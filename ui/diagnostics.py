"""Pestaña de diagnóstico del entorno."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tkinter import Text, Tk, filedialog, messagebox, ttk

from i18n import t
from presets import SettingsStore
from runtime_environment import (
    FFmpegInfo,
    render_diagnostics,
    resolve_ffmpeg,
    selected_ffmpeg,
)
from ui.theme import FONT_DATA, LINE, PANEL, SIGNAL, TEXT


class DiagnosticsPanel(ttk.Frame):
    def __init__(self, parent, root: Tk, on_ffmpeg: Callable[[bool], None]) -> None:
        super().__init__(parent, padding=24)
        self.root = root
        self.store = SettingsStore()
        self.on_ffmpeg = on_ffmpeg
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
        encoder_actions = ttk.Frame(self)
        encoder_actions.pack(anchor="e", pady=(6, 0))
        ttk.Button(
            encoder_actions,
            text=t("ui.diagnostics.choose_ffmpeg"),
            command=self.choose_ffmpeg,
        ).pack(side="left", padx=(0, 8))
        self.auto_button = ttk.Button(
            encoder_actions,
            text=t("ui.diagnostics.auto_ffmpeg"),
            command=lambda: self.save_encoder(None),
        )
        self.auto_button.pack(side="left")
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
        self.show_encoder(resolve_ffmpeg())

    def show_encoder(self, info: FFmpegInfo | None) -> None:
        self.auto_button.configure(
            state="normal" if self.store.load_ffmpeg_path() else "disabled"
        )
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", render_diagnostics(info))
        self.text.configure(state="disabled")
        self.on_ffmpeg(info is not None)

    def choose_ffmpeg(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self.root,
            title=t("ui.diagnostics.choose_ffmpeg"),
            filetypes=(("FFmpeg", "ffmpeg*.exe"),),
        )
        if not filename:
            return
        info = selected_ffmpeg(Path(filename))
        if info is None:
            messagebox.showerror(
                t("ui.diagnostics.choose_ffmpeg"),
                t("ui.diagnostics.invalid_ffmpeg"),
                parent=self.root,
            )
            return
        self.save_encoder(info)

    def save_encoder(self, info: FFmpegInfo | None) -> None:
        try:
            self.store.save_ffmpeg_path(str(info.path) if info else "")
        except OSError:
            messagebox.showerror(
                t("ui.diagnostics.heading"),
                t("ui.diagnostics.cannot_save"),
                parent=self.root,
            )
            return
        self.show_encoder(info or resolve_ffmpeg())

    def copy(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text.get("1.0", "end-1c"))
        self.root.update_idletasks()
