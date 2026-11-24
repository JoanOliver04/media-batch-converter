"""Ventana principal, selector de idioma y punto de entrada de la interfaz."""

from __future__ import annotations

import logging
from pathlib import Path
from tkinter import Tk, messagebox, ttk

from PIL import Image, ImageTk

from i18n import (
    available_languages,
    current_language,
    language_display_name,
    set_language,
    t,
)
from presets import SettingsStore
from runtime_environment import missing_document_dependencies, resolve_ffmpeg
from ui.audio_panel import AudioPanel
from ui.diagnostics import DiagnosticsPanel
from ui.document_panel import DocumentPanel
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
        icon_path = Path(__file__).resolve().parents[1] / "assets" / "app-icon.png"
        with Image.open(icon_path) as icon:
            window_icon = ImageTk.PhotoImage(icon, master=root)
            self.header_icon = ImageTk.PhotoImage(
                icon.resize((24, 24), Image.Resampling.LANCZOS), master=root
            )
        root.iconphoto(True, window_icon, self.header_icon)
        width = min(1160, root.winfo_screenwidth() - 40)
        height = min(850, root.winfo_screenheight() - 105)
        root.geometry(f"{width}x{height}")
        root.minsize(min(640, width), min(500, height))
        self.closing = False
        self.container = ttk.Frame(root)
        self.container.pack(fill="both", expand=True)
        self.panels: tuple = ()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()

    def _build(self) -> None:
        header = ttk.Frame(
            self.container, style="Surface.TFrame", padding=(20, 14, 20, 0)
        )
        header.pack(fill="x")
        ttk.Label(header, image=self.header_icon, style="Wordmark.TLabel").pack(
            side="left", padx=(0, 8)
        )
        ttk.Label(header, text=APP_NAME, style="Wordmark.TLabel").pack(side="left")

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
        self.notebook = notebook
        notebook.pack(fill="both", expand=True)
        notebook.enable_traversal()
        image_tab = ScrollableTab(notebook, ImagePanel, self.root)
        audio_tab = ScrollableTab(notebook, AudioPanel, self.root)
        video_tab = ScrollableTab(notebook, VideoPanel, self.root)
        document_tab = ScrollableTab(notebook, DocumentPanel, self.root)
        self.panels = (
            image_tab.panel,
            audio_tab.panel,
            video_tab.panel,
            document_tab.panel,
        )
        notebook.add(image_tab, text=t("ui.tab.images"))
        notebook.add(audio_tab, text=t("ui.tab.audio"))
        notebook.add(video_tab, text=t("ui.tab.video"))
        notebook.add(document_tab, text=t("ui.tab.files"))
        notebook.add(
            DiagnosticsPanel(notebook, self.root, self._set_media_available),
            text=t("ui.tab.diagnostics"),
        )
        self._set_media_available(resolve_ffmpeg() is not None)
        if missing_document_dependencies():
            document_tab.panel.status.set(t("ui.document.tabs_disabled"))
            notebook.tab(document_tab, state="disabled")

    def _set_media_available(self, available: bool) -> None:
        for index in (1, 2):
            panel = self.panels[index]
            # Keep running conversions accessible, including their Cancel button.
            if panel.busy:
                continue
            self.notebook.tab(index, state="normal" if available else "disabled")
            if not available:
                panel.status.set(t("ui.ffmpeg.tabs_disabled"))
            elif panel.status.get() == t("ui.ffmpeg.tabs_disabled"):
                panel.status.set(t("ui.status.select_prompt"))
                panel.restore_sources(panel.selection.get(), panel.selected_files)

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

    def _on_close(self) -> None:
        if self.closing:
            return
        if self.conversion_running():
            if not messagebox.askyesno(
                t("ui.dialog.close_busy_title"),
                t("ui.dialog.close_busy_body"),
            ):
                return
            self.closing = True
            self.language_selector.state(("disabled",))
            for panel in self.panels:
                panel.closing = True
                if getattr(panel, "busy", False):
                    panel.cancel()
            self._close_when_finished()
            return
        self.root.destroy()

    def _close_when_finished(self) -> None:
        if self.conversion_running():
            self.root.after(50, self._close_when_finished)
        else:
            self.root.destroy()

    def _rebuild(self) -> None:
        current_tab = self.notebook.index("current")
        selections = [
            (
                panel.selection.get(),
                panel.selected_files,
                panel.destination_parent,
                panel.recursive.get(),
                panel.finished_batch,
            )
            for panel in self.panels
        ]
        for panel in self.panels:
            panel.close_results()
        for child in self.container.winfo_children():
            child.destroy()
        self.panels = ()
        self._build()
        for panel, (selection, files, destination, recursive, finished_batch) in zip(
            self.panels, selections, strict=True
        ):
            panel.recursive.set(recursive)
            panel.set_destination(destination)
            panel.restore_sources(selection, files)
            panel.restore_finished_batch(finished_batch)
        if self.notebook.tab(current_tab, "state") == "normal":
            self.notebook.select(current_tab)


def main() -> None:
    root = Tk()
    ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
