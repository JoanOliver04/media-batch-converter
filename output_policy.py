"""Collision policies and atomic output replacement helpers."""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class OutputPolicy(StrEnum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    UNIQUE = "unique"
    SOURCE_NEWER = "source_newer"


class OutputAction(StrEnum):
    CONVERT = "converted"
    OVERWRITE = "overwritten"
    RENAME = "renamed"
    SKIP_EXISTS = "skipped_exists"
    SKIP_UP_TO_DATE = "skipped_up_to_date"


@dataclass(frozen=True, slots=True)
class OutputPlan:
    target: Path
    temporary: Path | None
    action: OutputAction
    reserved: bool = False

    @property
    def should_convert(self) -> bool:
        return self.temporary is not None


_NAME_LOCK = threading.Lock()
_RESERVED_PATHS: set[str] = set()
MAX_UNIQUE_ATTEMPTS = 10_000


def _temporary_path(target: Path) -> Path:
    token = uuid.uuid4().hex
    return target.with_name(f".{target.stem}.{token}.tmp{target.suffix}")


def _case_insensitive_names(directory: Path) -> set[str]:
    try:
        return {entry.name.casefold() for entry in directory.iterdir()}
    except FileNotFoundError:
        return set()


def _existing_path(desired: Path) -> Path | None:
    try:
        return next(
            entry
            for entry in desired.parent.iterdir()
            if entry.name.casefold() == desired.name.casefold()
        )
    except (FileNotFoundError, StopIteration):
        return None


def unique_path(desired: Path) -> Path:
    """Return deterministic _2 naming while considering case-insensitive collisions."""
    with _NAME_LOCK:
        existing = _case_insensitive_names(desired.parent)
        if desired.name.casefold() not in existing:
            return desired
        for index in range(2, MAX_UNIQUE_ATTEMPTS + 2):
            candidate = desired.with_name(f"{desired.stem}_{index}{desired.suffix}")
            if candidate.name.casefold() not in existing:
                return candidate
    raise FileExistsError("No se pudo encontrar un nombre de salida libre.")


def _reserve_unique_path(desired: Path) -> Path:
    with _NAME_LOCK:
        existing = _case_insensitive_names(desired.parent)
        for index in range(1, MAX_UNIQUE_ATTEMPTS + 2):
            candidate = (
                desired
                if index == 1
                else desired.with_name(f"{desired.stem}_{index}{desired.suffix}")
            )
            key = str(candidate.resolve(strict=False)).casefold()
            if candidate.name.casefold() not in existing and key not in _RESERVED_PATHS:
                _RESERVED_PATHS.add(key)
                return candidate
    raise FileExistsError("No se pudo reservar un nombre de salida libre.")


def _release_reservation(plan: OutputPlan | None) -> None:
    if plan is not None and plan.reserved:
        key = str(plan.target.resolve(strict=False)).casefold()
        with _NAME_LOCK:
            _RESERVED_PATHS.discard(key)


def plan_output(source: Path, desired: Path, policy: OutputPolicy | str) -> OutputPlan:
    policy = OutputPolicy(policy)
    existing_target = _existing_path(desired)

    if policy is OutputPolicy.UNIQUE:
        target = _reserve_unique_path(desired)
        action = OutputAction.RENAME if target != desired else OutputAction.CONVERT
        return OutputPlan(target, _temporary_path(target), action, reserved=True)
    if existing_target is None:
        return OutputPlan(desired, _temporary_path(desired), OutputAction.CONVERT)
    if policy is OutputPolicy.SKIP:
        return OutputPlan(existing_target, None, OutputAction.SKIP_EXISTS)
    if policy is OutputPolicy.SOURCE_NEWER:
        if source.stat().st_mtime_ns <= existing_target.stat().st_mtime_ns:
            return OutputPlan(existing_target, None, OutputAction.SKIP_UP_TO_DATE)
        return OutputPlan(
            existing_target,
            _temporary_path(existing_target),
            OutputAction.OVERWRITE,
        )
    return OutputPlan(
        existing_target, _temporary_path(existing_target), OutputAction.OVERWRITE
    )


def commit_output(plan: OutputPlan) -> None:
    if plan.temporary is None:
        raise ValueError("A skipped output plan cannot be committed.")
    try:
        os.replace(plan.temporary, plan.target)
    finally:
        _release_reservation(plan)


def cleanup_temporary(plan: OutputPlan | None) -> None:
    try:
        if plan is not None and plan.temporary is not None:
            plan.temporary.unlink(missing_ok=True)
    finally:
        _release_reservation(plan)
