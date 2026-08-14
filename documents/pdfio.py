"""PDF extraction and generation through pypdf and reportlab."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from documents.errors import DocumentError
from documents.model import Block, BlockKind, DocumentModel
from documents.security import MAX_BLOCKS, MAX_PAGES
from documents.settings import DocumentSettings
from error_handling import ErrorCode
from i18n import t

PAGE_SIZES = {"a4": A4, "letter": LETTER}
MAX_TABLE_COLUMNS = 12


def read_pdf(path: Path, settings: DocumentSettings) -> DocumentModel:
    try:
        reader = PdfReader(str(path), strict=False)
    except Exception as error:
        raise DocumentError(t("document.corrupt_pdf"), ErrorCode.IO_ERROR) from error
    if reader.is_encrypted:
        raise DocumentError(t("document.encrypted"))
    pages = len(reader.pages)
    if pages > MAX_PAGES:
        raise DocumentError(t("document.too_many_pages", limit=MAX_PAGES))
    blocks: list[Block] = []
    for index, page in enumerate(reader.pages, 1):
        _ensure_block_budget(len(blocks))
        if settings.page_markers and pages > 1:
            blocks.append(
                Block(
                    BlockKind.HEADING,
                    t("document.page_heading", number=index),
                    level=2,
                )
            )
        try:
            extracted = page.extract_text() or ""
        except Exception:
            extracted = ""
            blocks.append(
                Block(BlockKind.PARAGRAPH, t("document.page_unreadable", number=index))
            )
            continue
        for chunk in _split_extracted(extracted):
            _ensure_block_budget(len(blocks))
            blocks.append(Block(BlockKind.PARAGRAPH, chunk))
        if index < pages:
            blocks.append(Block(BlockKind.PAGE_BREAK))
    warnings = ()
    if not any(
        block.text.strip() for block in blocks if block.kind is BlockKind.PARAGRAPH
    ):
        warnings = (t("document.warning.pdf_no_text"),)
    return DocumentModel(None, tuple(blocks), warnings, pages, "PDF")


def write_pdf(model: DocumentModel, path: Path, settings: DocumentSettings) -> None:
    regular, bold = register_pdf_fonts()
    page_size = PAGE_SIZES[settings.page_size]
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="DocBody",
            parent=styles["Normal"],
            fontName=regular,
            fontSize=11,
            leading=15,
            alignment=TA_LEFT,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="DocTitle",
            parent=styles["Heading1"],
            fontName=bold,
            fontSize=18,
            leading=22,
            spaceAfter=12,
        )
    )
    for level in range(1, 7):
        styles.add(
            ParagraphStyle(
                name=f"DocH{level}",
                parent=styles["Heading1"],
                fontName=bold,
                fontSize=max(12, 18 - level),
                leading=max(15, 22 - level),
                spaceBefore=10,
                spaceAfter=6,
            )
        )
    styles.add(
        ParagraphStyle(
            name="DocCode",
            parent=styles["Code"],
            fontName=regular,
            fontSize=9,
            leading=12,
        )
    )

    story: list = []
    if model.title:
        story.append(Paragraph(escape(model.title), styles["DocTitle"]))
        story.append(Spacer(1, 4 * mm))

    pending_items: list[ListItem] = []
    pending_ordered: bool | None = None

    def flush_list() -> None:
        nonlocal pending_items, pending_ordered
        if pending_items:
            story.append(
                ListFlowable(
                    pending_items,
                    bulletType="1" if pending_ordered else "bullet",
                    start="1",
                )
            )
            pending_items = []
            pending_ordered = None

    for block in model.blocks:
        if block.kind is BlockKind.LIST_ITEM:
            if pending_ordered is not None and pending_ordered != block.ordered:
                flush_list()
            pending_ordered = block.ordered
            pending_items.append(
                ListItem(Paragraph(escape(block.text), styles["DocBody"]))
            )
            continue
        flush_list()
        if block.kind is BlockKind.HEADING:
            level = min(max(block.level, 1), 6)
            story.append(Paragraph(escape(block.text), styles[f"DocH{level}"]))
        elif block.kind is BlockKind.PARAGRAPH:
            story.append(
                Paragraph(escape(block.text).replace("\n", "<br/>"), styles["DocBody"])
            )
        elif block.kind is BlockKind.CODE:
            story.append(Preformatted(block.text, styles["DocCode"]))
        elif block.kind is BlockKind.TABLE:
            table = _pdf_table(block.rows, styles["DocBody"], page_size[0] - 40 * mm)
            if table is not None:
                story.append(table)
                story.append(Spacer(1, 4 * mm))
        elif block.kind is BlockKind.PAGE_BREAK:
            story.append(PageBreak())
    flush_list()
    if not story:
        story.append(Paragraph(" ", styles["DocBody"]))

    document = SimpleDocTemplate(
        str(path),
        pagesize=page_size,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=model.title or "",
        author="",
    )
    document.build(story)


def rewrite_pdf(source: Path, output: Path) -> None:
    try:
        reader = PdfReader(str(source), strict=False)
    except Exception as error:
        raise DocumentError(t("document.corrupt_pdf"), ErrorCode.IO_ERROR) from error
    if reader.is_encrypted:
        raise DocumentError(t("document.encrypted"))
    writer = PdfWriter()
    writer.append(reader)
    with output.open("wb") as handle:
        writer.write(handle)


@lru_cache(maxsize=1)
def register_pdf_fonts() -> tuple[str, str]:
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    pairs = (
        ("segoeui.ttf", "segoeuib.ttf", "MBC-UI", "MBC-UI-Bold"),
        ("arial.ttf", "arialbd.ttf", "MBC-Arial", "MBC-Arial-Bold"),
        ("calibri.ttf", "calibrib.ttf", "MBC-Calibri", "MBC-Calibri-Bold"),
    )
    for regular_file, bold_file, regular_name, bold_name in pairs:
        regular_path = fonts_dir / regular_file
        bold_path = fonts_dir / bold_file
        if regular_path.is_file() and bold_path.is_file():
            try:
                pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
                pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
                return regular_name, bold_name
            except Exception:
                continue
    return "Helvetica", "Helvetica-Bold"


def _pdf_table(rows: tuple[tuple[str, ...], ...], style, width: float):
    if not rows:
        return None
    trimmed = tuple(row[:MAX_TABLE_COLUMNS] for row in rows)
    columns = max(len(row) for row in trimmed)
    normalized = [list(row) + [""] * (columns - len(row)) for row in trimmed]
    flow = [
        [Paragraph(escape(cell).replace("\n", "<br/>"), style) for cell in row]
        for row in normalized
    ]
    col_width = width / max(columns, 1)
    table = Table(flow, colWidths=[col_width] * columns, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#272E39")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#E6E9EF")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#333C49")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _split_extracted(text: str) -> list[str]:
    chunks = [part.strip() for part in text.replace("\r\n", "\n").split("\n\n")]
    return [chunk for chunk in chunks if chunk]


def _ensure_block_budget(count: int) -> None:
    if count >= MAX_BLOCKS:
        raise DocumentError(t("document.too_many_blocks", limit=MAX_BLOCKS))
