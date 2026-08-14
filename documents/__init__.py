"""Document conversion services.

Readers and writers talk through a shared intermediate model so a new
format is one module, not a new pair for every existing type. LibreOffice
is an optional high-fidelity path, the same way FFmpeg is optional for
audio and video.
"""

from __future__ import annotations

from documents.conversion import ConversionOutcome, convert_document
from documents.errors import DocumentError
from documents.formats import (
    DOCUMENT_EXTENSIONS,
    DOCUMENT_FORMATS,
    conversion_supported,
    format_from_path,
)
from documents.libreoffice import LibreOfficeInfo, resolve_libreoffice
from documents.settings import (
    DOCUMENT_ENGINES,
    DOCUMENT_PAGE_SIZES,
    DocumentSettings,
    validate_document_settings,
)

__all__ = [
    "DOCUMENT_ENGINES",
    "DOCUMENT_EXTENSIONS",
    "DOCUMENT_FORMATS",
    "DOCUMENT_PAGE_SIZES",
    "ConversionOutcome",
    "DocumentError",
    "DocumentSettings",
    "LibreOfficeInfo",
    "conversion_supported",
    "convert_document",
    "format_from_path",
    "resolve_libreoffice",
    "validate_document_settings",
]
