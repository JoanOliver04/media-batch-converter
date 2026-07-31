from __future__ import annotations

import logging
import os
import tempfile
import unittest
from pathlib import Path
from tkinter import TclError, Tk, ttk
from unittest.mock import Mock, patch

from app_logging import configure_logging
from ui.app import ConverterApp, ScrollableTab
from video_encoding import ProgressLimiter


def find_notebook(widget) -> ttk.Notebook:
    """Localiza el Notebook, que ahora cuelga del contenedor de ConverterApp."""
    for child in widget.winfo_children():
        if isinstance(child, ttk.Notebook):
            return child
        found = find_notebook(child)
        if found is not None:
            return found
    return None


class PerformanceContractTests(unittest.TestCase):
    def test_progress_limiter_throttles_bursts_and_emits_completion(self) -> None:
        limiter = ProgressLimiter(interval_seconds=0.1)
        self.assertTrue(limiter.should_emit(1.0))
        self.assertFalse(limiter.should_emit(1.05))
        self.assertTrue(limiter.should_emit(1.10))
        self.assertTrue(limiter.should_emit(1.11, completed=True))

    def test_detailed_exceptions_are_written_to_rotating_local_log(self) -> None:
        root_logger = logging.getLogger()
        old_handlers = list(root_logger.handlers)
        for handler in old_handlers:
            root_logger.removeHandler(handler)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary).resolve() / "application.log"
                self.assertEqual(configure_logging(destination), destination)
                try:
                    raise PermissionError("destination locked")
                except PermissionError:
                    logging.getLogger("quality-test").exception("conversion failed")
                for handler in root_logger.handlers:
                    handler.flush()
                contents = destination.read_text(encoding="utf-8")
                self.assertIn("conversion failed", contents)
                self.assertIn("PermissionError", contents)
                for handler in list(root_logger.handlers):
                    handler.close()
                    root_logger.removeHandler(handler)
        finally:
            for handler in list(root_logger.handlers):
                handler.close()
                root_logger.removeHandler(handler)
            for handler in old_handlers:
                root_logger.addHandler(handler)


class IsolatedSettingsMixin:
    """Redirige la carpeta de configuración a un temporal.

    Construir un panel real persiste preset y política, así que sin esto los
    tests reescribirían los ajustes reales del usuario.
    """

    def setUp(self) -> None:
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        for variable in ("APPDATA", "XDG_CONFIG_HOME"):
            previous = os.environ.get(variable)
            os.environ[variable] = temporary.name
            self.addCleanup(self._restore_environment, variable, previous)

    @staticmethod
    def _restore_environment(variable: str, previous: str | None) -> None:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous


class HighDpiUiTests(IsolatedSettingsMixin, unittest.TestCase):
    def test_tabs_remain_bounded_and_scrollable_at_common_scales(self) -> None:
        for scale in (1.0, 1.25, 1.5, 2.0):
            try:
                root = Tk()
                root.withdraw()
            except TclError as error:
                self.skipTest(f"Tk unavailable: {error}")
            try:
                root.tk.call("tk", "scaling", scale)
                with patch(
                    "ui.app.resolve_ffmpeg",
                    return_value=Mock(
                        path=Path("ffmpeg"), version="test", source="test"
                    ),
                ):
                    ConverterApp(root)
                root.update_idletasks()
                self.assertLessEqual(root.winfo_reqwidth(), 900)
                self.assertLessEqual(root.winfo_reqheight(), 780)
                notebook = find_notebook(root)
                tabs = [notebook.nametowidget(tab) for tab in notebook.tabs()[:3]]
                self.assertTrue(all(isinstance(tab, ScrollableTab) for tab in tabs))
                self.assertTrue(
                    all(tab.canvas.cget("takefocus") == "1" for tab in tabs)
                )
            finally:
                root.destroy()

    def test_changing_tabs_preserves_independent_manual_state(self) -> None:
        try:
            root = Tk()
            root.withdraw()
        except TclError as error:
            self.skipTest(f"Tk unavailable: {error}")
        try:
            with patch(
                "ui.app.resolve_ffmpeg",
                return_value=Mock(path=Path("ffmpeg"), version="test", source="test"),
            ):
                ConverterApp(root)
            notebook = find_notebook(root)
            image_tab, audio_tab, video_tab = [
                notebook.nametowidget(tab) for tab in notebook.tabs()[:3]
            ]
            image_tab.panel.apply_preset_id("thumbnail")
            audio_tab.panel.apply_audio_preset_id("voice_dialogue")
            video_tab.panel.apply_video_preset_id("vertical_social")
            for tab in (audio_tab, video_tab, image_tab):
                notebook.select(tab)
                root.update_idletasks()
            self.assertEqual(image_tab.panel.quality.get(), 78)
            self.assertEqual(audio_tab.panel.audio_channels.get(), "Mono")
            self.assertEqual(video_tab.panel.video_aspect.get(), "Ajustar con bandas")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
