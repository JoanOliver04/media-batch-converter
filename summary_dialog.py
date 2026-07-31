"""Tkinter batch-summary window."""

from __future__ import annotations

from pathlib import Path
from tkinter import Toplevel, ttk
from tkinter.scrolledtext import ScrolledText

from conversion_results import BatchSummary, ResultStatus, summary_text
from i18n import t
from ui.theme import FONT_DATA, PANEL, SIGNAL, SURFACE, TEXT

DETAIL_LIMIT = 50


def show_summary(
    parent,
    summary: BatchSummary,
    output_root: Path,
    report_file: Path | None = None,
) -> None:
    window = Toplevel(parent)
    window.title(t("summary.window_title"))
    window.geometry("720x560")
    window.minsize(560, 420)
    window.transient(parent)
    window.configure(background=SURFACE)

    frame = ttk.Frame(window, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=t("summary.window_title"), style="Title.TLabel").pack(
        anchor="w", pady=(0, 12)
    )
    text = ScrolledText(
        frame,
        wrap="word",
        height=22,
        font=FONT_DATA,
        background=PANEL,
        foreground=TEXT,
        insertbackground=SIGNAL,
        relief="flat",
        borderwidth=0,
        padx=14,
        pady=12,
    )
    text.pack(fill="both", expand=True)

    body = summary_text(summary) + f"\n{t('summary.output_folder')}: {output_root}\n"
    if report_file is not None:
        body += f"{t('summary.json_report')}: {report_file}\n"
    if summary.operation_warnings:
        body += f"\n{t('summary.operation_warnings_heading')}\n"
        body += (
            "\n".join(f"- {warning}" for warning in summary.operation_warnings) + "\n"
        )
    details = [
        result
        for result in summary.results
        if result.status in {ResultStatus.FAILED, ResultStatus.SKIPPED}
        or result.name_collision
        or result.warnings
    ]
    if details or summary.discovery_errors:
        body += f"\n{t('summary.details_heading')}\n"
        for result in details[:DETAIL_LIMIT]:
            reason = result.error_message or result.status.value
            if result.name_collision:
                reason += t("summary.name_collision_note")
            body += f"- {result.source_path}: {reason}\n"
            for warning in result.warnings:
                if hasattr(warning, "code"):
                    body += (
                        f"  [{warning.severity.value}] {warning.code.value}: "
                        f"{warning.message}\n"
                    )
                else:
                    body += f"  [warning] {warning}\n"
        remaining = max(0, len(details) - DETAIL_LIMIT)
        if remaining:
            body += t("summary.more_results", count=remaining) + "\n"
        for error in summary.discovery_errors[: max(0, DETAIL_LIMIT - len(details))]:
            body += f"- {t('summary.discovery_prefix')}: {error}\n"

    text.insert("1.0", body)
    text.configure(state="disabled")

    actions = ttk.Frame(frame)
    actions.pack(fill="x", pady=(12, 0))

    def copy_summary() -> None:
        parent.clipboard_clear()
        parent.clipboard_append(body)
        parent.update_idletasks()

    ttk.Button(actions, text=t("summary.copy_button"), command=copy_summary).pack(
        side="left"
    )
    ttk.Button(actions, text=t("summary.close_button"), command=window.destroy).pack(
        side="right"
    )
