"""Base compartida por los paneles que convierten mediante FFmpeg."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from audio_encoding import encoder_available
from conversion_results import FileResult, ResultStatus, safe_file_size
from error_handling import describe_error
from filename_normalization import path_key
from i18n import t
from output_policy import (
    OutputAction,
    OutputPlan,
    OutputPolicy,
    cleanup_temporary,
    commit_output,
    plan_output,
)
from runtime_environment import resolve_ffmpeg
from ui.base import BatchCancelled, ConverterPanel
from ui.formats import batch_name_collision_keys, desired_output_path
from video_encoding import ProgressLimiter, parse_progress_seconds, probe_media

logging.getLogger(__name__).addHandler(logging.NullHandler())


@dataclass(frozen=True, slots=True)
class FFmpegBatch:
    """Ajustes resueltos una sola vez para todo el lote."""

    ffmpeg: str
    source_root: Path
    destination: Path
    extension: str
    codec_args: list[str]
    policy: OutputPolicy
    normalize: bool
    generate_report: bool
    audio_only: bool
    name_collisions: set[str]
    total: int


class FFmpegPanel(ConverterPanel):
    """Descubrimiento, política de salida e informes sobre procesos FFmpeg.

    Audio y vídeo comparten esta base en lugar de heredar uno del otro.
    """

    def run_ffmpeg(self, command: list[str], progress_callback=None) -> None:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=flags,
        )
        self.active_process = process
        stderr_lines: list[str] = []
        try:
            if process.stderr is not None:
                for line in process.stderr:
                    stderr_lines.append(line.rstrip())
                    if len(stderr_lines) > 200:
                        del stderr_lines[:50]
                    seconds = parse_progress_seconds(line)
                    if seconds is not None and progress_callback is not None:
                        progress_callback(seconds)
            process.wait()
        finally:
            self.active_process = None
        if process.returncode:
            detail = [line for line in stderr_lines if line]
            raise RuntimeError(detail[-1] if detail else t("ui.ffmpeg.failed"))

    def convert_ffmpeg_batch(
        self,
        source_root: Path,
        files: list[Path],
        output_format: str,
        extension: str,
        codec_args: list[str],
        initial_errors: list[str],
        options: dict[str, object] | None,
        audio_only: bool,
        required_encoder: str | tuple[str, ...] | None = None,
    ) -> None:
        destination = source_root / f"convertidos_{output_format.lower()}"
        ffmpeg = self._resolve_encoder(required_encoder)
        if ffmpeg is None:
            return

        options = options or {}
        normalize = bool(options.get("normalize_filenames", False))
        batch = FFmpegBatch(
            ffmpeg=ffmpeg,
            source_root=source_root,
            destination=destination,
            extension=extension,
            codec_args=codec_args,
            policy=OutputPolicy(options.get("output_policy", OutputPolicy.SKIP)),
            normalize=normalize,
            generate_report=bool(options.get("generate_report", False)),
            audio_only=audio_only,
            name_collisions=batch_name_collision_keys(
                destination, source_root, files, extension, normalize
            ),
            total=len(files),
        )

        results: list[FileResult] = []
        for index, source in enumerate(files, 1):
            if self.cancel_event.is_set():
                self._finish(batch, results, initial_errors, cancelled=True)
                return
            self.root.after(
                0,
                self.status.set,
                f"Convirtiendo {index}/{batch.total}: {source.name}",
            )
            try:
                results.append(self._convert_file(batch, source, index))
            except BatchCancelled:
                self._finish(batch, results, initial_errors, cancelled=True)
                return
            self.report_progress(index, batch.total, source.name)
        self.root.after(0, self.status.set, "Finalizando lote…")
        self._finish(
            batch, results, initial_errors, cancelled=self.cancel_event.is_set()
        )

    def _resolve_encoder(
        self, required_encoder: str | tuple[str, ...] | None
    ) -> str | None:
        """Devuelve la ruta de FFmpeg, o None tras informar del motivo."""
        ffmpeg_info = resolve_ffmpeg()
        if ffmpeg_info is None:
            self.root.after(
                0,
                self.fail,
                t("ui.ffmpeg.unavailable"),
            )
            return None
        ffmpeg = str(ffmpeg_info.path)
        required = (
            (required_encoder,)
            if isinstance(required_encoder, str)
            else required_encoder or ()
        )
        missing = [codec for codec in required if not encoder_available(ffmpeg, codec)]
        if missing:
            self.root.after(
                0,
                self.fail,
                t("ui.ffmpeg.missing_encoders", codecs=", ".join(missing)),
            )
            return None
        return ffmpeg

    def _finish(
        self,
        batch: FFmpegBatch,
        results: list[FileResult],
        discovery_errors: list[str],
        cancelled: bool,
    ) -> None:
        self.root.after(
            0,
            self.finish_results,
            batch.destination,
            results,
            discovery_errors,
            cancelled,
        )

    def _convert_file(self, batch: FFmpegBatch, source: Path, index: int) -> FileResult:
        started = time.monotonic()
        original_bytes = safe_file_size(source)
        plan: OutputPlan | None = None
        collision = False
        try:
            desired = desired_output_path(
                batch.destination,
                batch.source_root,
                source,
                batch.extension,
                batch.normalize,
            )
            desired.parent.mkdir(parents=True, exist_ok=True)
            collision = path_key(desired) in batch.name_collisions
            plan = plan_output(source, desired, batch.policy)
            if not plan.should_convert:
                return FileResult(
                    source,
                    plan.target,
                    ResultStatus.SKIPPED,
                    original_bytes,
                    error_message=(
                        t("ui.skip.exists")
                        if plan.action is OutputAction.SKIP_EXISTS
                        else t("ui.skip.up_to_date")
                    ),
                    processing_seconds=time.monotonic() - started,
                    output_action=plan.action.value,
                    name_collision=collision,
                )

            self._encode(batch, source, plan, index)
            commit_output(plan)
            checksum, checksum_warnings = self.checksum_for_report(
                plan.target, batch.generate_report
            )
            return FileResult(
                source,
                plan.target,
                ResultStatus.CONVERTED,
                original_bytes,
                safe_file_size(plan.target),
                processing_seconds=time.monotonic() - started,
                output_action=plan.action.value,
                name_collision=collision,
                warnings=checksum_warnings,
                sha256=checksum,
            )
        except Exception as error:
            logging.getLogger(__name__).exception("conversion_failed source=%s", source)
            cleanup_temporary(plan)
            if self.cancel_event.is_set():
                raise BatchCancelled from error
            return FileResult(
                source,
                None,
                ResultStatus.FAILED,
                original_bytes,
                error_message=describe_error(error).message,
                processing_seconds=time.monotonic() - started,
                name_collision=collision,
            )

    def _encode(
        self, batch: FFmpegBatch, source: Path, plan: OutputPlan, index: int
    ) -> None:
        command = [batch.ffmpeg, "-y", "-i", str(source), "-map_metadata", "0"]
        duration = None
        if batch.audio_only:
            command.append("-vn")
        else:
            duration, _has_audio = probe_media(batch.ffmpeg, source)
            command.extend(("-progress", "pipe:2", "-nostats"))
        command.extend((*batch.codec_args, str(plan.temporary)))

        if batch.audio_only:
            self.run_ffmpeg(command)
            return

        limiter = ProgressLimiter()

        def update_media_progress(seconds: float) -> None:
            if duration and duration > 0:
                fraction = min(1.0, max(0.0, seconds / duration))
                if not limiter.should_emit(time.monotonic(), completed=fraction >= 1.0):
                    return
                self.root.after(
                    0, self.progress.configure, {"value": (index - 1) + fraction}
                )

        self.run_ffmpeg(command, update_media_progress)
