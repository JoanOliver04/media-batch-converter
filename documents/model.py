"""Intermediate document representation shared by every reader and writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    PAGE_BREAK = "page_break"
    CODE = "code"
    IMAGE = "image"


@dataclass(frozen=True, slots=True)
class Block:
    kind: BlockKind
    text: str = ""
    level: int = 0
    rows: tuple[tuple[str, ...], ...] = ()
    ordered: bool = False
    image_bytes: bytes = b""
    image_format: str = ""


@dataclass(frozen=True, slots=True)
class DocumentModel:
    title: str | None
    blocks: tuple[Block, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    page_count: int | None = None
    source_format: str = ""
    header: str | None = None
    footer: str | None = None

    def with_warning(self, warning: str) -> DocumentModel:
        return DocumentModel(
            title=self.title,
            blocks=self.blocks,
            warnings=(*self.warnings, warning),
            page_count=self.page_count,
            source_format=self.source_format,
            header=self.header,
            footer=self.footer,
        )
