"""Validated document conversion settings, independent from the UI."""

from __future__ import annotations

from dataclasses import dataclass

from i18n import t

DOCUMENT_ENGINES = ("automatic", "builtin", "libreoffice")
DOCUMENT_PAGE_SIZES = ("a4", "letter")


@dataclass(frozen=True, slots=True)
class DocumentSettings:
    page_size: str = "a4"
    engine: str = "automatic"
    page_markers: bool = True


def validate_document_settings(settings: DocumentSettings) -> None:
    if settings.page_size not in DOCUMENT_PAGE_SIZES:
        raise ValueError(t("document.page_size_invalid"))
    if settings.engine not in DOCUMENT_ENGINES:
        raise ValueError(t("document.engine_invalid"))
