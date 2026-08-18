"""Normalize embedded images so Word and PDF writers share one safe path."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from documents.security import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS

MAX_RENDER_WIDTH = 1600
MAX_RENDER_HEIGHT = 1600


@dataclass(frozen=True, slots=True)
class NormalizedImage:
    data: bytes
    format: str
    width: int
    height: int


def normalize_image(data: bytes) -> NormalizedImage | None:
    """Decode *data* with Pillow and return PNG or JPEG bytes, or None if unsafe."""
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    try:
        with Image.open(BytesIO(data)) as image:
            if image.width <= 0 or image.height <= 0:
                return None
            if image.width * image.height > MAX_IMAGE_PIXELS:
                return None
            image.load()
            oriented = ImageOps.exif_transpose(image)
            oriented.thumbnail((MAX_RENDER_WIDTH, MAX_RENDER_HEIGHT))
            has_alpha = oriented.mode in {"RGBA", "LA"} or (
                oriented.mode == "P" and "transparency" in oriented.info
            )
            if has_alpha:
                converted = oriented.convert("RGBA")
                output_format = "PNG"
            else:
                converted = oriented.convert("RGB")
                output_format = "JPEG"
            buffer = BytesIO()
            converted.save(buffer, format=output_format)
            payload = buffer.getvalue()
            if not payload or len(payload) > MAX_IMAGE_BYTES:
                return None
            return NormalizedImage(
                payload, output_format, converted.width, converted.height
            )
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError):
        return None
