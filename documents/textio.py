"""Readers and writers for TXT, Markdown and HTML."""

from __future__ import annotations

import base64
import html
import re
from html.parser import HTMLParser
from pathlib import Path

from documents.errors import DocumentError
from documents.model import Block, BlockKind, DocumentModel
from documents.security import MAX_BLOCKS
from i18n import t

_ORDERED_ITEM = re.compile(r"^(\d+)[.)]\s+(.*)$")


def read_text_file(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentError(t("document.undecodable_text"))


def write_text_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def read_txt(path: Path) -> DocumentModel:
    text = read_text_file(path)
    blocks = _paragraphs_from_plain(text)
    return DocumentModel(None, tuple(blocks), source_format="TXT")


def write_txt(model: DocumentModel, path: Path) -> None:
    write_text_file(path, render_plain(model))


def read_markdown(path: Path) -> DocumentModel:
    return DocumentModel(
        None, tuple(parse_markdown(read_text_file(path))), source_format="MD"
    )


def write_markdown(model: DocumentModel, path: Path) -> None:
    write_text_file(path, render_markdown(model))


def read_html(path: Path) -> DocumentModel:
    parser = _DocumentHTMLParser()
    parser.feed(read_text_file(path))
    parser.close()
    title = parser.title.strip() or None
    return DocumentModel(title, tuple(parser.blocks), source_format="HTML")


def write_html(model: DocumentModel, path: Path) -> None:
    write_text_file(path, render_html(model))


def parse_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    paragraph: list[str] = []
    lines = text.splitlines()
    index = 0

    def flush() -> None:
        if paragraph:
            blocks.append(Block(BlockKind.PARAGRAPH, " ".join(paragraph).strip()))
            paragraph.clear()

    while index < len(lines):
        _ensure_block_budget(len(blocks) + len(paragraph))
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            index += 1
            code: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            blocks.append(Block(BlockKind.CODE, "\n".join(code)))
            index += 1
            continue
        if stripped.startswith("#"):
            flush()
            hashes = len(stripped) - len(stripped.lstrip("#"))
            blocks.append(
                Block(
                    BlockKind.HEADING,
                    stripped[hashes:].strip(),
                    level=min(max(hashes, 1), 6),
                )
            )
            index += 1
            continue
        if stripped.startswith("|") and "|" in stripped[1:]:
            flush()
            rows: list[tuple[str, ...]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = tuple(
                    cell.strip() for cell in lines[index].strip().strip("|").split("|")
                )
                if not all(cell and set(cell) <= set("-: ") for cell in cells):
                    rows.append(cells)
                index += 1
            if rows:
                blocks.append(Block(BlockKind.TABLE, rows=tuple(rows)))
            continue
        ordered = _ORDERED_ITEM.match(stripped)
        if stripped.startswith(("- ", "* ", "+ ")) or ordered:
            flush()
            item = ordered.group(2) if ordered else stripped[2:].strip()
            blocks.append(Block(BlockKind.LIST_ITEM, item, ordered=ordered is not None))
            index += 1
            continue
        if not stripped:
            flush()
            index += 1
            continue
        paragraph.append(stripped)
        index += 1
    flush()
    return blocks


def render_plain(model: DocumentModel) -> str:
    lines: list[str] = []
    if model.title:
        lines.extend((model.title, ""))
    for block in model.blocks:
        if block.kind is BlockKind.HEADING:
            lines.extend((block.text, ""))
        elif block.kind is BlockKind.PARAGRAPH:
            lines.extend((block.text, ""))
        elif block.kind is BlockKind.LIST_ITEM:
            marker = "1." if block.ordered else "-"
            lines.append(f"{marker} {block.text}")
        elif block.kind is BlockKind.CODE:
            lines.extend((block.text, ""))
        elif block.kind is BlockKind.TABLE:
            for row in block.rows:
                lines.append("\t".join(row))
            lines.append("")
        elif block.kind is BlockKind.IMAGE:
            lines.extend((t("document.image_placeholder"), ""))
        elif block.kind is BlockKind.PAGE_BREAK:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_markdown(model: DocumentModel) -> str:
    lines: list[str] = []
    if model.title:
        lines.extend((f"# {model.title}", ""))
    for block in model.blocks:
        if block.kind is BlockKind.HEADING:
            level = min(max(block.level, 1), 6)
            lines.extend((f"{'#' * level} {block.text}", ""))
        elif block.kind is BlockKind.PARAGRAPH:
            lines.extend((block.text, ""))
        elif block.kind is BlockKind.LIST_ITEM:
            marker = "1." if block.ordered else "-"
            lines.append(f"{marker} {block.text}")
        elif block.kind is BlockKind.CODE:
            lines.extend(("```", block.text, "```", ""))
        elif block.kind is BlockKind.TABLE:
            if not block.rows:
                continue
            width = max(len(row) for row in block.rows)
            normalized = [row + ("",) * (width - len(row)) for row in block.rows]
            lines.append("| " + " | ".join(normalized[0]) + " |")
            lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
            for row in normalized[1:]:
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")
        elif block.kind is BlockKind.IMAGE:
            lines.extend((t("document.image_placeholder"), ""))
        elif block.kind is BlockKind.PAGE_BREAK:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(model: DocumentModel) -> str:
    title = html.escape(model.title or "Document")
    parts = [
        "<!DOCTYPE html>",
        '<html lang="und">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{title}</title>",
        "</head>",
        "<body>",
    ]
    if model.title:
        parts.append(f"<h1>{html.escape(model.title)}</h1>")
    list_open: str | None = None

    def close_list() -> None:
        nonlocal list_open
        if list_open is not None:
            parts.append(f"</{list_open}>")
            list_open = None

    for block in model.blocks:
        if block.kind is BlockKind.LIST_ITEM:
            wanted = "ol" if block.ordered else "ul"
            if list_open != wanted:
                close_list()
                parts.append(f"<{wanted}>")
                list_open = wanted
            parts.append(f"<li>{html.escape(block.text)}</li>")
            continue
        close_list()
        if block.kind is BlockKind.HEADING:
            level = min(max(block.level, 1), 6)
            parts.append(f"<h{level}>{html.escape(block.text)}</h{level}>")
        elif block.kind is BlockKind.PARAGRAPH:
            parts.append(f"<p>{html.escape(block.text)}</p>")
        elif block.kind is BlockKind.CODE:
            parts.append(f"<pre><code>{html.escape(block.text)}</code></pre>")
        elif block.kind is BlockKind.TABLE:
            parts.append("<table>")
            for row in block.rows:
                cells = "".join(f"<td>{html.escape(cell)}</td>" for cell in row)
                parts.append(f"<tr>{cells}</tr>")
            parts.append("</table>")
        elif block.kind is BlockKind.IMAGE and block.image_bytes:
            mime = "image/png" if block.image_format == "PNG" else "image/jpeg"
            payload = base64.standard_b64encode(block.image_bytes).decode("ascii")
            parts.append(f'<p><img alt="" src="data:{mime};base64,{payload}"></p>')
        elif block.kind is BlockKind.PAGE_BREAK:
            parts.append('<hr class="page-break">')
    close_list()
    parts.extend(("</body>", "</html>", ""))
    return "\n".join(parts)


def _paragraphs_from_plain(text: str) -> list[Block]:
    blocks: list[Block] = []
    for chunk in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        stripped = chunk.strip()
        if stripped:
            _ensure_block_budget(len(blocks))
            blocks.append(Block(BlockKind.PARAGRAPH, stripped))
    return blocks


def _ensure_block_budget(count: int) -> None:
    if count >= MAX_BLOCKS:
        raise DocumentError(t("document.too_many_blocks", limit=MAX_BLOCKS))


class _DocumentHTMLParser(HTMLParser):
    SKIP = {"script", "style", "noscript"}
    HEADINGS = {f"h{index}" for index in range(1, 7)}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.title = ""
        self._skip = 0
        self._capture: list[str] = []
        self._in_title = False
        self._current_tag: str | None = None
        self._row: list[str] = []
        self._table: list[tuple[str, ...]] = []
        self._cell: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag in self.SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "br":
            self._capture.append("\n")
            return
        if tag == "tr":
            self._flush_inline()
            self._row = []
            return
        if tag in {"td", "th"}:
            self._flush_inline()
            self._cell = []
            self._current_tag = tag
            return
        if tag == "table":
            self._flush_inline()
            self._table = []
            return
        if tag in self.HEADINGS or tag in {"p", "li", "pre"}:
            self._flush_inline()
            self._current_tag = tag

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in {"td", "th"}:
            self._row.append("".join(self._cell).strip())
            self._cell = []
            self._current_tag = None
            return
        if tag == "tr":
            if self._row:
                self._table.append(tuple(self._row))
            self._row = []
            return
        if tag == "table":
            if self._table:
                self._append(Block(BlockKind.TABLE, rows=tuple(self._table)))
            self._table = []
            return
        if tag in self.HEADINGS or tag in {"p", "li", "pre"}:
            text = "".join(self._capture).strip()
            self._capture = []
            current = self._current_tag
            self._current_tag = None
            if not text:
                return
            if current in self.HEADINGS:
                self._append(Block(BlockKind.HEADING, text, level=int(current[1])))
            elif current == "li":
                self._append(Block(BlockKind.LIST_ITEM, text))
            elif current == "pre":
                self._append(Block(BlockKind.CODE, text))
            else:
                self._append(Block(BlockKind.PARAGRAPH, text))

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        if self._current_tag in {"td", "th"}:
            self._cell.append(data)
            return
        if self._current_tag is not None:
            self._capture.append(data)

    def _flush_inline(self) -> None:
        if self._current_tag in {"p", "li", "pre"} or (
            self._current_tag in self.HEADINGS if self._current_tag else False
        ):
            self.handle_endtag(self._current_tag or "p")

    def _append(self, block: Block) -> None:
        _ensure_block_budget(len(self.blocks))
        self.blocks.append(block)
