"""Validated audio settings and shell-free FFmpeg argument generation."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from presets import AudioSettings


CONTAINER_CODECS = {
    "M4A": {"aac"},
    "WAV": {"pcm_s16le", "pcm_s24le"},
    "MP3": {"libmp3lame"},
    "FLAC": {"flac"},
    "OGG": {"libvorbis"},
    "OPUS": {"libopus"},
}
_TIME_PATTERN = re.compile(r"\btime=(\d+):(\d+):(\d+(?:\.\d+)?)")


def validate_audio_settings(container: str, settings: AudioSettings) -> None:
    normalized = container.upper()
    if settings.codec not in CONTAINER_CODECS.get(normalized, set()):
        raise ValueError(f"El códec {settings.codec} no es compatible con {container}.")
    if settings.sample_rate is not None and settings.sample_rate <= 0:
        raise ValueError("La frecuencia de muestreo debe ser positiva.")
    if settings.channels not in {None, 1, 2}:
        raise ValueError(
            "Los canales deben conservarse, convertirse a mono o a estéreo."
        )
    if settings.bitrate_kbps is not None and settings.bitrate_kbps <= 0:
        raise ValueError("El bitrate debe ser positivo.")
    if settings.codec == "aac" and settings.profile != "aac_low":
        raise ValueError("Los presets AAC deben declarar explícitamente AAC-LC.")
    if settings.normalize_loudness:
        raise NotImplementedError(
            "La normalización de sonoridad está configurada pero aún no implementada."
        )


def build_audio_args(container: str, settings: AudioSettings) -> list[str]:
    validate_audio_settings(container, settings)
    args = ["-c:a", settings.codec]
    if settings.codec == "aac":
        args.extend(("-profile:a", "aac_low"))
    if settings.codec == "flac":
        args.extend(("-compression_level", "8"))
    if settings.sample_rate is not None:
        args.extend(("-ar", str(settings.sample_rate)))
    if settings.channels is not None:
        args.extend(("-ac", str(settings.channels)))
    if settings.bitrate_kbps is not None:
        args.extend(("-b:a", f"{settings.bitrate_kbps}k"))
    return args


def build_audio_command(
    ffmpeg: str,
    source: Path,
    output: Path,
    settings: AudioSettings,
    container: str,
) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-map_metadata",
        "0",
        "-vn",
        *build_audio_args(container, settings),
        str(output),
    ]


def manual_audio_settings(
    container: str,
    quality: int,
    sample_rate: int | None,
    channels: int | None,
    bitrate_kbps: int | None,
) -> AudioSettings:
    codec = {
        "M4A": "aac",
        "WAV": "pcm_s24le",
        "MP3": "libmp3lame",
        "FLAC": "flac",
        "OGG": "libvorbis",
        "OPUS": "libopus",
    }[container.upper()]
    if container.upper() in {"WAV", "FLAC"}:
        bitrate_kbps = None
    elif bitrate_kbps is None:
        bitrate_kbps = round(64 + max(1, min(100, quality)) * 2.56)
    return AudioSettings(
        codec,
        sample_rate,
        channels,
        bitrate_kbps,
        "lossless" if container.upper() in {"WAV", "FLAC"} else "bitrate",
        "aac_low" if codec == "aac" else None,
    )


def encoder_available(ffmpeg: str, codec: str) -> bool:
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and bool(
        re.search(
            rf"^\s*[A-Z.]+\s+{re.escape(codec)}\s", completed.stdout, re.MULTILINE
        )
    )


def parse_ffmpeg_time(line: str) -> float | None:
    match = _TIME_PATTERN.search(line)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
