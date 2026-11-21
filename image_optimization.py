"""Storage optimizations for still images."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageChops

MAX_CANDIDATE_PIXELS = 4_000_000


def compact_image(image: Image.Image, image_format: str) -> Image.Image:
    if image_format in {"PNG", "TIFF"}:
        if image.mode in {"1", "L", "LA", "P", "I;16", "I;16B"}:
            if image_format == "PNG" or (
                "transparency" not in image.info
                and (image.palette is None or image.palette.mode != "RGBA")
            ):
                return image
        if image.mode == "I;16L":
            return image.convert("I;16") if image_format == "PNG" else image
    if image_format == "GIF" and image.mode == "P":
        return image
    rgba = image.convert("RGBA")
    if image_format in {"PNG", "TIFF", "BMP", "AVIF"} and rgba.getchannel(
        "A"
    ).getextrema() == (255, 255):
        rgb = rgba.convert("RGB")
        # A converted palette's tRNS index is invalid for RGB samples.
        rgb.info.pop("transparency", None)
        return rgb
    return rgba


def exact_palette(image: Image.Image) -> tuple[Image.Image, int] | None:
    if (
        image.mode not in {"RGB", "RGBA"}
        or image.width * image.height > MAX_CANDIDATE_PIXELS
    ):
        return None
    colors = image.getcolors(maxcolors=256)
    if colors is None:
        return None
    mode = (
        Image.Quantize.FASTOCTREE if image.mode == "RGBA" else Image.Quantize.MEDIANCUT
    )
    palette = image.quantize(colors=len(colors), method=mode, dither=Image.Dither.NONE)
    restored = palette.convert(image.mode)
    if ImageChops.difference(image, restored).getbbox(alpha_only=False):
        return None
    used = palette.getextrema()[1] + 1
    bits = next(depth for depth in (1, 2, 4, 8) if used <= 1 << depth)
    return palette, bits


def keep_smaller_candidate(path: Path, encode: Callable[[Path], None]) -> bool:
    with TemporaryDirectory(prefix=".image-opt-", dir=path.parent) as folder:
        candidate = Path(folder) / path.name
        try:
            encode(candidate)
            if not 0 < candidate.stat().st_size < path.stat().st_size:
                return False
            candidate.replace(path)
        except (OSError, ValueError):
            return False
    return True
