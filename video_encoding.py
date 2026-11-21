"""Validated video settings and deterministic FFmpeg argument generation."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from i18n import t
from process_control import ffmpeg_transcode_args, local_media_input, text_kwargs

ASPECT_MODES = {"preserve", "fit", "fill", "stretch"}
CONTAINER_VIDEO_CODECS = {
    "MP4": {"libx264"},
    "MOV": {"libx264"},
    "MKV": {"libx264", "libvpx-vp9"},
    "WEBM": {"libvpx-vp9"},
    "AVI": {"mpeg4"},
}
CONTAINER_AUDIO_CODECS = {
    "MP4": {"aac"},
    "MOV": {"aac"},
    "MKV": {"aac", "libopus"},
    "WEBM": {"libopus"},
    "AVI": {"libmp3lame"},
}
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_TIME = re.compile(r"\btime=(\d+):(\d+):(\d+(?:\.\d+)?)")
_OUT_TIME = re.compile(r"^out_time=(\d+):(\d+):(\d+(?:\.\d+)?)$")


@dataclass(slots=True)
class ProgressLimiter:
    """Limit UI notifications while always allowing completion updates."""

    interval_seconds: float = 0.1
    last_emit: float = float("-inf")

    def should_emit(self, now: float, completed: bool = False) -> bool:
        if completed or now - self.last_emit >= self.interval_seconds:
            self.last_emit = now
            return True
        return False


@dataclass(frozen=True, slots=True)
class VideoSettings:
    video_codec: str
    audio_codec: str
    width: int | None
    height: int | None
    aspect_mode: str
    fps_cap: int | None
    crf: int
    remove_audio: bool = False
    background: str = "black"
    pixel_format: str = "yuv420p"
    faststart: bool = False
    max_size_mb: int | None = None

    @property
    def max_size_bytes(self) -> int | None:
        return None if self.max_size_mb is None else self.max_size_mb * 1024 * 1024


def validate_video_settings(container: str, settings: VideoSettings) -> None:
    normalized = container.upper()
    if settings.video_codec not in CONTAINER_VIDEO_CODECS.get(normalized, set()):
        raise ValueError(
            t(
                "video.codec_incompatible",
                codec=settings.video_codec,
                container=container,
            )
        )
    if (
        not settings.remove_audio
        and settings.audio_codec not in CONTAINER_AUDIO_CODECS.get(normalized, set())
    ):
        raise ValueError(
            t(
                "video.audio_codec_incompatible",
                codec=settings.audio_codec,
                container=container,
            )
        )
    if settings.aspect_mode not in ASPECT_MODES:
        raise ValueError(t("video.aspect_invalid"))
    if (settings.width is None) != (settings.height is None):
        raise ValueError(t("video.resolution_needs_both"))
    if settings.width is not None and (settings.width < 2 or settings.height < 2):
        raise ValueError(t("video.resolution_min"))
    if settings.aspect_mode in {"fit", "fill", "stretch"} and settings.width is None:
        raise ValueError(t("video.mode_requires_resolution"))
    if settings.fps_cap is not None and settings.fps_cap <= 0:
        raise ValueError(t("video.fps_positive"))
    if settings.max_size_mb is not None and settings.max_size_mb <= 0:
        raise ValueError(t("ui.validate.max_size_positive"))
    if not 0 <= settings.crf <= 63:
        raise ValueError(t("video.crf_invalid"))
    if not re.fullmatch(
        r"(?:[A-Za-z]+|#[0-9A-Fa-f]{6}|0x[0-9A-Fa-f]{6})", settings.background
    ):
        raise ValueError(t("video.background_invalid"))


def build_video_filter(settings: VideoSettings) -> str:
    width, height = settings.width, settings.height
    filters: list[str] = []
    if width is None:
        filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    elif settings.aspect_mode == "preserve":
        filters.append(
            f"scale=w='min(iw,{width})':h='min(ih,{height})':"
            "force_original_aspect_ratio=decrease:force_divisible_by=2"
        )
    elif settings.aspect_mode == "fit":
        even_width, even_height = _even(width), _even(height)
        filters.extend(
            (
                f"scale={even_width}:{even_height}:force_original_aspect_ratio=decrease:force_divisible_by=2",
                f"pad={even_width}:{even_height}:(ow-iw)/2:(oh-ih)/2:color={settings.background}",
            )
        )
    elif settings.aspect_mode == "fill":
        even_width, even_height = _even(width), _even(height)
        filters.extend(
            (
                f"scale={even_width}:{even_height}:"
                "force_original_aspect_ratio=increase:force_divisible_by=2",
                f"crop={even_width}:{even_height}",
            )
        )
    else:
        filters.append(f"scale={_even(width)}:{_even(height)}")
    if settings.fps_cap is not None:
        filters.append(f"fps=fps='min({settings.fps_cap},source_fps)'")
    return ",".join(filters)


def build_video_args(container: str, settings: VideoSettings) -> list[str]:
    validate_video_settings(container, settings)
    args = [
        "-c:v",
        settings.video_codec,
        "-pix_fmt",
        settings.pixel_format,
        "-vf",
        build_video_filter(settings),
    ]
    if settings.video_codec == "mpeg4":
        args.extend(("-q:v", str(max(1, min(31, round(settings.crf / 2))))))
    else:
        args.extend(("-crf", str(settings.crf)))
    if settings.video_codec == "libx264":
        args.extend(("-preset", "slow"))
    elif settings.video_codec == "libvpx-vp9":
        args.extend(("-b:v", "0"))
    if settings.remove_audio:
        args.append("-an")
    else:
        args.extend(("-c:a", settings.audio_codec))
        args.extend(("-b:a", "160k" if settings.audio_codec == "libopus" else "192k"))
    if settings.faststart and container.upper() in {"MP4", "MOV"}:
        args.extend(("-movflags", "+faststart"))
    if settings.max_size_bytes is not None:
        args.extend(("-fs", str(settings.max_size_bytes)))
    return args


def build_video_command(
    ffmpeg: str, source: Path, output: Path, container: str, settings: VideoSettings
) -> list[str]:
    return [
        ffmpeg,
        *ffmpeg_transcode_args(source),
        *build_video_args(container, settings),
        str(output),
    ]


def _even(value: int) -> int:
    return max(2, value - (value % 2))


def parse_progress_seconds(line: str) -> float | None:
    match = _OUT_TIME.search(line.strip()) or _TIME.search(line)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_duration(text: str) -> float | None:
    match = _DURATION.search(text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def probe_media(ffmpeg: str, source: Path) -> tuple[float | None, bool]:
    """Return duration and whether an audio stream is present."""
    completed = subprocess.run(
        [ffmpeg, "-nostdin", "-hide_banner", *local_media_input(source)],
        capture_output=True,
        timeout=15,
        check=False,
        **text_kwargs(),
    )
    details = completed.stderr
    return parse_duration(details), bool(re.search(r"Stream #.*Audio:", details))


def estimated_size_mb(
    duration_seconds: float | None, video_kbps: int | None
) -> float | None:
    if duration_seconds is None or video_kbps is None:
        return None
    return duration_seconds * video_kbps / 8 / 1000
