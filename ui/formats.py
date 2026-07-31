"""Formatos admitidos y resolución de rutas de salida."""

from __future__ import annotations

from pathlib import Path

from batch_processing import safe_output_directory
from filename_normalization import collision_keys, output_filename

IMAGE_FORMATS = {
    "WebP": ("WEBP", ".webp"),
    "JPG": ("JPEG", ".jpg"),
    "PNG": ("PNG", ".png"),
    "ICO (favicon)": ("ICO", ".ico"),
    "TIFF": ("TIFF", ".tiff"),
    "BMP": ("BMP", ".bmp"),
    "GIF": ("GIF", ".gif"),
}
AUDIO_FORMATS = {
    "MP3": ".mp3",
    "WAV": ".wav",
    "FLAC": ".flac",
    "OGG": ".ogg",
    "M4A": ".m4a",
    "Opus": ".opus",
}
VIDEO_FORMATS = {
    "MP4": ".mp4",
    "MKV": ".mkv",
    "WebM": ".webm",
    "MOV": ".mov",
    "AVI": ".avi",
}
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".ico",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
}
AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".flac",
    ".ogg",
    ".oga",
    ".m4a",
    ".aac",
    ".opus",
    ".wma",
}
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".webm",
    ".mov",
    ".avi",
    ".m4v",
    ".wmv",
    ".mpg",
    ".mpeg",
}


def desired_output_path(
    output_root: Path,
    source_root: Path,
    source: Path,
    extension: str,
    normalize: bool,
) -> Path:
    directory = safe_output_directory(output_root, source_root, source)
    return directory / output_filename(source, extension, normalize)


def batch_name_collision_keys(
    output_root: Path,
    source_root: Path,
    sources: list[Path],
    extension: str,
    normalize: bool,
) -> set[str]:
    return collision_keys(
        [
            desired_output_path(output_root, source_root, source, extension, normalize)
            for source in sources
        ]
    )
