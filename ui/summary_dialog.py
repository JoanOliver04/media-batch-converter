"""Overview and per-file inspection for a finished batch."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from tkinter import StringVar, Toplevel, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from batch_processing import is_link
from conversion_results import (
    BatchSummary,
    FileResult,
    ResultStatus,
    format_bytes,
    summary_text,
)
from i18n import t
from image_validation import ImageWarning
from ui.theme import FONT_BODY, PANEL, SIGNAL, SURFACE, TEXT

PAGE_SIZE = 100
STATUS_KEYS = {
    ResultStatus.CONVERTED: "summary.converted",
    ResultStatus.SKIPPED: "summary.skipped",
    ResultStatus.FAILED: "summary.failed",
}
FILE_STATUS_KEYS = {
    ResultStatus.CONVERTED: "summary.file.status.converted",
    ResultStatus.SKIPPED: "summary.file.status.skipped",
    ResultStatus.FAILED: "summary.file.status.failed",
}


def warning_text(warning: ImageWarning | str) -> str:
    if isinstance(warning, ImageWarning):
        return f"[{warning.code.value}] {warning.message}"
    return warning


def file_details(result: FileResult) -> str:
    lines = [str(result.source_path), t(FILE_STATUS_KEYS[result.status])]
    if result.output_path is not None:
        lines.append(f"{t('summary.file_output')}: {result.output_path}")
    lines.append(f"{t('summary.original_size')}: {format_bytes(result.original_bytes)}")
    if result.status is ResultStatus.CONVERTED:
        lines.append(f"{t('summary.output_size')}: {format_bytes(result.output_bytes)}")
    if result.attempted_output_bytes is not None:
        lines.append(
            f"{t('summary.attempted_size')}: {format_bytes(result.attempted_output_bytes)}"
        )
    if result.error_message and not any(
        isinstance(warning, ImageWarning) and warning.message == result.error_message
        for warning in result.warnings
    ):
        lines.append(result.error_message)
    if result.name_collision:
        lines.append(t("summary.name_collision_note").strip())
    if result.sha256:
        lines.append(f"SHA-256: {result.sha256}")
    lines.extend(warning_text(warning) for warning in result.warnings)
    return "\n".join(lines)


def readout(parent, height: int) -> ScrolledText:
    widget = ScrolledText(
        parent,
        wrap="word",
        height=height,
        width=1,
        font=FONT_BODY,
        background=PANEL,
        foreground=TEXT,
        insertbackground=SIGNAL,
        relief="flat",
        borderwidth=0,
        padx=10,
        pady=8,
    )
    widget.vbar.configure(
        background=PANEL, troughcolor=SURFACE, activebackground=SIGNAL, borderwidth=0
    )
    return widget


def set_readout(widget: ScrolledText, value: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", value)
    widget.configure(state="disabled")


class FileResults(ttk.Frame):
    """Show one page of a filtered result list at a time."""

    def __init__(self, parent, summary: BatchSummary, source_root: Path | None) -> None:
        super().__init__(parent, padding=10)
        self.results = summary.results
        self.source_root = source_root
        self.page = 0
        self.matches = self.results
        self.filters = {t("summary.filter.all"): None}
        self.filters.update({t(label): status for status, label in STATUS_KEYS.items()})

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text=t("summary.filter.label")).pack(side="left", padx=(0, 8))
        self.filter = ttk.Combobox(
            bar, state="readonly", width=16, values=tuple(self.filters)
        )
        self.filter.current(0)
        self.filter.pack(side="left")
        self.filter.bind("<<ComboboxSelected>>", self.apply_filter)

        listing = ttk.Frame(self)
        listing.pack(fill="both", expand=True)
        self.table = ttk.Treeview(
            listing,
            columns=("source", "status"),
            show="headings",
            selectmode="browse",
            height=5,
            style="Results.Treeview",
        )
        self.table.heading("source", text=t("summary.file_source"), anchor="w")
        self.table.heading("status", text=t("summary.state"), anchor="w")
        self.table.column("source", width=330, minwidth=120)
        self.table.column("status", width=125, minwidth=105, stretch=False)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(listing, command=self.table.yview)
        scrollbar.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<<TreeviewSelect>>", self.show_details)

        paging = ttk.Frame(self)
        paging.pack(fill="x", pady=6)
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
        self.details = readout(self, 5)
        self.details.pack(fill="x")
        self.show_page(0)

    def apply_filter(self, _event=None) -> None:
        status = self.filters[self.filter.get()]
        self.matches = (
            self.results
            if status is None
            else tuple(item for item in self.results if item.status is status)
        )
        self.show_page(0)

    def show_page(self, page: int) -> None:
        self.page = page
        start = page * PAGE_SIZE
        self.table.delete(*self.table.get_children())
        for index, item in enumerate(self.matches[start : start + PAGE_SIZE], start):
            path = item.source_path
            if self.source_root and path.is_relative_to(self.source_root):
                path = path.relative_to(self.source_root)
            self.table.insert(
                "",
                "end",
                iid=str(index),
                values=(str(path), t(FILE_STATUS_KEYS[item.status])),
            )
        if start < len(self.matches):
            self.table.selection_set(str(start))
            self.table.focus(str(start))
        self.show_details()
        end = min(len(self.matches), start + PAGE_SIZE)
        self.page_label.set(
            t("summary.page.range", first=start + 1, last=end, total=len(self.matches))
            if end
            else t("summary.page.empty")
        )
        self.previous.configure(state="normal" if page else "disabled")
        self.next.configure(state="normal" if end < len(self.matches) else "disabled")

    def show_details(self, _event=None) -> None:
        selection = self.table.selection()
        body = (
            file_details(self.matches[int(selection[0])])
            if selection
            else t("summary.page.empty")
        )
        set_readout(self.details, body)


def show_summary(
    parent,
    summary: BatchSummary,
    output_root: Path,
    report_file: Path | None = None,
    *,
    source_root: Path | None = None,
    retry: Callable[[], bool] | None = None,
) -> Toplevel:
    window = Toplevel(parent)
    window.title(t("summary.window_title"))
    window.geometry("840x620")
    window.minsize(580, 475)
    window.transient(parent)
    window.configure(background=SURFACE)
    window.bind("<Escape>", lambda _event: window.destroy())

    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=t("summary.window_title"), style="Title.TLabel").pack(
        anchor="w", pady=(0, 5)
    )
    ttk.Label(
        frame,
        text=t(
            "summary.batch_counts",
            converted=summary.converted,
            skipped=summary.skipped,
            failed=summary.failed,
        ),
    ).pack(anchor="w", pady=(0, 10))

    notebook = ttk.Notebook(frame)
    notebook.pack(fill="both", expand=True)
    notebook.enable_traversal()
    overview = ttk.Frame(notebook, padding=10)
    files = FileResults(notebook, summary, source_root)
    notebook.add(overview, text=t("summary.tab.overview"))
    notebook.add(files, text=t("summary.details_heading"))
    body = summary_text(summary) + f"\n{t('summary.output_folder')}: {output_root}\n"
    if report_file is not None:
        body += f"{t('summary.json_report')}: {report_file}\n"
    if summary.operation_warnings:
        body += f"\n{t('summary.operation_warnings_heading')}\n" + "\n".join(
            summary.operation_warnings
        )
    for error in summary.discovery_errors:
        body += f"\n{t('summary.discovery_prefix')}: {error}"
    content = readout(overview, 8)
    content.pack(fill="both", expand=True)
    set_readout(content, body)

    actions = ttk.Frame(frame)
    actions.pack(fill="x", pady=(10, 0))

    def copy_summary() -> None:
        noteworthy = (
            file_details(result)
            for result in summary.results
            if result.status is not ResultStatus.CONVERTED
            or result.warnings
            or result.name_collision
        )
        parent.clipboard_clear()
        parent.clipboard_append(
            "\n\n".join(part for part in (body, "\n\n".join(noteworthy)) if part)
        )

    def open_output_folder() -> None:
        try:
            if is_link(output_root) or not output_root.is_dir():
                raise OSError(output_root)
            os.startfile(output_root, "explore")
        except OSError:
            messagebox.showwarning(
                t("summary.window_title"),
                t("summary.folder_unavailable"),
                parent=window,
            )

    def retry_and_close() -> None:
        if retry is not None and retry() and window.winfo_exists():
            window.destroy()

    ttk.Button(actions, text=t("summary.copy_button"), command=copy_summary).pack(
        side="left"
    )
    if sys.platform == "win32" and output_root.is_dir():
        ttk.Button(
            actions, text=t("summary.open_folder"), command=open_output_folder
        ).pack(side="left", padx=(8, 0))
    ttk.Button(actions, text=t("summary.close_button"), command=window.destroy).pack(
        side="right"
    )
    if retry is not None:
        ttk.Button(
            actions,
            text=t("summary.retry_failed"),
            command=retry_and_close,
            style="Accent.TButton",
        ).pack(side="right", padx=(0, 8))
    if summary.discovery_errors or summary.operation_warnings:
        return window
    if any(item.status is ResultStatus.FAILED for item in summary.results):
        files.filter.set(t("summary.failed"))
        files.apply_filter()
        notebook.select(files)
    return window
