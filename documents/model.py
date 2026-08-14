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


@dataclass(frozen=True, slots=True)
class Block:
    kind: BlockKind
    text: str = ""
    level: int = 0
    rows: tuple[tuple[str, ...], ...] = ()
    ordered: bool = False


@dataclass(frozen=True, slots=True)
class DocumentModel:
    title: str | None
    blocks: tuple[Block, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    page_count: int | None = None
    source_format: str = ""

    def with_warning(self, warning: str) -> DocumentModel:
        return DocumentModel(
            self.title,
            self.blocks,
            (*self.warnings, warning),
            self.page_count,
            self.source_format,
        )
