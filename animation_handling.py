"""Animated-image policy and Pillow capability helpers."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image


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


def webp_frame_durations(path: Path) -> tuple[int, ...]:
    """Read ANMF duration fields that Pillow currently does not expose."""
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return ()
    durations: list[int] = []
    offset = 12
    while offset + 8 <= len(data):
        chunk_type = data[offset : offset + 4]
        chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        payload = offset + 8
        if chunk_type == b"ANMF" and chunk_size >= 16 and payload + 15 <= len(data):
            durations.append(
                int.from_bytes(data[payload + 12 : payload + 15], "little")
            )
        offset = payload + chunk_size + (chunk_size % 2)
    return tuple(durations)


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
    raise FileExistsError("No se encontró una carpeta libre para los fotogramas.")


def frame_number_width(frame_count: int) -> int:
    return max(4, len(str(max(1, frame_count))))
