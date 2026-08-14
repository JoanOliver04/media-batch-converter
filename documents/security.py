"""Source inspection: type sniffing, size limits and zip-bomb guards."""

from __future__ import annotations

import zipfile
from pathlib import Path

from documents.errors import DocumentError
from documents.formats import DetectedKind, format_from_path
from error_handling import ErrorCode
from i18n import t

MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 200 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_ZIP_RATIO = 100
MAX_PAGES = 2_000
MAX_BLOCKS = 50_000
MAX_TABLE_CELLS = 200_000
MAX_IMAGES = 80
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
OLE_MAGIC = b"\xd0\xcf\x11\xe0"
ZIP_MAGIC = b"PK"
PDF_MAGIC = b"%PDF"
RTF_MAGIC = b"{\\rtf"

_ZIP_FORMATS = frozenset({"DOCX", "XLSX", "PPTX", "ODT", "ODP"})
_OLE_FORMATS = frozenset({"DOC", "XLS", "PPT"})
_TEXT_FORMATS = frozenset({"TXT", "MD", "CSV", "HTML"})


def inspect_source(path: Path) -> DetectedKind:
    """Reject unsafe or implausible sources before a reader opens them."""
    source = Path(path)
    if source.is_symlink():
        raise DocumentError(t("document.symlink_rejected"), ErrorCode.UNSUPPORTED)
    if not source.is_file():
        raise DocumentError(t("document.not_a_file"), ErrorCode.NOT_FOUND)
    try:
        size = source.stat().st_size
    except OSError as error:
        raise DocumentError(t("document.unreadable"), ErrorCode.IO_ERROR) from error
    if size > MAX_FILE_BYTES:
        raise DocumentError(
            t("document.file_too_large", limit_mb=MAX_FILE_BYTES // (1024 * 1024)),
            ErrorCode.UNSUPPORTED,
        )
    if size == 0:
        raise DocumentError(t("document.empty_file"), ErrorCode.INVALID_SETTINGS)

    kind = sniff_kind(source)
    declared = format_from_path(source)
    _assert_kind_matches(declared, kind)
    if kind is DetectedKind.ZIP_PACKAGE:
        inspect_zip(source)
    return kind


def sniff_kind(path: Path) -> DetectedKind:
    header = _read_header(path, 512)
    stripped = header.lstrip()
    if header.startswith(PDF_MAGIC):
        return DetectedKind.PDF
    if header.startswith(ZIP_MAGIC):
        return DetectedKind.ZIP_PACKAGE
    if header.startswith(OLE_MAGIC):
        return DetectedKind.OLE
    if stripped.startswith(RTF_MAGIC):
        return DetectedKind.RTF
    if _looks_like_html(stripped):
        return DetectedKind.HTML
    if _looks_like_text(header):
        return DetectedKind.TEXT
    return DetectedKind.UNKNOWN


def inspect_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            total = 0
            for info in archive.infolist():
                if info.file_size > MAX_ZIP_MEMBER_BYTES:
                    raise DocumentError(t("document.zip_member_too_large"))
                if (
                    info.compress_type != zipfile.ZIP_STORED
                    and info.compress_size > 0
                    and info.file_size / info.compress_size > MAX_ZIP_RATIO
                ):
                    raise DocumentError(t("document.zip_ratio_too_high"))
                total += info.file_size
                if total > MAX_ZIP_UNCOMPRESSED_BYTES:
                    raise DocumentError(t("document.zip_uncompressed_too_large"))
    except zipfile.BadZipFile as error:
        raise DocumentError(t("document.corrupt_package")) from error


def _assert_kind_matches(declared: str | None, kind: DetectedKind) -> None:
    if declared is None:
        raise DocumentError(t("document.unknown_extension"))
    expected = {
        DetectedKind.PDF: {"PDF"},
        DetectedKind.ZIP_PACKAGE: _ZIP_FORMATS,
        DetectedKind.OLE: _OLE_FORMATS,
        DetectedKind.RTF: {"RTF"},
        DetectedKind.HTML: {"HTML"},
        DetectedKind.TEXT: _TEXT_FORMATS,
    }
    allowed = expected.get(kind)
    if allowed is None:
        raise DocumentError(t("document.unrecognized_type"))
    if declared not in allowed:
        raise DocumentError(
            t(
                "document.extension_mismatch",
                extension=declared,
                detected=kind.value,
            )
        )


def _read_header(path: Path, size: int) -> bytes:
    try:
        with path.open("rb") as stream:
            return stream.read(size)
    except OSError as error:
        raise DocumentError(t("document.unreadable"), ErrorCode.IO_ERROR) from error


def _looks_like_html(payload: bytes) -> bool:
    lowered = payload[:200].lstrip().lower()
    return lowered.startswith((b"<!doctype html", b"<html", b"<head", b"<body"))


def _looks_like_text(payload: bytes) -> bool:
    if not payload:
        return False
    if b"\x00" in payload:
        return False
    sample = payload.replace(b"\r", b"").replace(b"\n", b"").replace(b"\t", b"")
    if not sample:
        return True
    printable = sum(32 <= byte <= 126 or byte >= 160 for byte in sample)
    return printable / len(sample) >= 0.85
