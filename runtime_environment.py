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
from i18n import t
from process_control import text_kwargs
from version import APP_NAME, APP_VERSION

INSTALL_COMMAND = "python -m pip install -r requirements.txt"

DOCUMENT_PYTHON_DEPENDENCIES = (
    ("docx", "python-docx"),
    ("pypdf", "pypdf"),
    ("reportlab", "reportlab"),
    ("openpyxl", "openpyxl"),
    ("pptx", "python-pptx"),
)

#: Códigos estables del proveedor de FFmpeg; se traducen solo al mostrarse.
FFMPEG_SOURCE_BUNDLED = "bundled"
FFMPEG_SOURCE_SYSTEM = "system"
FFMPEG_SOURCE_IMAGEIO = "imageio-ffmpeg"


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
        *DOCUMENT_PYTHON_DEPENDENCIES,
    ):
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(distribution)
    return missing


def missing_document_dependencies() -> list[str]:
    missing = []
    for import_name, distribution in DOCUMENT_PYTHON_DEPENDENCIES:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(distribution)
    return missing


def _ffmpeg_version(executable: Path) -> str | None:
    try:
        completed = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            timeout=8,
            check=False,
            **text_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    first_line = completed.stdout.splitlines()
    return (
        first_line[0].strip() if first_line else t("diagnostics.ffmpeg_unknown_version")
    )


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
                candidates.append((candidate, FFMPEG_SOURCE_BUNDLED))
    try:
        provider = importlib.import_module("imageio_ffmpeg")
        candidates.append((Path(provider.get_ffmpeg_exe()), FFMPEG_SOURCE_IMAGEIO))
    except (ImportError, OSError, RuntimeError):
        pass
    system = shutil.which("ffmpeg")
    if system:
        candidates.append((Path(system), FFMPEG_SOURCE_SYSTEM))
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


def ffmpeg_source_label(source: str) -> str:
    """Traduce el código estable del proveedor de FFmpeg para mostrarlo."""
    return {
        FFMPEG_SOURCE_BUNDLED: t("diagnostics.source.bundled"),
        FFMPEG_SOURCE_SYSTEM: t("diagnostics.source.system"),
        FFMPEG_SOURCE_IMAGEIO: t("diagnostics.source.imageio"),
    }.get(source, source)


def diagnostics_text(ffmpeg: FFmpegInfo | None = None) -> str:
    unavailable = t("diagnostics.unavailable")
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
        pillow = unavailable
        image_formats = t("diagnostics.unavailable_plural")
    try:
        imageio_version = importlib.import_module("imageio_ffmpeg").__version__
    except ImportError:
        imageio_version = t("diagnostics.imageio_unavailable")
    ffmpeg = ffmpeg if ffmpeg is not None else resolve_ffmpeg()
    packaged = t("diagnostics.packaged_suffix") if getattr(sys, "frozen", False) else ""
    document_versions = []
    for import_name, distribution in DOCUMENT_PYTHON_DEPENDENCIES:
        try:
            module = importlib.import_module(import_name)
            document_versions.append(
                f"{distribution}: {getattr(module, '__version__', t('diagnostics.unavailable'))}"
            )
        except ImportError:
            document_versions.append(f"{distribution}: {unavailable}")
    try:
        from documents.libreoffice import resolve_libreoffice

        office = resolve_libreoffice()
    except Exception:
        office = None
    lines = [
        f"{t('diagnostics.line.application')}: {APP_NAME} {APP_VERSION}",
        f"{t('diagnostics.line.system')}: {platform.platform()}",
        f"{t('diagnostics.line.python')}: {platform.python_version()}{packaged}",
        f"Pillow: {pillow}",
        f"imageio-ffmpeg: {imageio_version}",
        f"FFmpeg: {ffmpeg.version if ffmpeg else unavailable}",
        f"{t('diagnostics.line.ffmpeg_provider')}: "
        f"{ffmpeg_source_label(ffmpeg.source) if ffmpeg else t('diagnostics.none')}",
        f"{t('diagnostics.line.ffmpeg_path')}: "
        f"{private_path(ffmpeg.path) if ffmpeg else unavailable}",
        f"{t('diagnostics.line.libreoffice')}: "
        f"{office.version if office else unavailable}",
        f"{t('diagnostics.line.libreoffice_path')}: "
        f"{private_path(office.path) if office else unavailable}",
        *document_versions,
        f"{t('diagnostics.line.log')}: {private_path(log_path())}",
        f"{t('diagnostics.line.image_formats')}: {image_formats}",
    ]
    return "\n".join(lines)
