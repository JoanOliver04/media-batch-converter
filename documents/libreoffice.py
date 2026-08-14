"""Optional LibreOffice headless conversion, resolved like FFmpeg."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Event

from documents.errors import DocumentError
from documents.formats import DOCUMENT_FORMATS, libreoffice_supports, normalize_format
from error_handling import ErrorCode
from i18n import t

logging.getLogger(__name__).addHandler(logging.NullHandler())

LIBREOFFICE_TIMEOUT_SECONDS = 180
LIBREOFFICE_FILTERS = {
    "PDF": "pdf",
    "DOCX": "docx",
    "ODT": "odt",
    "RTF": "rtf",
    "TXT": "txt:Text",
    "HTML": "html",
    "XLSX": "xlsx",
    "CSV": "csv",
    "PPTX": "pptx",
}


@dataclass(frozen=True, slots=True)
class LibreOfficeInfo:
    path: Path
    version: str


@lru_cache(maxsize=1)
def resolve_libreoffice() -> LibreOfficeInfo | None:
    for candidate in _candidates():
        if not candidate.is_file():
            continue
        version = _libreoffice_version(candidate)
        if version:
            return LibreOfficeInfo(candidate.resolve(), version)
    return None


def _conversion_executable(office: LibreOfficeInfo) -> Path:
    """soffice.com is fine for --version but can crash on Windows convert-to."""
    if office.path.suffix.casefold() == ".com":
        executable = office.path.with_suffix(".exe")
        if executable.is_file():
            return executable
    return office.path


def convert_with_libreoffice(
    source: Path,
    output: Path,
    dest_format: str,
    cancel_event: Event | None = None,
    office: LibreOfficeInfo | None = None,
) -> None:
    office = office or resolve_libreoffice()
    if office is None:
        raise DocumentError(t("document.libreoffice_unavailable"), ErrorCode.NOT_FOUND)
    dest = normalize_format(dest_format)
    source_format = source.suffix
    if not libreoffice_supports(_guess_from_suffix(source), dest):
        raise DocumentError(
            t(
                "document.pair_unsupported",
                source=source_format.lstrip(".").upper() or "?",
                dest=dest,
            )
        )
    target = LIBREOFFICE_FILTERS[dest]
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="mbc-lo-"))
    profile = work / "profile"
    profile.mkdir()
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    command = [
        str(_conversion_executable(office)),
        "--headless",
        "--nologo",
        "--nofirststartwizard",
        "--norestore",
        "--nolockcheck",
        "--nodefault",
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        "--convert-to",
        target,
        "--outdir",
        str(work),
        str(source.resolve()),
    ]
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=flags,
        )
        try:
            _stdout, stderr = _wait_for_process(process, cancel_event)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.communicate()
            raise DocumentError(t("document.libreoffice_timeout")) from error
        except InterruptedError:
            process.kill()
            process.communicate()
            raise
        if process.returncode:
            detail = (stderr or "").strip().splitlines()
            logging.getLogger(__name__).error(
                "libreoffice_failed code=%s detail=%s",
                process.returncode,
                detail[-1] if detail else "",
            )
            raise DocumentError(
                t("document.libreoffice_failed"), ErrorCode.PROCESS_FAILED
            )
        produced = _find_output(work, dest)
        shutil.move(str(produced), str(output))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _find_output(directory: Path, dest_format: str) -> Path:
    extension = DOCUMENT_FORMATS[dest_format]
    matches = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file()
        and path.suffix.casefold() == extension
        and "profile" not in path.parts
    )
    if not matches:
        raise DocumentError(
            t("document.libreoffice_no_output"), ErrorCode.PROCESS_FAILED
        )
    return matches[0]


def _wait_for_process(
    process: subprocess.Popen[str], cancel_event: Event | None
) -> tuple[str, str]:
    deadline = time.monotonic() + LIBREOFFICE_TIMEOUT_SECONDS
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError(t("error.cancelled"))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, LIBREOFFICE_TIMEOUT_SECONDS)
        try:
            stdout, stderr = process.communicate(timeout=min(0.4, remaining))
        except subprocess.TimeoutExpired:
            continue
        return stdout or "", stderr or ""


def _guess_from_suffix(path: Path) -> str:
    from documents.formats import format_from_path

    return format_from_path(path) or path.suffix.lstrip(".").upper()


def _candidates() -> list[Path]:
    found: list[Path] = []
    configured = os.environ.get("LIBREOFFICE_PATH")
    if configured:
        found.append(Path(configured))
    names = (
        ("soffice.com", "soffice.exe", "soffice")
        if sys.platform == "win32"
        else ("soffice", "libreoffice")
    )
    roots = [
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMW6432"),
        r"C:\Program Files",
        r"C:\Program Files (x86)",
    ]
    for root in roots:
        if not root:
            continue
        program = Path(root) / "LibreOffice" / "program"
        for name in names:
            found.append(program / name)
    which_names = (
        ("soffice.com", "soffice.exe", "soffice")
        if sys.platform == "win32"
        else ("soffice", "libreoffice")
    )
    for name in which_names:
        located = shutil.which(name)
        if located:
            found.append(Path(located))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in found:
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _libreoffice_version(executable: Path) -> str | None:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode not in {0, 1}:
        return None
    first = (completed.stdout or completed.stderr).splitlines()
    if not first:
        return t("diagnostics.libreoffice_unknown_version")
    tokens = first[0].split()
    if len(tokens) >= 2 and tokens[1][:1].isdigit():
        return f"{tokens[0]} {tokens[1]}"
    return first[0].strip()
