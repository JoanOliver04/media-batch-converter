"""Search and paginated tables shared by batch review and results."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from tkinter import StringVar, ttk
from typing import Generic, TypeVar

from i18n import t

PAGE_SIZE = 100
Row = TypeVar("Row")


def search_key(path: str) -> str:
    return path.replace("\\", "/").casefold()


class FileTable(ttk.Frame, Generic[Row]):
    def __init__(
        self,
        parent,
        columns: Sequence[tuple[str, str, int]],
        values: Callable[[Row], tuple[str, ...]],
    ) -> None:
        super().__init__(parent)
        self.values = values
        self.rows: Sequence[Row] = ()
        self.page = 0
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(
            self,
            columns=[name for name, _, _ in columns],
            show="headings",
            selectmode="browse",
            height=5,
            style="Results.Treeview",
        )
        for index, (name, label, width) in enumerate(columns):
            self.table.heading(name, text=label, anchor="w")
            self.table.column(
                name, width=width, minwidth=min(60, width), stretch=index == 0
            )
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self, command=self.table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.table.configure(yscrollcommand=scrollbar.set)

        paging = ttk.Frame(self)
        paging.grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)
        self.previous = ttk.Button(
            paging,
            text=t("summary.page.previous"),
            command=lambda: self.show_page(self.page - 1),
        )
        self.previous.pack(side="left")
        self.page_label = StringVar(self)
        ttk.Label(paging, textvariable=self.page_label, style="Muted.TLabel").pack(
            side="left", padx=8
        )
        self.next = ttk.Button(
            paging,
            text=t("summary.page.next"),
            command=lambda: self.show_page(self.page + 1),
        )
        self.next.pack(side="right")

    def set_rows(self, rows: Sequence[Row]) -> None:
        self.rows = rows
        self.show_page(0)

    def show_page(self, page: int) -> None:
        total = len(self.rows)
        self.page = max(0, min(page, (total - 1) // PAGE_SIZE))
        start = self.page * PAGE_SIZE
        end = min(total, start + PAGE_SIZE)
        self.table.delete(*self.table.get_children())
        for index in range(start, end):
            self.table.insert(
                "", "end", iid=str(index), values=self.values(self.rows[index])
            )
        if total:
            self.table.selection_set(str(start))
            self.table.focus(str(start))
        self.page_label.set(
            t("summary.page.range", first=start + 1, last=end, total=total)
            if total
            else t("summary.page.empty")
        )
        self.previous.configure(state="normal" if self.page else "disabled")
        self.next.configure(state="normal" if end < total else "disabled")

    def selected(self) -> Row | None:
        selection = self.table.selection()
        return self.rows[int(selection[0])] if selection else None
