"""Animated-image policy and Pillow capability helpers."""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image

from i18n import t

MAX_ANIMATION_FRAMES = 500
MAX_WEBP_DURATION_BYTES = 200 * 1024 * 1024


class AnimationMode(StrEnum):
    PRESERVE = "preserve"
    EXTRACT_FRAMES = "extract_frames"
    FIRST_FRAME = "first_frame"


@lru_cache(maxsize=None)
def animation_supported(output_format: str) -> bool:
    """Probe Pillow by writing and reopening a tiny animation in memory."""
    normalized = output_format.upper()
    Image.init()
    if normalized not in Image.SAVE_ALL:
        return False
    first = Image.new("RGBA", (2, 2), (255, 0, 0, 0))
    second = Image.new("RGBA", (2, 2), (0, 0, 255, 128))
    stream = BytesIO()
    try:
        first.save(
            stream,
            format=normalized,
            save_all=True,
            append_images=[second],
            duration=[40, 90],
            loop=2,
        )
        stream.seek(0)
        with Image.open(stream) as restored:
            if not getattr(restored, "is_animated", False) or restored.n_frames != 2:
                return False
            if restored.info.get("loop") != 2:
                return False
            if normalized == "WEBP":
                # Pillow writes WebP durations but does not expose them when reading.
                return True
            durations = []
            for index in range(restored.n_frames):
                restored.seek(index)
                durations.append(restored.info.get("duration"))
            return durations == [40, 90]
    except (KeyError, OSError, TypeError, ValueError):
        return False


def animation_too_large(frame_count: int | None) -> bool:
    return frame_count is not None and frame_count > MAX_ANIMATION_FRAMES


def webp_frame_durations(path: Path) -> tuple[int, ...]:
    """Read ANMF duration fields that Pillow currently does not expose."""
    try:
        if path.stat().st_size > MAX_WEBP_DURATION_BYTES:
            return ()
    except OSError:
        return ()
    with path.open("rb") as stream:
        header = stream.read(12)
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WEBP":
            return ()
        durations: list[int] = []
        while True:
            chunk_header = stream.read(8)
            if len(chunk_header) < 8:
                break
            chunk_type = chunk_header[:4]
            chunk_size = int.from_bytes(chunk_header[4:], "little")
            if chunk_type == b"ANMF" and chunk_size >= 16:
                payload = stream.read(16)
                if len(payload) >= 15:
                    durations.append(int.from_bytes(payload[12:15], "little"))
                leftover = chunk_size - len(payload)
                if leftover > 0:
                    stream.seek(leftover, os.SEEK_CUR)
            else:
                stream.seek(chunk_size, os.SEEK_CUR)
            if chunk_size % 2:
                stream.seek(1, os.SEEK_CUR)
        return tuple(durations)


def existing_directory(desired: Path) -> Path | None:
    try:
        return next(
            entry
            for entry in desired.parent.iterdir()
            if entry.is_dir() and entry.name.casefold() == desired.name.casefold()
        )
    except (FileNotFoundError, StopIteration):
        return None


def frame_directory(desired: Path, maximum_attempts: int = 10_000) -> Path:
    """Return a new case-insensitive deterministic directory name."""
    try:
        existing = {entry.name.casefold() for entry in desired.parent.iterdir()}
    except FileNotFoundError:
        existing = set()
    for index in range(1, maximum_attempts + 1):
        candidate = (
            desired if index == 1 else desired.with_name(f"{desired.name}_{index}")
        )
        if candidate.name.casefold() not in existing:
            return candidate
    raise FileExistsError(t("animation.no_free_frame_directory"))


def frame_number_width(frame_count: int) -> int:
    return max(4, len(str(max(1, frame_count))))
