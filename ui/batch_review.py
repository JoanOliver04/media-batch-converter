"""Read-only source inventory and optional selection before starting a batch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event, Thread
from tkinter import StringVar, Toplevel, ttk

from batch_processing import UnsafePathError, discover_files, is_link
from conversion_results import format_bytes
from error_handling import describe_error
from i18n import t
from ui.file_list import FileTable, search_key
from ui.widgets import readout, set_readout


@dataclass(frozen=True, slots=True)
class ReviewFile:
    source: Path
    relative: str
    size: int
    search_path: str


def inspect_sources(
    root: Path,
    files: tuple[Path, ...] | None,
    recursive: bool,
    extensions: set[str],
    cancelled: Event,
) -> tuple[list[ReviewFile], list[str]]:
    if is_link(root):
        raise UnsafePathError()
    errors: list[str] = []
    if files is None:
        discovery = discover_files(root, extensions, recursive, cancelled)
        sources = discovery.files
        errors = discovery.errors
    else:
        sources = files
    rows = []
    for path in sources:
        if cancelled.is_set():
            break
        try:
            relative = str(path.relative_to(root))
            if is_link(path) or not path.resolve().is_relative_to(root):
                raise UnsafePathError()
            rows.append(
                ReviewFile(path, relative, path.stat().st_size, search_key(relative))
            )
        except (ValueError, OSError) as error:
            errors.append(f"{path}: {describe_error(error).message}")
    return rows, errors


class BatchReview(Toplevel):
    def __init__(
        self,
        parent,
        *,
        root: Path,
        files: tuple[Path, ...] | None,
        recursive: bool,
        extensions: set[str],
        destination: Path,
        start: Callable[[tuple[Path, ...], tuple[str, ...]], None],
    ) -> None:
        super().__init__(parent)
        self.title(t("ui.review.title"))
        width = min(780, self.winfo_screenwidth() - 40)
        height = min(540, self.winfo_screenheight() - 100)
        self.geometry(f"{width}x{height}")
        self.minsize(min(540, width), min(380, height))
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.cancelled = Event()
        self.timer: str | None = None
        self.bind("<Destroy>", self._destroyed)
        self.start_batch = start
        self.rows: list[ReviewFile] = []
        self.errors: list[str] = []
        self.excluded: set[Path] = set()
        self.included_bytes = 0

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        self.status = StringVar(self, value=t("ui.status.discovering"))
        ttk.Label(
            frame,
            textvariable=self.status,
            style="Wordmark.TLabel",
            anchor="w",
            padding=8,
        ).pack(fill="x")
        destination_row = ttk.Frame(frame)
        destination_row.pack(fill="x", pady=(8, 0))
        ttk.Label(destination_row, text=t("summary.output_folder")).pack(
            side="left", padx=(0, 8)
        )
        self.destination = StringVar(self, value=str(destination))
        ttk.Entry(
            destination_row, state="readonly", textvariable=self.destination
        ).pack(side="left", fill="x", expand=True)

        search_row = ttk.Frame(frame)
        search_row.pack(fill="x", pady=8)
        ttk.Label(search_row, text=t("ui.label.search_path")).pack(
            side="left", padx=(0, 8)
        )
        self.query = StringVar(self)
        search = ttk.Entry(search_row, textvariable=self.query)
        search.pack(side="left", fill="x", expand=True)
        self.query.trace_add("write", self.filter_rows)
        self.listing = FileTable(
            frame,
            (
                ("source", t("summary.file_source"), 320),
                ("size", t("ui.review.size"), 90),
                ("include", t("ui.review.include_column"), 90),
            ),
            self.row_values,
        )
        self.listing.pack(fill="both", expand=True)
        self.listing.table.bind("<space>", self.toggle)
        self.listing.table.bind("<Double-Button-1>", self.double_click)
        self.listing.table.bind("<<TreeviewSelect>>", self.selection_changed)
        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        self.toggle_button = ttk.Button(
            controls, text=t("ui.review.exclude"), command=self.toggle, state="disabled"
        )
        self.toggle_button.pack(side="left")
        self.exclude_matches = ttk.Button(
            controls,
            text=t("ui.review.exclude_matches"),
            command=lambda: self.set_matches(False),
            state="disabled",
        )
        self.exclude_matches.pack(side="right")
        self.include_matches = ttk.Button(
            controls,
            text=t("ui.review.include_matches"),
            command=lambda: self.set_matches(True),
            state="disabled",
        )
        self.include_matches.pack(side="right", padx=6)
        self.notice = readout(frame, 2)
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(12, 0))
        self.convert = ttk.Button(
            actions,
            text=t("ui.review.convert"),
            style="Accent.TButton",
            command=self.confirm,
            state="disabled",
        )
        self.convert.pack(side="right")
        ttk.Button(actions, text=t("summary.close_button"), command=self.destroy).pack(
            side="right", padx=8
        )
        self.listing.set_rows(())
        self.grab_set()
        search.focus_set()

        result = SimpleQueue()
        cancel_event = self.cancelled

        def inspect() -> None:
            try:
                result.put(
                    inspect_sources(root, files, recursive, extensions, cancel_event)
                )
            except Exception as error:
                result.put(([], [describe_error(error).message]))

        def collect() -> None:
            try:
                self.rows, self.errors = result.get_nowait()
            except Empty:
                self.timer = self.after(50, collect)
                return
            self.timer = None
            self.included_bytes = sum(row.size for row in self.rows)
            if self.errors:
                set_readout(self.notice, "\n".join(self.errors))
                self.notice.pack(fill="x", before=actions, pady=(8, 0))
            self.filter_rows()

        Thread(target=inspect, daemon=True).start()
        self.timer = self.after(0, collect)

    def _destroyed(self, event) -> None:
        if event.widget is self:
            self.cancelled.set()
            if self.timer is not None:
                self.after_cancel(self.timer)

    def row_values(self, row: ReviewFile) -> tuple[str, ...]:
        included = row.source not in self.excluded
        return (
            row.relative,
            format_bytes(row.size),
            t("ui.review.yes" if included else "ui.review.no"),
        )

    def filter_rows(self, *_args) -> None:
        query = search_key(self.query.get().strip())
        matches = (
            [row for row in self.rows if query in row.search_path]
            if query
            else self.rows
        )
        self.listing.set_rows(matches)
        state = "normal" if matches else "disabled"
        self.include_matches.configure(state=state)
        self.exclude_matches.configure(state=state)
        self.selection_changed()
        if self.timer is None:
            self.update_count()

    def selection_changed(self, _event=None) -> None:
        row = self.listing.selected()
        include = row is not None and row.source in self.excluded
        self.toggle_button.configure(
            text=t("ui.review.include" if include else "ui.review.exclude"),
            state="normal" if row else "disabled",
        )

    def update_count(self) -> None:
        count = len(self.rows) - len(self.excluded)
        self.status.set(
            t(
                "ui.review.count",
                count=count,
                total=len(self.rows),
                size=format_bytes(self.included_bytes),
            )
        )
        self.convert.configure(state="normal" if count else "disabled")

    def set_included(self, row: ReviewFile, include: bool) -> None:
        if include and row.source in self.excluded:
            self.excluded.remove(row.source)
            self.included_bytes += row.size
        elif not include and row.source not in self.excluded:
            self.excluded.add(row.source)
            self.included_bytes -= row.size

    def toggle(self, _event=None) -> str:
        row = self.listing.selected()
        if row is not None:
            self.set_included(row, row.source in self.excluded)
            self.listing.table.item(
                self.listing.table.selection()[0], values=self.row_values(row)
            )
            self.selection_changed()
            self.update_count()
        return "break"

    def double_click(self, event) -> str:
        table = self.listing.table
        item = table.identify_row(event.y)
        if item and table.identify_region(event.x, event.y) in {"cell", "tree"}:
            table.selection_set(item)
            self.toggle()
        return "break"

    def set_matches(self, include: bool) -> None:
        for row in self.listing.rows:
            self.set_included(row, include)
        self.listing.show_page(self.listing.page)
        self.selection_changed()
        self.update_count()

    def confirm(self) -> None:
        chosen = tuple(
            row.source for row in self.rows if row.source not in self.excluded
        )
        if chosen:
            self.destroy()
            self.start_batch(chosen, tuple(self.errors))
