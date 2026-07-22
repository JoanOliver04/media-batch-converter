"""Validated video settings and deterministic FFmpeg argument generation."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


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


def validate_video_settings(container: str, settings: VideoSettings) -> None:
    normalized = container.upper()
    if settings.video_codec not in CONTAINER_VIDEO_CODECS.get(normalized, set()):
        raise ValueError(
            f"El códec de vídeo {settings.video_codec} no es compatible con {container}."
        )
    if (
        not settings.remove_audio
        and settings.audio_codec not in CONTAINER_AUDIO_CODECS.get(normalized, set())
    ):
        raise ValueError(
            f"El códec de audio {settings.audio_codec} no es compatible con {container}."
        )
    if settings.aspect_mode not in ASPECT_MODES:
        raise ValueError("El modo de relación de aspecto no es válido.")
    if (settings.width is None) != (settings.height is None):
        raise ValueError("La resolución requiere anchura y altura.")
    if settings.width is not None and (settings.width < 2 or settings.height < 2):
        raise ValueError("La resolución debe ser de al menos 2 × 2 píxeles.")
    if settings.aspect_mode in {"fit", "fill", "stretch"} and settings.width is None:
        raise ValueError("Este modo requiere una resolución de destino.")
    if settings.fps_cap is not None and settings.fps_cap <= 0:
        raise ValueError("La frecuencia de fotogramas debe ser positiva.")
    if not 0 <= settings.crf <= 63:
        raise ValueError("El nivel CRF no es válido.")
    if not re.fullmatch(
        r"(?:[A-Za-z]+|#[0-9A-Fa-f]{6}|0x[0-9A-Fa-f]{6})", settings.background
    ):
        raise ValueError(
            "El color de bandas debe ser un nombre o un valor hexadecimal."
        )


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
        filters.extend(
            (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={settings.background}",
            )
        )
    elif settings.aspect_mode == "fill":
        filters.extend(
            (
                f"scale={width}:{height}:force_original_aspect_ratio=increase",
                f"crop={width}:{height}",
            )
        )
    else:
        filters.append(f"scale={width}:{height}")
    if settings.fps_cap is not None:
        filters.append(f"fps=fps='min({settings.fps_cap},source_fps)'")
    return ",".join(filters)


def build_video_args(container: str, settings: VideoSettings) -> list[str]:
    validate_video_settings(container, settings)
    args = [
        "-c:v",
        settings.video_codec,
        "-crf",
        str(settings.crf),
        "-vf",
        build_video_filter(settings),
    ]
    if settings.video_codec == "libx264":
        args.extend(("-preset", "slow", "-pix_fmt", settings.pixel_format))
    elif settings.video_codec == "libvpx-vp9":
        args.extend(("-b:v", "0", "-pix_fmt", settings.pixel_format))
    if settings.remove_audio:
        args.append("-an")
    else:
        args.extend(("-c:a", settings.audio_codec))
        args.extend(("-b:a", "160k" if settings.audio_codec == "libopus" else "192k"))
    if settings.faststart and container.upper() in {"MP4", "MOV"}:
        args.extend(("-movflags", "+faststart"))
    return args


def build_video_command(
    ffmpeg: str, source: Path, output: Path, container: str, settings: VideoSettings
) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-map_metadata",
        "0",
        "-progress",
        "pipe:2",
        "-nostats",
        *build_video_args(container, settings),
        str(output),
    ]


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
    flags = (
        subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    )
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(source)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        creationflags=flags,
    )
    details = completed.stderr
    return parse_duration(details), bool(re.search(r"Stream #.*Audio:", details))


def estimated_size_mb(
    duration_seconds: float | None, video_kbps: int | None
) -> float | None:
    if duration_seconds is None or video_kbps is None:
        return None
    return duration_seconds * video_kbps / 8 / 1000
