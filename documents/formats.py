"""Document format catalogue and conversion capability matrix."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

DOCUMENT_FORMATS = {
    "PDF": ".pdf",
    "DOCX": ".docx",
    "ODT": ".odt",
    "RTF": ".rtf",
    "TXT": ".txt",
    "MD": ".md",
    "HTML": ".html",
    "XLSX": ".xlsx",
    "CSV": ".csv",
    "PPTX": ".pptx",
}

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".odt",
    ".rtf",
    ".txt",
    ".md",
    ".markdown",
    ".html",
    ".htm",
    ".xlsx",
    ".xls",
    ".csv",
    ".pptx",
    ".ppt",
    ".odp",
}

SUFFIX_TO_FORMAT = {
    ".pdf": "PDF",
    ".docx": "DOCX",
    ".doc": "DOC",
    ".odt": "ODT",
    ".rtf": "RTF",
    ".txt": "TXT",
    ".md": "MD",
    ".markdown": "MD",
    ".html": "HTML",
    ".htm": "HTML",
    ".xlsx": "XLSX",
    ".xls": "XLS",
    ".csv": "CSV",
    ".pptx": "PPTX",
    ".ppt": "PPT",
    ".odp": "ODP",
}

BUILTIN_READERS = frozenset({"PDF", "DOCX", "TXT", "MD", "HTML", "XLSX", "CSV", "PPTX"})
BUILTIN_WRITERS = frozenset({"PDF", "DOCX", "TXT", "MD", "HTML", "XLSX", "CSV", "PPTX"})
WRITER_INPUTS = frozenset({"DOCX", "DOC", "ODT", "RTF", "TXT", "HTML"})
CALC_INPUTS = frozenset({"XLSX", "XLS", "CSV"})
IMPRESS_INPUTS = frozenset({"PPTX", "PPT", "ODP"})
LIBREOFFICE_EXPORTS = (
    (WRITER_INPUTS, frozenset({"PDF", "DOCX", "ODT", "RTF", "TXT", "HTML"})),
    (CALC_INPUTS, frozenset({"PDF", "XLSX", "CSV", "TXT", "HTML"})),
    (IMPRESS_INPUTS, frozenset({"PDF", "PPTX"})),
    (frozenset({"PDF"}), frozenset({"PDF", "HTML"})),
)
#: Office binaries and layout-heavy pairs prefer LibreOffice when present.
LAYOUT_FORMATS = frozenset(
    {"PDF", "DOCX", "DOC", "ODT", "RTF", "XLSX", "XLS", "PPTX", "PPT", "ODP"}
)
PASSTHROUGH_FORMATS = frozenset({"PDF", "DOCX", "XLSX", "PPTX"})


class DetectedKind(StrEnum):
    PDF = "pdf"
    ZIP_PACKAGE = "zip"
    OLE = "ole"
    RTF = "rtf"
    HTML = "html"
    TEXT = "text"
    UNKNOWN = "unknown"


def normalize_format(value: str) -> str:
    return value.strip().upper()


def format_from_path(path: Path | str) -> str | None:
    return SUFFIX_TO_FORMAT.get(Path(path).suffix.casefold())


def builtin_supports(source_format: str, dest_format: str) -> bool:
    source = normalize_format(source_format)
    dest = normalize_format(dest_format)
    if source == dest and source in PASSTHROUGH_FORMATS | BUILTIN_WRITERS:
        return source in BUILTIN_READERS or source in PASSTHROUGH_FORMATS
    return source in BUILTIN_READERS and dest in BUILTIN_WRITERS


def libreoffice_supports(source_format: str, dest_format: str) -> bool:
    source = normalize_format(source_format)
    dest = normalize_format(dest_format)
    return any(
        source in inputs and dest in outputs for inputs, outputs in LIBREOFFICE_EXPORTS
    )


def prefers_libreoffice(source_format: str, dest_format: str) -> bool:
    source = normalize_format(source_format)
    dest = normalize_format(dest_format)
    if source == dest:
        return False
    return source in LAYOUT_FORMATS or dest in {"PDF", "ODT", "RTF"}


def conversion_supported(
    source_format: str,
    dest_format: str,
    engine: str = "automatic",
    libreoffice_available: bool = False,
) -> bool:
    if engine == "builtin":
        return builtin_supports(source_format, dest_format)
    if engine == "libreoffice":
        return libreoffice_available and libreoffice_supports(
            source_format, dest_format
        )
    return builtin_supports(source_format, dest_format) or (
        libreoffice_available and libreoffice_supports(source_format, dest_format)
    )
