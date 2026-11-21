"""Collision policies and atomic output replacement helpers."""

from __future__ import annotations

import logging
import os
import sys
import threading
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from batch_processing import UnsafePathError, is_link
from i18n import t


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
_RESERVED_PATHS: dict[str, Path] = {}
MAX_UNIQUE_ATTEMPTS = 10_000


class OutputPlanner:
    """One worker's directory index and ownership record for a conversion batch."""

    def __init__(self) -> None:
        self._entries: dict[Path, dict[str, Path]] = {}
        self._created: list[Path] = []

    def ensure_directory(self, directory: Path) -> None:
        missing: list[Path] = []
        current = directory
        while not current.is_dir():
            missing.append(current)
            if current == current.parent:
                raise FileNotFoundError(directory)
            current = current.parent
        if is_link(current):
            raise UnsafePathError()
        for path in reversed(missing):
            try:
                path.mkdir()
            except FileExistsError:
                if is_link(path) or not path.is_dir():
                    raise
            else:
                self._created.append(path)

    def plan(self, source: Path, desired: Path, policy: OutputPolicy) -> OutputPlan:
        self.ensure_directory(desired.parent)
        if desired.parent not in self._entries:
            self._entries[desired.parent] = _directory_entries(desired.parent)
        entries = self._entries[desired.parent]
        plan = plan_output(source, desired, policy, entries=entries)
        entries[plan.target.name.casefold()] = plan.target
        return plan

    def prune_empty_directories(self) -> None:
        for path in reversed(self._created):
            try:
                if not is_link(path):
                    path.rmdir()
            except OSError:
                continue


def _temporary_path(target: Path) -> Path:
    token = uuid.uuid4().hex
    return target.with_name(f".mbc-{token}.tmp{target.suffix}")


def _directory_entries(directory: Path) -> dict[str, Path]:
    try:
        return {entry.name.casefold(): entry for entry in directory.iterdir()}
    except FileNotFoundError:
        return {}


def _existing_path(desired: Path, entries: dict[str, Path]) -> Path | None:
    known = entries.get(desired.name.casefold(), desired)
    if os.path.lexists(known):
        return known
    if known != desired and os.path.lexists(desired):
        return desired
    return None


def unique_path(desired: Path) -> Path:
    """Return deterministic _2 naming while considering case-insensitive collisions."""
    with _NAME_LOCK:
        existing = _directory_entries(desired.parent)
        if desired.name.casefold() not in existing:
            return desired
        for index in range(2, MAX_UNIQUE_ATTEMPTS + 2):
            candidate = desired.with_name(f"{desired.stem}_{index}{desired.suffix}")
            if candidate.name.casefold() not in existing:
                return candidate
    raise FileExistsError(t("policy.no_free_name"))


def _plan_unique_output(desired: Path, entries: dict[str, Path]) -> OutputPlan:
    with _NAME_LOCK:
        for index in range(1, MAX_UNIQUE_ATTEMPTS + 2):
            candidate = (
                desired
                if index == 1
                else desired.with_name(f"{desired.stem}_{index}{desired.suffix}")
            )
            key = str(candidate.absolute()).casefold()
            if (
                key not in _RESERVED_PATHS
                and _existing_path(candidate, entries) is None
            ):
                temporary = _temporary_path(candidate)
                _RESERVED_PATHS[key] = temporary
                action = OutputAction.CONVERT if index == 1 else OutputAction.RENAME
                return OutputPlan(candidate, temporary, action, reserved=True)
    raise FileExistsError(t("policy.no_reservation"))


def _release_reservation(plan: OutputPlan | None) -> None:
    if plan is not None and plan.reserved:
        key = str(plan.target.absolute()).casefold()
        with _NAME_LOCK:
            if _RESERVED_PATHS.get(key) == plan.temporary:
                del _RESERVED_PATHS[key]


def policy_for_name_collision(
    policy: OutputPolicy | str, collision: bool
) -> OutputPolicy:
    """Keep both sources when several files would share one destination name."""
    resolved = OutputPolicy(policy)
    if collision and resolved is not OutputPolicy.UNIQUE:
        return OutputPolicy.UNIQUE
    return resolved


def plan_output(
    source: Path,
    desired: Path,
    policy: OutputPolicy | str,
    *,
    entries: dict[str, Path] | None = None,
) -> OutputPlan:
    policy = OutputPolicy(policy)
    if entries is None:
        entries = _directory_entries(desired.parent)
    if policy is OutputPolicy.UNIQUE:
        return _plan_unique_output(desired, entries)

    existing_target = _existing_path(desired, entries)
    if existing_target is None:
        return OutputPlan(desired, _temporary_path(desired), OutputAction.CONVERT)
    if policy is OutputPolicy.SKIP:
        return OutputPlan(existing_target, None, OutputAction.SKIP_EXISTS)
    if (
        is_link(existing_target)
        or not existing_target.is_file()
        or source.samefile(existing_target)
    ):
        raise UnsafePathError()
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
        if is_link(plan.target.parent) or is_link(plan.target):
            raise UnsafePathError()
        if plan.action is OutputAction.OVERWRITE:
            os.replace(plan.temporary, plan.target)
        else:
            publish_new_file(plan.temporary, plan.target)
    finally:
        _release_reservation(plan)


def publish_new_file(temporary: Path, target: Path) -> None:
    """Publish a completed file without replacing a destination created concurrently."""
    if sys.platform == "win32":
        temporary.rename(target)
    else:
        os.link(temporary, target)
        temporary.unlink()


def cleanup_temporary(plan: OutputPlan | None) -> None:
    try:
        if plan is not None and plan.temporary is not None:
            plan.temporary.unlink(missing_ok=True)
    except OSError:
        logging.getLogger(__name__).exception(
            "output_cleanup_failed path=%s", plan.temporary
        )
    finally:
        _release_reservation(plan)
