from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from tkinter import TclError, Tk, ttk
from unittest.mock import Mock, patch

from i18n import DEFAULT_LANGUAGE, Language, current_language, set_language
from presets import SettingsStore
from ui.app import ConverterApp


def find_notebook(widget):
    for child in widget.winfo_children():
        if isinstance(child, ttk.Notebook):
            return child
        found = find_notebook(child)
        if found is not None:
            return found
    return None


def tab_labels(notebook) -> list[str]:
    return [notebook.tab(tab, "text") for tab in notebook.tabs()]


class LanguageSelectorTests(unittest.TestCase):
    """La app se construye con un almacén temporal para no tocar la
    configuración real del usuario al ejecutar los tests."""

    def setUp(self) -> None:
        self.addCleanup(set_language, DEFAULT_LANGUAGE)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings_path = Path(self.temporary.name).resolve() / "settings.json"
        try:
            self.root = Tk()
            self.root.withdraw()
        except TclError as error:
            self.skipTest(f"Tk unavailable: {error}")
        self.addCleanup(self.root.destroy)

    def build(self) -> ConverterApp:
        store = SettingsStore(self.settings_path)
        with (
            patch("ui.app.SettingsStore", return_value=store),
            patch(
                "ui.app.resolve_ffmpeg",
                return_value=Mock(
                    path=Path("ffmpeg"), version="test", source="bundled"
                ),
            ),
        ):
            return ConverterApp(self.root)

    def select(self, app: ConverterApp, display: str) -> None:
        app.language_selector.set(display)
        app._language_selected()
        self.root.update()

    def test_starts_in_spanish_and_lists_both_languages(self) -> None:
        app = self.build()
        self.assertEqual(app.language_selector.get(), "Español")
        self.assertEqual(
            set(app.language_selector.cget("values")), {"Español", "English"}
        )
        self.assertIn(" Imágenes ", tab_labels(find_notebook(self.root)))

    def test_switching_to_english_rebuilds_the_tabs(self) -> None:
        app = self.build()
        self.select(app, "English")
        self.assertIs(current_language(), Language.ENGLISH)
        labels = tab_labels(find_notebook(self.root))
        self.assertIn(" Images ", labels)
        self.assertIn(" Diagnostics ", labels)
        self.assertNotIn(" Imágenes ", labels)

    def test_switching_back_to_spanish_restores_labels(self) -> None:
        app = self.build()
        self.select(app, "English")
        self.select(app, "Español")
        self.assertIs(current_language(), Language.SPANISH)
        self.assertIn(" Imágenes ", tab_labels(find_notebook(self.root)))

    def test_panel_contents_follow_the_language(self) -> None:
        app = self.build()
        self.select(app, "English")
        image_panel = app.panels[0]
        self.assertEqual(image_panel.file_button.cget("text"), "Select file")
        self.assertEqual(image_panel.convert_button.cget("text"), "Start conversion")

    def test_only_one_notebook_survives_a_rebuild(self) -> None:
        app = self.build()
        self.select(app, "English")
        notebooks = [
            child
            for child in app.container.winfo_children()
            if isinstance(child, ttk.Notebook)
        ]
        self.assertEqual(len(notebooks), 1)

    def test_choice_is_persisted_and_restored(self) -> None:
        app = self.build()
        self.select(app, "English")
        self.assertEqual(SettingsStore(self.settings_path).load_language(), "en")

        set_language(DEFAULT_LANGUAGE)
        restored = self.build()
        self.assertIs(current_language(), Language.ENGLISH)
        self.assertEqual(restored.language_selector.get(), "English")

    def test_language_cannot_change_during_a_conversion(self) -> None:
        app = self.build()
        app.panels[0].busy = True
        with patch("ui.app.messagebox.showinfo") as warned:
            self.select(app, "English")
        warned.assert_called_once()
        self.assertIs(current_language(), Language.SPANISH)
        self.assertEqual(app.language_selector.get(), "Español")

    def test_reselecting_the_active_language_is_a_no_op(self) -> None:
        app = self.build()
        before = find_notebook(self.root)
        self.select(app, "Español")
        self.assertIs(find_notebook(self.root), before)

    def test_unwritable_settings_do_not_block_the_switch(self) -> None:
        app = self.build()
        with patch.object(SettingsStore, "save_language", side_effect=OSError):
            self.select(app, "English")
        self.assertIs(current_language(), Language.ENGLISH)


if __name__ == "__main__":
    unittest.main()
