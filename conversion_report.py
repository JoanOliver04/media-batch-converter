"""Versioned, privacy-aware JSON reports for conversion operations."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Any, BinaryIO

from conversion_results import BatchSummary, FileResult
from image_validation import ImageWarning
from version import APP_VERSION


SCHEMA_VERSION = 1
APPLICATION_VERSION = APP_VERSION
HASH_CHUNK_SIZE = 1024 * 1024


class HashCancelled(Exception):
    pass


def sha256_file(
    path: Path,
    cancel_event: Event | None = None,
    chunk_size: int = HASH_CHUNK_SIZE,
    opener=open,
) -> tuple[str, str | None]:
    """Hash final bytes in chunks and warn if size or mtime changes."""
    before = path.stat()
    digest = hashlib.sha256()
    with opener(path, "rb") as stream:
        _hash_stream(stream, digest, cancel_event, chunk_size)
    after = path.stat()
    warning = None
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        warning = "El archivo cambió durante el cálculo de SHA-256."
    return digest.hexdigest(), warning


def _hash_stream(
    stream: BinaryIO,
    digest,
    cancel_event: Event | None,
    chunk_size: int,
) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise HashCancelled
        chunk = stream.read(chunk_size)
        if not chunk:
            return
        digest.update(chunk)


def _safe_path(path: Path | None, root: Path, absolute: bool) -> str | None:
    if path is None:
        return None
    if absolute:
        return str(path.resolve(strict=False))
    try:
        return (
            path.resolve(strict=False)
            .relative_to(root.resolve(strict=False))
            .as_posix()
        )
    except ValueError:
        return path.name


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return value.name
    return value


def warning_entry(
    warning: ImageWarning | str, source_root: Path, absolute_paths: bool
) -> dict[str, Any]:
    if isinstance(warning, ImageWarning):
        return {
            "code": warning.code.value,
            "severity": warning.severity.value,
            "message": warning.message,
            "details": _json_safe(warning.details),
            "source": _safe_path(warning.source, source_root, absolute_paths),
        }
    return {
        "code": "OPERATION_WARNING",
        "severity": "warning",
        "message": str(warning),
        "details": {},
        "source": None,
    }


def file_entry(
    result: FileResult,
    source_root: Path,
    output_root: Path,
    absolute_paths: bool,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "source": _safe_path(result.source_path, source_root, absolute_paths),
        "output": _safe_path(result.output_path, output_root, absolute_paths),
        "status": result.status.value,
        "originalBytes": result.original_bytes,
        "outputBytes": result.output_bytes,
        "warnings": [
            warning_entry(warning, source_root, absolute_paths)
            for warning in result.warnings
        ],
        "error": result.error_message,
    }
    optional = {
        "width": result.width,
        "height": result.height,
        "outputWidth": result.output_width,
        "outputHeight": result.output_height,
        "quality": result.quality,
        "encodingMode": result.encoder_mode,
        "sha256": result.sha256,
    }
    entry.update({key: value for key, value in optional.items() if value is not None})
    if result.animation_mode is not None:
        entry["animationMode"] = result.animation_mode
        entry["frameCount"] = result.frame_count
        entry["animationLoop"] = result.animation_loop
        entry["frameDurationsMs"] = list(result.frame_durations_ms)
    if result.frames:
        entry["frames"] = [
            {
                "output": _safe_path(frame.output_path, output_root, absolute_paths),
                "durationMs": frame.duration_ms,
                "outputBytes": frame.output_bytes,
                "sha256": frame.sha256,
            }
            for frame in result.frames
        ]
    return entry


def build_report(
    summary: BatchSummary,
    source_root: Path,
    output_root: Path,
    media_type: str,
    output_format: str,
    settings: dict[str, Any],
    started_at: datetime,
    completed_at: datetime,
    absolute_paths: bool = False,
) -> dict[str, Any]:
    files = [
        file_entry(result, source_root, output_root, absolute_paths)
        for result in summary.results
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "applicationVersion": APPLICATION_VERSION,
        "startedAt": started_at.astimezone(timezone.utc).isoformat(),
        "completedAt": completed_at.astimezone(timezone.utc).isoformat(),
        "elapsedMilliseconds": round(summary.elapsed_seconds * 1000),
        "mediaType": media_type,
        "outputFormat": output_format.lower(),
        "settings": _json_safe(settings),
        "summary": {
            "discovered": summary.files_discovered,
            "processed": summary.files_processed,
            "converted": summary.converted,
            "skipped": summary.skipped,
            "failed": summary.failed,
            "cancelled": summary.cancelled,
            "originalBytes": summary.original_bytes,
            "outputBytes": summary.output_bytes,
        },
        "files": files,
    }


def report_path(output_root: Path, completed_at: datetime) -> Path:
    try:
        existing = {entry.name.casefold() for entry in output_root.iterdir()}
    except FileNotFoundError:
        existing = set()
    plain = output_root / "conversion_report.json"
    if plain.name.casefold() not in existing:
        return plain
    stamp = completed_at.astimezone(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    stamped = output_root / f"conversion_report_{stamp}.json"
    if stamped.name.casefold() not in existing:
        return stamped
    for index in range(2, 10_002):
        candidate = output_root / f"conversion_report_{stamp}_{index}.json"
        if candidate.name.casefold() not in existing:
            return candidate
    raise FileExistsError("No se encontró un nombre libre para el informe.")


def write_report_atomic(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
