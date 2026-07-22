"""Portable output filename normalization without modifying source paths."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path


MAX_BASENAME_LENGTH = 100
SAFE_PREFIX = "asset_"
WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_UNSUPPORTED = re.compile(r"[^a-z0-9]+")


def normalize_basename(filename: str, max_length: int = MAX_BASENAME_LENGTH) -> str:
    """Return a lowercase ASCII basename suitable for common filesystems."""
    if max_length < len("asset"):
        raise ValueError("max_length must allow the fallback basename")
    stem = Path(filename.rstrip(" .")).stem
    decomposed = unicodedata.normalize("NFKD", stem)
    ascii_text = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character) and character.isascii()
    ).lower()
    normalized = _UNSUPPORTED.sub("_", ascii_text).strip("_")
    if not normalized:
        normalized = "asset"
    if normalized[0].isdigit():
        normalized = SAFE_PREFIX + normalized
    if normalized in WINDOWS_RESERVED_NAMES:
        normalized = SAFE_PREFIX + normalized
    normalized = normalized[:max_length].rstrip("_")
    return normalized or "asset"


def output_filename(source: Path, extension: str, enabled: bool) -> str:
    basename = normalize_basename(source.name) if enabled else source.stem
    suffix = extension if extension.startswith(".") else f".{extension}"
    return f"{basename}{suffix}"


def collision_keys(paths: list[Path]) -> set[str]:
    """Return case-insensitive path keys generated more than once in a batch."""
    keys = [str(path.resolve(strict=False)).casefold() for path in paths]
    counts = Counter(keys)
    return {key for key, count in counts.items() if count > 1}


def path_key(path: Path) -> str:
    return str(path.resolve(strict=False)).casefold()
