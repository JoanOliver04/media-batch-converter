"""Orchestrate one document conversion without touching the UI."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from documents.errors import DocumentError
from documents.formats import (
    PASSTHROUGH_FORMATS,
    builtin_supports,
    format_from_path,
    libreoffice_supports,
    normalize_format,
    prefers_libreoffice,
)
from documents.libreoffice import (
    LibreOfficeInfo,
    convert_with_libreoffice,
    resolve_libreoffice,
)
from documents.model import DocumentModel
from documents.security import inspect_source
from documents.settings import DocumentSettings, validate_document_settings
from i18n import t

logging.getLogger(__name__).addHandler(logging.NullHandler())


@dataclass(frozen=True, slots=True)
class ConversionOutcome:
    engine: str
    warnings: tuple[str, ...]
    page_count: int | None = None
    block_count: int = 0


def convert_document(
    source: Path,
    output: Path,
    output_format: str,
    settings: DocumentSettings | None = None,
    cancel_event: Event | None = None,
    office: LibreOfficeInfo | None = None,
) -> ConversionOutcome:
    settings = settings or DocumentSettings()
    validate_document_settings(settings)
    inspect_source(source)
    source_format = format_from_path(source)
    if source_format is None:
        raise DocumentError(t("document.unknown_extension"))
    dest_format = normalize_format(output_format)
    resolved_office = office if office is not None else resolve_libreoffice()
    engine = choose_engine(
        source_format, dest_format, settings, resolved_office is not None
    )
    _raise_if_cancelled(cancel_event)
    output.parent.mkdir(parents=True, exist_ok=True)

    fallback_warning: str | None = None
    if engine == "libreoffice":
        try:
            convert_with_libreoffice(
                source, output, dest_format, cancel_event, resolved_office
            )
            return ConversionOutcome("libreoffice", (), None, 0)
        except DocumentError:
            if settings.engine != "automatic" or not builtin_supports(
                source_format, dest_format
            ):
                raise
            logging.getLogger(__name__).warning(
                "libreoffice_fallback source=%s dest=%s", source, dest_format
            )
            fallback_warning = t("document.warning.libreoffice_fallback")

    if source_format == dest_format and source_format in PASSTHROUGH_FORMATS:
        if source_format == "PDF":
            from documents.pdfio import rewrite_pdf

            rewrite_pdf(source, output)
        else:
            shutil.copyfile(source, output)
        return ConversionOutcome(
            "builtin",
            (fallback_warning,) if fallback_warning else (),
            None,
            0,
        )

    model = read_document(source, source_format, settings)
    _raise_if_cancelled(cancel_event)
    write_document(model, output, dest_format, settings)
    warnings = model.warnings
    if fallback_warning:
        warnings = (fallback_warning, *warnings)
    return ConversionOutcome("builtin", warnings, model.page_count, len(model.blocks))


def read_document(
    source: Path, source_format: str, settings: DocumentSettings
) -> DocumentModel:
    from documents import office, pdfio, textio

    readers = {
        "PDF": lambda path: pdfio.read_pdf(path, settings),
        "DOCX": office.read_docx,
        "TXT": textio.read_txt,
        "MD": textio.read_markdown,
        "HTML": textio.read_html,
        "XLSX": office.read_xlsx,
        "CSV": office.read_csv,
        "PPTX": office.read_pptx,
    }
    reader = readers.get(normalize_format(source_format))
    if reader is None:
        raise DocumentError(t("document.reader_missing", format=source_format))
    return reader(source)


def write_document(
    model: DocumentModel, output: Path, dest_format: str, settings: DocumentSettings
) -> None:
    from documents import office, pdfio, textio

    dest = normalize_format(dest_format)
    if dest == "PDF":
        pdfio.write_pdf(model, output, settings)
        return
    writers = {
        "DOCX": office.write_docx,
        "TXT": textio.write_txt,
        "MD": textio.write_markdown,
        "HTML": textio.write_html,
        "XLSX": office.write_xlsx,
        "CSV": office.write_csv,
        "PPTX": office.write_pptx,
    }
    writer = writers.get(dest)
    if writer is None:
        raise DocumentError(t("document.writer_missing", format=dest))
    writer(model, output)


def choose_engine(
    source_format: str,
    dest_format: str,
    settings: DocumentSettings,
    libreoffice_available: bool,
) -> str:
    source = normalize_format(source_format)
    dest = normalize_format(dest_format)
    if settings.engine == "libreoffice":
        if not libreoffice_available:
            raise DocumentError(t("document.libreoffice_unavailable"))
        if not libreoffice_supports(source, dest):
            raise DocumentError(
                t("document.pair_unsupported", source=source, dest=dest)
            )
        return "libreoffice"
    if settings.engine == "builtin":
        if not builtin_supports(source, dest):
            raise DocumentError(
                t("document.pair_unsupported", source=source, dest=dest)
            )
        return "builtin"
    if (
        prefers_libreoffice(source, dest)
        and libreoffice_available
        and libreoffice_supports(source, dest)
    ):
        return "libreoffice"
    if builtin_supports(source, dest):
        return "builtin"
    if libreoffice_available and libreoffice_supports(source, dest):
        return "libreoffice"
    raise DocumentError(t("document.pair_unsupported", source=source, dest=dest))


def _raise_if_cancelled(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError(t("error.cancelled"))
