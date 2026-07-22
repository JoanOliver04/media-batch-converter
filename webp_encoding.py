"""Deterministic WebP mode selection independent from Tkinter."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from PIL import Image


class WebPMode(StrEnum):
    AUTOMATIC = "automatic"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


SAMPLE_MAX_DIMENSION = 128
LOW_COLOR_THRESHOLD = 256
LARGE_PIXEL_THRESHOLD = 1_000_000
LARGE_DIMENSION_THRESHOLD = 1_600


def has_meaningful_alpha(image: Image.Image) -> bool:
    """Return whether at least one pixel is not fully opaque."""
    if "A" not in image.getbands() and "transparency" not in image.info:
        return False
    alpha = image.convert("RGBA").getchannel("A")
    minimum, _maximum = alpha.getextrema()
    return minimum < 255


def sampled_color_count(image: Image.Image) -> int:
    """Estimate colour complexity from a bounded RGBA thumbnail."""
    sample = image.convert("RGBA")
    sample.thumbnail((SAMPLE_MAX_DIMENSION, SAMPLE_MAX_DIMENSION))
    colors = sample.getcolors(maxcolors=LOW_COLOR_THRESHOLD + 1)
    return LOW_COLOR_THRESHOLD + 1 if colors is None else len(colors)


def choose_automatic_webp_mode(image: Image.Image, source: Path | str) -> WebPMode:
    """Choose a stable WebP mode from format, animation, size and complexity."""
    source_suffix = Path(source).suffix.casefold()
    source_format = (image.format or "").upper()
    if source_suffix in {".jpg", ".jpeg"} or source_format == "JPEG":
        return WebPMode.LOSSY
    if getattr(image, "is_animated", False):
        return WebPMode.LOSSLESS

    width, height = image.size
    is_large = (
        width * height >= LARGE_PIXEL_THRESHOLD
        or max(width, height) >= LARGE_DIMENSION_THRESHOLD
    )
    low_color = image.mode == "P" or sampled_color_count(image) <= LOW_COLOR_THRESHOLD

    if low_color:
        return WebPMode.LOSSLESS
    if is_large or has_meaningful_alpha(image):
        return WebPMode.LOSSY
    return WebPMode.LOSSY


def resolve_webp_mode(
    requested: WebPMode | str, image: Image.Image, source: Path | str
) -> WebPMode:
    mode = WebPMode(requested)
    if mode is WebPMode.AUTOMATIC:
        return choose_automatic_webp_mode(image, source)
    return mode


def webp_save_options(mode: WebPMode | str, quality: int) -> dict[str, object]:
    """Build Pillow options for a resolved explicit WebP mode."""
    resolved = WebPMode(mode)
    if resolved is WebPMode.AUTOMATIC:
        raise ValueError("Automatic WebP mode must be resolved before encoding.")
    if resolved is WebPMode.LOSSLESS:
        return {"lossless": True, "method": 6, "exact": True}
    return {
        "lossless": False,
        "quality": max(1, min(100, int(quality))),
        "method": 6,
        "exact": True,
    }


def webp_controls_visible(output_format: str) -> bool:
    return output_format.casefold() == "webp"
