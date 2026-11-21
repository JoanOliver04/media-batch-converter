"""Lossless compression of staged document outputs, with a smaller-file check."""

from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from documents.security import MAX_PAGES, inspect_zip
from i18n import t

OFFICE_PACKAGES = {"DOCX", "XLSX", "PPTX", "ODT"}
MAX_PDF_REPACK_BYTES = 48 * 1024 * 1024
MAX_ZIP_REPACK_MEMBER_BYTES = 16 * 1024 * 1024


def optimize_document(path: Path, output_format: str, cancel: Event) -> None:
    if output_format not in OFFICE_PACKAGES and output_format != "PDF":
        return
    original_size = path.stat().st_size
    if output_format == "PDF" and original_size > MAX_PDF_REPACK_BYTES:
        return
    with TemporaryDirectory(prefix=".repack-", dir=path.parent) as work:
        candidate = Path(work) / path.name
        try:
            if output_format == "PDF":
                _compress_pdf(path, candidate, cancel)
            else:
                inspect_zip(path)
                _compress_package(path, candidate, cancel)
                if candidate.exists():
                    inspect_zip(candidate)
            _check_cancel(cancel)
            if candidate.is_file() and 0 < candidate.stat().st_size < original_size:
                candidate.replace(path)
        except InterruptedError:
            raise
        except Exception:
            logging.getLogger(__name__).info(
                "optional_document_repack_failed", exc_info=True
            )


def _check_cancel(cancel: Event) -> None:
    if cancel.is_set():
        raise InterruptedError(t("error.cancelled"))


def _compress_pdf(source: Path, output: Path, cancel: Event) -> None:
    from pypdf import PdfReader, PdfWriter

    with source.open("rb") as stream:
        reader = PdfReader(stream)
        if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
            return
        writer = PdfWriter(clone_from=reader)
        for page in writer.pages:
            _check_cancel(cancel)
            page.compress_content_streams(level=9)
        writer.compress_identical_objects(
            remove_duplicates=True, remove_unreferenced=False
        )
        with output.open("wb") as handle:
            writer.write(handle)


def _compress_package(source: Path, output: Path, cancel: Event) -> None:
    with ZipFile(source) as package:
        members = package.infolist()
        if any(member.file_size > MAX_ZIP_REPACK_MEMBER_BYTES for member in members):
            return
        with ZipFile(output, "w") as compressed:
            compressed.comment = package.comment
            for member in members:
                _check_cancel(cancel)
                payload = package.read(member)
                method = (
                    ZIP_STORED
                    if member.filename == "mimetype" or member.is_dir()
                    else ZIP_DEFLATED
                )
                compressed.writestr(
                    member, payload, compress_type=method, compresslevel=9
                )
