"""Overview and per-file inspection for a finished batch."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from tkinter import StringVar, Toplevel, messagebox, ttk

from batch_processing import is_link
from conversion_results import (
    BatchSummary,
    FileResult,
    ResultStatus,
    format_bytes,
    format_duration,
    outcome_counts,
    summary_text,
)
from i18n import t
from image_validation import ImageWarning
from ui.file_list import FileTable, search_key
from ui.theme import SURFACE
from ui.widgets import readout, set_readout

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


def savings_text(result: FileResult) -> str:
    if result.status is not ResultStatus.CONVERTED:
        return "—"
    sign = "−" if result.bytes_saved < 0 else ""
    return sign + format_bytes(result.bytes_saved)


class FileResults(ttk.Frame):
    """Show one page of a filtered result list at a time."""

    def __init__(self, parent, summary: BatchSummary, source_root: Path | None) -> None:
        super().__init__(parent, padding=10)
        self.results = summary.results
        self.source_root = source_root
        self.paths = tuple(self.display_path(item) for item in self.results)
        self.search_paths = tuple(search_key(path) for path in self.paths)
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

        ttk.Label(bar, text=t("ui.label.search_path")).pack(side="left", padx=(14, 6))
        self.query = StringVar(self)
        self.search = ttk.Entry(bar, textvariable=self.query, width=14)
        self.search.pack(side="left", fill="x", expand=True)
        self.query.trace_add("write", self.apply_filter)
        self.listing = FileTable(
            self,
            (
                ("source", t("summary.file_source"), 330),
                ("status", t("summary.state"), 125),
                ("saved", t("summary.space_saved"), 120),
            ),
            lambda index: (
                self.paths[index],
                t(FILE_STATUS_KEYS[self.results[index].status]),
                savings_text(self.results[index]),
            ),
        )
        self.listing.pack(fill="both", expand=True)
        self.listing.table.bind("<<TreeviewSelect>>", self.show_details)
        self.details = readout(self, 5)
        self.details.pack(fill="x")
        self.apply_filter()

    def display_path(self, result: FileResult) -> str:
        path = result.source_path
        if self.source_root and path.is_relative_to(self.source_root):
            path = path.relative_to(self.source_root)
        return str(path)

    def apply_filter(self, *_args) -> None:
        status = self.filters[self.filter.get()]
        query = search_key(self.query.get().strip())
        rows = range(len(self.results))
        if status is not None or query:
            rows = [
                index
                for index in rows
                if (status is None or self.results[index].status is status)
                and query in self.search_paths[index]
            ]
        self.listing.set_rows(rows)
        self.show_details()

    def show_details(self, _event=None) -> None:
        index = self.listing.selected()
        body = (
            file_details(self.results[index])
            if index is not None
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

    def find_file(_event):
        notebook.select(files)
        files.search.focus_set()
        files.search.selection_range(0, "end")
        return "break"

    window.bind("<Control-f>", find_file)
    if summary.converted:
        saved = summary.bytes_saved
        label = t("summary.space_saved" if saved >= 0 else "summary.size_increase")
        metric = f"{label} · {format_bytes(abs(saved))}"
        percentage = summary.percentage_reduction
        if percentage is not None:
            metric += f" ({abs(percentage):.1f}%)"
        ttk.Label(
            overview,
            text=metric,
            style="Readout.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            overview,
            text=t(
                "summary.converted_sizes",
                before=format_bytes(summary.converted_original_bytes),
                after=format_bytes(summary.output_bytes),
            ),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 8))
    notes = [f"{t('summary.output_folder')}: {output_root}"]
    if report_file is not None:
        notes.append(f"{t('summary.json_report')}: {report_file}")
    if summary.operation_warnings:
        notes.extend(
            ("", t("summary.operation_warnings_heading"), *summary.operation_warnings)
        )
    notes.extend(
        f"{t('summary.discovery_prefix')}: {error}"
        for error in summary.discovery_errors
    )
    state = t(
        "summary.state.cancelled" if summary.cancelled else "summary.state.completed"
    )
    activity = t(
        "summary.activity",
        state=state,
        processed=summary.files_processed,
        total=summary.files_discovered,
        time=format_duration(summary.elapsed_seconds),
    )
    breakdown = [
        f"{t(key).lstrip(' -')}: {count}"
        for key, count in outcome_counts(summary)
        if count
    ]
    content = readout(overview, 8)
    content.pack(fill="both", expand=True)
    set_readout(content, "\n".join([activity, "", *breakdown, "", *notes]).strip())

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
        body = "\n".join([summary_text(summary), *notes])
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
