"""Structured per-file results and aggregate batch statistics."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ResultStatus(StrEnum):
    CONVERTED = "converted"
    SKIPPED = "skipped"
    FAILED = "failed"


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
        size_line = f"Espacio ahorrado: {format_bytes(summary.bytes_saved)}"
        percent_line = (
            f"Reducción: {reduction:.1f}%"
            if reduction is not None
            else "Reducción: no aplicable"
        )
    else:
        size_line = f"Aumento de tamaño: {format_bytes(-summary.bytes_saved)}"
        percent_line = (
            f"Incremento: {-reduction:.1f}%"
            if reduction is not None
            else "Incremento: no aplicable"
        )
    state = "Cancelada" if summary.cancelled else "Completada"
    return "\n".join(
        (
            f"Estado: {state}",
            f"Archivos descubiertos: {summary.files_discovered}",
            f"Archivos procesados: {summary.files_processed}",
            f"Convertidos correctamente: {summary.converted}",
            f"Omitidos: {summary.skipped}",
            f"  - Destino existente: {summary.skipped_existing}",
            f"  - Destino actualizado: {summary.skipped_up_to_date}",
            f"Sobrescritos: {summary.overwritten}",
            f"Renombrados por colisión: {summary.renamed}",
            f"Fallidos: {summary.failed}",
            f"Tamaño original procesado: {format_bytes(summary.original_bytes)}",
            f"Tamaño de salida: {format_bytes(summary.output_bytes)}",
            size_line,
            percent_line,
            f"Tiempo transcurrido: {format_duration(summary.elapsed_seconds)}",
        )
    )
