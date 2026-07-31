"""Ventana principal, selector de idioma y punto de entrada de la interfaz."""

from __future__ import annotations

import logging
from tkinter import Tk, messagebox, ttk

from i18n import (
    available_languages,
    current_language,
    language_display_name,
    set_language,
    t,
)
from presets import SettingsStore
from runtime_environment import resolve_ffmpeg
from ui.audio_panel import AudioPanel
from ui.diagnostics import DiagnosticsPanel
from ui.image_panel import ImagePanel
from ui.theme import apply_theme
from ui.video_panel import VideoPanel
from ui.widgets import ScrollableTab
from version import APP_NAME

logging.getLogger(__name__).addHandler(logging.NullHandler())


class ConverterApp:
    """Ventana principal.

    Cambiar de idioma reconstruye las pestañas: cada widget lee su texto al
    construirse, así que no hace falta un mecanismo aparte para re-traducir.
    """

    def __init__(self, root: Tk) -> None:
        self.root = root
        self.settings_store = SettingsStore()
        set_language(self.settings_store.load_language())
        apply_theme(root)
        root.title(APP_NAME)
        root.geometry("980x860")
        root.minsize(820, 720)
        self.container = ttk.Frame(root)
        self.container.pack(fill="both", expand=True)
        self.panels: tuple = ()
        self._build()

    def _build(self) -> None:
        header = ttk.Frame(
            self.container, style="Surface.TFrame", padding=(20, 14, 20, 0)
        )
        header.pack(fill="x")
        ttk.Label(header, text=APP_NAME.upper(), style="Wordmark.TLabel").pack(
            side="left"
        )
        ttk.Label(header, text=t("ui.header.tagline"), style="Tagline.TLabel").pack(
            side="left", padx=(12, 0)
        )

        self._language_by_display = {
            language_display_name(language): language
            for language in available_languages()
        }
        self.language_selector = ttk.Combobox(
            header,
            values=tuple(self._language_by_display),
            state="readonly",
            width=9,
        )
        self.language_selector.set(language_display_name(current_language()))
        # El combo se empaqueta antes que su etiqueta: con side="right" el
        # primero queda más a la derecha, así se lee "Idioma: [English]".
        self.language_selector.pack(side="right")
        ttk.Label(header, text=t("ui.label.language"), style="HeaderLabel.TLabel").pack(
            side="right", padx=(0, 8)
        )
        self.language_selector.bind("<<ComboboxSelected>>", self._language_selected)

        rule = ttk.Frame(self.container, style="Line.TFrame", height=1)
        rule.pack(fill="x", pady=(14, 0))

        notebook = ttk.Notebook(self.container)
        notebook.pack(fill="both", expand=True)
        image_tab = ScrollableTab(notebook, ImagePanel, self.root)
        audio_tab = ScrollableTab(notebook, AudioPanel, self.root)
        video_tab = ScrollableTab(notebook, VideoPanel, self.root)
        self.panels = (image_tab.panel, audio_tab.panel, video_tab.panel)
        notebook.add(image_tab, text=t("ui.tab.images"))
        notebook.add(audio_tab, text=t("ui.tab.audio"))
        notebook.add(video_tab, text=t("ui.tab.video"))
        notebook.add(
            DiagnosticsPanel(notebook, self.root), text=t("ui.tab.diagnostics")
        )
        if resolve_ffmpeg() is None:
            unavailable = t("ui.ffmpeg.tabs_disabled")
            audio_tab.panel.status.set(unavailable)
            video_tab.panel.status.set(unavailable)
            notebook.tab(audio_tab, state="disabled")
            notebook.tab(video_tab, state="disabled")

    def conversion_running(self) -> bool:
        return any(getattr(panel, "busy", False) for panel in self.panels)

    def _language_selected(self, _event=None) -> None:
        chosen = self._language_by_display.get(self.language_selector.get())
        if chosen is None or chosen is current_language():
            return
        if self.conversion_running():
            self.language_selector.set(language_display_name(current_language()))
            messagebox.showinfo(
                t("ui.dialog.language_busy_title"), t("ui.dialog.language_busy_body")
            )
            return
        set_language(chosen)
        try:
            self.settings_store.save_language(str(chosen))
        except OSError:
            logging.getLogger(__name__).warning("language_preference_not_saved")
        # Diferido: no se puede destruir el combo desde su propio callback.
        self.root.after(0, self._rebuild)

    def _rebuild(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()
        self.panels = ()
        self._build()


def main() -> None:
    root = Tk()
    ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
