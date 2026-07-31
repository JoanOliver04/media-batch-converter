"""Structured per-file results and aggregate batch statistics."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from i18n import t
from image_validation import ImageWarning


class ResultStatus(StrEnum):
    CONVERTED = "converted"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FrameResult:
    output_path: Path
    duration_ms: int
    output_bytes: int
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class FileResult:
    source_path: Path
    output_path: Path | None
    status: ResultStatus
    original_bytes: int
    output_bytes: int = 0
    error_message: str | None = None
    processing_seconds: float = 0.0
    encoder_mode: str | None = None
    output_action: str | None = None
    name_collision: bool = False
    warnings: tuple[ImageWarning | str, ...] = field(default_factory=tuple)
    width: int | None = None
    height: int | None = None
    output_width: int | None = None
    output_height: int | None = None
    quality: int | None = None
    sha256: str | None = None
    animation_mode: str | None = None
    frame_count: int | None = None
    animation_loop: int | None = None
    frame_durations_ms: tuple[int, ...] = field(default_factory=tuple)
    frames: tuple[FrameResult, ...] = field(default_factory=tuple)

    @property
    def bytes_saved(self) -> int:
        return self.original_bytes - self.output_bytes

    @property
    def percentage_change(self) -> float | None:
        if self.original_bytes == 0:
            return None
        return self.bytes_saved / self.original_bytes * 100


@dataclass(frozen=True, slots=True)
class BatchSummary:
    files_discovered: int
    results: tuple[FileResult, ...]
    elapsed_seconds: float
    cancelled: bool = False
    discovery_errors: tuple[str, ...] = field(default_factory=tuple)
    operation_warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def files_processed(self) -> int:
        return len(self.results)

    def count(self, status: ResultStatus) -> int:
        return sum(result.status is status for result in self.results)

    @property
    def converted(self) -> int:
        return self.count(ResultStatus.CONVERTED)

    @property
    def skipped(self) -> int:
        return self.count(ResultStatus.SKIPPED)

    @property
    def failed(self) -> int:
        return self.count(ResultStatus.FAILED) + len(self.discovery_errors)

    def action_count(self, action: str) -> int:
        return sum(result.output_action == action for result in self.results)

    @property
    def overwritten(self) -> int:
        return self.action_count("overwritten")

    @property
    def renamed(self) -> int:
        return self.action_count("renamed")

    @property
    def skipped_existing(self) -> int:
        return self.action_count("skipped_exists")

    @property
    def skipped_up_to_date(self) -> int:
        return self.action_count("skipped_up_to_date")

    @property
    def name_collisions(self) -> int:
        return sum(result.name_collision for result in self.results)

    @property
    def warning_count(self) -> int:
        return sum(len(result.warnings) for result in self.results)

    def animation_count(self, mode: str) -> int:
        return sum(result.animation_mode == mode for result in self.results)

    @property
    def original_bytes(self) -> int:
        return sum(result.original_bytes for result in self.results)

    @property
    def converted_original_bytes(self) -> int:
        return sum(
            result.original_bytes
            for result in self.results
            if result.status is ResultStatus.CONVERTED
        )

    @property
    def output_bytes(self) -> int:
        return sum(
            result.output_bytes
            for result in self.results
            if result.status is ResultStatus.CONVERTED
        )

    @property
    def bytes_saved(self) -> int:
        return self.converted_original_bytes - self.output_bytes

    @property
    def percentage_reduction(self) -> float | None:
        if self.converted_original_bytes == 0:
            return None
        return self.bytes_saved / self.converted_original_bytes * 100


def safe_file_size(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(abs(value))
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.2f} {unit}"


def format_duration(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return (
        f"{hours:02d}:{minutes:02d}:{secs:02d}"
        if hours
        else f"{minutes:02d}:{secs:02d}"
    )


def summary_text(summary: BatchSummary) -> str:
    reduction = summary.percentage_reduction
    if summary.bytes_saved >= 0:
        size_line = f"{t('summary.space_saved')}: {format_bytes(summary.bytes_saved)}"
        percent_label = t("summary.reduction")
        percent_value = f"{reduction:.1f}%" if reduction is not None else None
    else:
        size_line = (
            f"{t('summary.size_increase')}: {format_bytes(-summary.bytes_saved)}"
        )
        percent_label = t("summary.increment")
        percent_value = f"{-reduction:.1f}%" if reduction is not None else None
    percent_line = f"{percent_label}: {percent_value or t('summary.not_applicable')}"
    state = t(
        "summary.state.cancelled" if summary.cancelled else "summary.state.completed"
    )
    return "\n".join(
        (
            f"{t('summary.state')}: {state}",
            f"{t('summary.files_discovered')}: {summary.files_discovered}",
            f"{t('summary.files_processed')}: {summary.files_processed}",
            f"{t('summary.converted')}: {summary.converted}",
            f"{t('summary.skipped')}: {summary.skipped}",
            f"{t('summary.skipped_existing')}: {summary.skipped_existing}",
            f"{t('summary.skipped_up_to_date')}: {summary.skipped_up_to_date}",
            f"{t('summary.overwritten')}: {summary.overwritten}",
            f"{t('summary.renamed')}: {summary.renamed}",
            f"{t('summary.name_collisions')}: {summary.name_collisions}",
            f"{t('summary.warning_count')}: {summary.warning_count}",
            f"{t('summary.animation_preserved')}: {summary.animation_count('preserve')}",
            f"{t('summary.animation_extracted')}: {summary.animation_count('extract_frames')}",
            f"{t('summary.animation_first_frame')}: {summary.animation_count('first_frame')}",
            f"{t('summary.failed')}: {summary.failed}",
            f"{t('summary.original_size')}: {format_bytes(summary.original_bytes)}",
            f"{t('summary.output_size')}: {format_bytes(summary.output_bytes)}",
            size_line,
            percent_line,
            f"{t('summary.elapsed')}: {format_duration(summary.elapsed_seconds)}",
            f"{t('summary.operation_warnings')}: {len(summary.operation_warnings)}",
        )
    )
