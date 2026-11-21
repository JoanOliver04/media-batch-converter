"""Base compartida por los paneles que convierten mediante FFmpeg."""

from __future__ import annotations

import logging
import subprocess
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from audio_encoding import encoder_available
from conversion_results import FileResult, ResultStatus, safe_file_size
from error_handling import UserFacingError, describe_error
from filename_normalization import path_key
from i18n import t
from output_policy import (
    OutputAction,
    OutputPlan,
    OutputPlanner,
    OutputPolicy,
    cleanup_temporary,
    commit_output,
    policy_for_name_collision,
)
from process_control import ffmpeg_transcode_args, stop_process, text_kwargs
from runtime_environment import resolve_ffmpeg
from ui.base import BatchCancelled, ConverterPanel
from ui.formats import batch_name_collision_keys, batch_output_root, desired_output_path
from video_encoding import ProgressLimiter, parse_duration, parse_progress_seconds

logging.getLogger(__name__).addHandler(logging.NullHandler())


@dataclass(frozen=True, slots=True)
class FFmpegBatch:
    """Ajustes resueltos una sola vez para todo el lote."""

    ffmpeg: str
    source_root: Path
    destination: Path
    planner: OutputPlanner
    extension: str
    codec_args: list[str]
    policy: OutputPolicy
    normalize: bool
    generate_report: bool
    audio_only: bool
    name_collisions: set[str]
    total: int
    output_limit_bytes: int | None


class FFmpegPanel(ConverterPanel):
    """Descubrimiento, política de salida e informes sobre procesos FFmpeg.

    Audio y vídeo comparten esta base en lugar de heredar uno del otro.
    """

    def run_ffmpeg(
        self, command: list[str], progress_callback: Callable[[float, float], None]
    ) -> None:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **text_kwargs(),
        )
        self.active_process = process
        stderr_lines: deque[str] = deque(maxlen=200)
        duration = None
        try:
            if self.cancel_event.is_set():
                stop_process(process)
            if process.stderr is not None:
                with process.stderr:
                    for line in process.stderr:
                        if self.cancel_event.is_set():
                            stop_process(process)
                            break
                        stderr_lines.append(line.rstrip())
                        if duration is None:
                            duration = parse_duration(line)
                        seconds = parse_progress_seconds(line)
                        if seconds is not None and duration:
                            progress_callback(seconds, duration)
            process.wait()
        finally:
            stop_process(process)
            self.active_process = None
        if self.cancel_event.is_set():
            raise InterruptedError(t("error.cancelled"))
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
        output_limit_bytes: int | None = None,
    ) -> None:
        options = options or {}
        destination = batch_output_root(source_root, output_format, options)
        ffmpeg = self._resolve_encoder(required_encoder)
        if ffmpeg is None:
            return

        normalize = bool(options.get("normalize_filenames", False))
        batch = FFmpegBatch(
            ffmpeg=ffmpeg,
            source_root=source_root,
            destination=destination,
            planner=OutputPlanner(),
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
            output_limit_bytes=output_limit_bytes,
        )

        results: list[FileResult] = []
        for index, source in enumerate(files, 1):
            if self.cancel_event.is_set():
                self._finish(batch, results, initial_errors, cancelled=True)
                return
            self.root.after(
                0,
                self.status.set,
                t(
                    "ui.status.converting",
                    index=index,
                    total=batch.total,
                    name=source.name,
                ),
            )
            try:
                results.append(self._convert_file(batch, source, index))
            except BatchCancelled:
                self._finish(batch, results, initial_errors, cancelled=True)
                return
            self.report_progress(index, batch.total, source.name)
        self.root.after(0, self.status.set, t("ui.status.finalizing"))
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
        batch.planner.prune_empty_directories()
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
            collision = path_key(desired) in batch.name_collisions
            plan = batch.planner.plan(
                source, desired, policy_for_name_collision(batch.policy, collision)
            )
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
            if self.cancel_event.is_set():
                raise BatchCancelled()
            output_bytes = plan.temporary.stat().st_size
            if (
                batch.output_limit_bytes is not None
                and output_bytes > batch.output_limit_bytes
            ):
                raise UserFacingError(t("ui.video.output_exceeds_limit"))
            commit_output(plan)
            checksum, checksum_warnings = self.checksum_for_report(
                plan.target, batch.generate_report
            )
            return FileResult(
                source,
                plan.target,
                ResultStatus.CONVERTED,
                original_bytes,
                output_bytes,
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
        if self.cancel_event.is_set():
            raise InterruptedError(t("error.cancelled"))
        command = [batch.ffmpeg, *ffmpeg_transcode_args(source)]
        if batch.audio_only:
            command.append("-vn")
        command.extend((*batch.codec_args, str(plan.temporary)))
        limiter = ProgressLimiter()

        def update_media_progress(seconds: float, duration: float) -> None:
            fraction = min(1.0, max(0.0, seconds / duration))
            if limiter.should_emit(time.monotonic(), completed=fraction >= 1.0):
                self.root.after(
                    0, self.progress.configure, {"value": (index - 1) + fraction}
                )

        self.run_ffmpeg(command, update_media_progress)
