"""Tkinter batch-summary window."""

from __future__ import annotations

from pathlib import Path
from tkinter import Toplevel
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from conversion_results import BatchSummary, ResultStatus, summary_text


DETAIL_LIMIT = 50


def show_summary(parent, summary: BatchSummary, output_root: Path) -> None:
    window = Toplevel(parent)
    window.title("Resumen de conversión")
    window.geometry("720x560")
    window.minsize(560, 420)
    window.transient(parent)

    frame = ttk.Frame(window, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Resumen de conversión", font=("Segoe UI", 16, "bold")).pack(
        anchor="w", pady=(0, 10)
    )
    text = ScrolledText(frame, wrap="word", height=22, font=("Consolas", 10))
    text.pack(fill="both", expand=True)

    body = summary_text(summary) + f"\nCarpeta de salida: {output_root}\n"
    details = [
        result
        for result in summary.results
        if result.status in {ResultStatus.FAILED, ResultStatus.SKIPPED}
    ]
    if details or summary.discovery_errors:
        body += "\nDetalles de fallos y omisiones:\n"
        for result in details[:DETAIL_LIMIT]:
            reason = result.error_message or result.status.value
            body += f"- {result.source_path}: {reason}\n"
        remaining = max(0, len(details) - DETAIL_LIMIT)
        if remaining:
            body += f"- …y {remaining} resultado(s) más.\n"
        for error in summary.discovery_errors[: max(0, DETAIL_LIMIT - len(details))]:
            body += f"- Descubrimiento: {error}\n"

    text.insert("1.0", body)
    text.configure(state="disabled")

    actions = ttk.Frame(frame)
    actions.pack(fill="x", pady=(12, 0))

    def copy_summary() -> None:
        parent.clipboard_clear()
        parent.clipboard_append(body)
        parent.update_idletasks()

    ttk.Button(actions, text="Copiar resumen", command=copy_summary).pack(side="left")
    ttk.Button(actions, text="Cerrar", command=window.destroy).pack(side="right")
