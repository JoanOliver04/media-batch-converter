"""Runtime dependency checks, resource lookup and privacy-aware diagnostics."""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app_logging import log_path
from version import APP_NAME, APP_VERSION

INSTALL_COMMAND = "python -m pip install -r requirements.txt"


@dataclass(frozen=True, slots=True)
class FFmpegInfo:
    path: Path
    source: str
    version: str


def resource_path(relative: str | Path) -> Path:
    """Resolve a bundled resource in source, one-folder or one-file mode."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def application_directory() -> Path:
    return (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )


def missing_python_dependencies() -> list[str]:
    missing = []
    for import_name, distribution in (
        ("PIL", "Pillow"),
        ("imageio_ffmpeg", "imageio-ffmpeg"),
    ):
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(distribution)
    return missing


def _ffmpeg_version(executable: Path) -> str | None:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    first_line = completed.stdout.splitlines()
    return first_line[0].strip() if first_line else "FFmpeg (versión desconocida)"


def resolve_ffmpeg() -> FFmpegInfo | None:
    candidates: list[tuple[Path, str]] = []
    bundled_directories = (
        application_directory() / "ffmpeg",
        resource_path("ffmpeg"),
    )
    for directory in bundled_directories:
        bundled = [directory / "ffmpeg.exe"]
        try:
            bundled.extend(sorted(directory.glob("ffmpeg*.exe")))
        except OSError:
            pass
        for candidate in bundled:
            if candidate not in (item[0] for item in candidates):
                candidates.append((candidate, "incluido"))
    try:
        provider = importlib.import_module("imageio_ffmpeg")
        candidates.append((Path(provider.get_ffmpeg_exe()), "imageio-ffmpeg"))
    except (ImportError, OSError, RuntimeError):
        pass
    system = shutil.which("ffmpeg")
    if system:
        candidates.append((Path(system), "sistema"))
    for path, source in candidates:
        if path.is_file():
            version = _ffmpeg_version(path)
            if version:
                return FFmpegInfo(path.resolve(), source, version)
    return None


def private_path(path: Path) -> str:
    text = str(path)
    home = str(Path.home())
    if os.path.normcase(text).startswith(os.path.normcase(home)):
        return "~" + text[len(home) :]
    return text


def diagnostics_text(ffmpeg: FFmpegInfo | None = None) -> str:
    try:
        pillow = importlib.import_module("PIL").__version__
        from PIL import Image

        extensions = sorted(
            {
                extension.upper().lstrip(".")
                for extension in Image.registered_extensions()
            }
        )
        image_formats = ", ".join(extensions)
    except ImportError:
        pillow = "No disponible"
        image_formats = "No disponibles"
    try:
        imageio_version = importlib.import_module("imageio_ffmpeg").__version__
    except ImportError:
        imageio_version = "No disponible (se puede usar FFmpeg incluido o del sistema)"
    ffmpeg = ffmpeg if ffmpeg is not None else resolve_ffmpeg()
    lines = [
        f"Aplicación: {APP_NAME} {APP_VERSION}",
        f"Sistema: {platform.platform()}",
        f"Python: {platform.python_version()}{' (empaquetado)' if getattr(sys, 'frozen', False) else ''}",
        f"Pillow: {pillow}",
        f"imageio-ffmpeg: {imageio_version}",
        f"FFmpeg: {ffmpeg.version if ffmpeg else 'No disponible'}",
        f"Proveedor FFmpeg: {ffmpeg.source if ffmpeg else 'Ninguno'}",
        f"Ruta FFmpeg: {private_path(ffmpeg.path) if ffmpeg else 'No disponible'}",
        f"Registro local: {private_path(log_path())}",
        f"Formatos de imagen registrados: {image_formats}",
    ]
    return "\n".join(lines)
