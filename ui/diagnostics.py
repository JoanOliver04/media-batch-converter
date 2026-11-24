"""Pestaña de diagnóstico del entorno."""

from __future__ import annotations

from tkinter import Text, Tk, ttk

from i18n import t
from runtime_environment import diagnostics_text
from ui.theme import FONT_DATA, LINE, PANEL, SIGNAL, TEXT


class DiagnosticsPanel(ttk.Frame):
    def __init__(self, parent, root: Tk) -> None:
        super().__init__(parent, padding=24)
        self.root = root
        ttk.Label(
            self, text=t("ui.diagnostics.heading"), font=("Segoe UI", 18, "bold")
        ).pack(anchor="w", pady=(0, 14))
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.text = Text(
            body,
            wrap="word",
            height=1,
            width=1,
            font=FONT_DATA,
            background=PANEL,
            foreground=TEXT,
            insertbackground=SIGNAL,
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            padx=14,
            pady=12,
        )
        self.text.configure(highlightbackground=LINE)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        scrollbar.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=scrollbar.set)
        actions = ttk.Frame(self)
        actions.pack(anchor="e", pady=(12, 0))
        ttk.Button(actions, text=t("ui.button.refresh"), command=self.refresh).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(
            actions, text=t("ui.button.copy_diagnostics"), command=self.copy
        ).pack(side="left")
        self.bind("<Map>", self._first_open)

    def _first_open(self, _event) -> None:
        self.unbind("<Map>")
        self.refresh()

    def refresh(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", diagnostics_text())
        self.text.configure(state="disabled")

    def copy(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text.get("1.0", "end-1c"))
        self.root.update_idletasks()
