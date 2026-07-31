from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from tkinter import TclError, Tk, ttk
from unittest.mock import Mock, patch

import runtime_environment
from runtime_environment import (
    FFMPEG_SOURCE_BUNDLED,
    FFMPEG_SOURCE_IMAGEIO,
    FFMPEG_SOURCE_SYSTEM,
    FFmpegInfo,
    diagnostics_text,
    missing_python_dependencies,
    resolve_ffmpeg,
    resource_path,
)
from ui.app import ConverterApp


def find_notebook(widget) -> ttk.Notebook:
    """Localiza el Notebook, que ahora cuelga del contenedor de ConverterApp."""
    for child in widget.winfo_children():
        if isinstance(child, ttk.Notebook):
            return child
        found = find_notebook(child)
        if found is not None:
            return found
    return None


class RuntimeEnvironmentTests(unittest.TestCase):
    def test_dependency_check_reports_distribution_names(self) -> None:
        real_import = runtime_environment.importlib.import_module

        def importing(name: str):
            if name == "imageio_ffmpeg":
                raise ImportError
            return real_import(name)

        with patch.object(
            runtime_environment.importlib, "import_module", side_effect=importing
        ):
            self.assertEqual(missing_python_dependencies(), ["imageio-ffmpeg"])

    def test_ffmpeg_resolution_prefers_bundled_then_provider_then_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            bundled = root / "ffmpeg" / "ffmpeg.exe"
            bundled.parent.mkdir()
            bundled.write_bytes(b"exe")
            with (
                patch("runtime_environment.application_directory", return_value=root),
                patch("runtime_environment.resource_path", return_value=bundled),
                patch("runtime_environment._ffmpeg_version", return_value="ffmpeg 1"),
            ):
                self.assertEqual(resolve_ffmpeg().source, FFMPEG_SOURCE_BUNDLED)

            bundled.unlink()
            provider_exe = root / "provider.exe"
            provider_exe.write_bytes(b"exe")
            provider = Mock(get_ffmpeg_exe=Mock(return_value=str(provider_exe)))
            with (
                patch("runtime_environment.application_directory", return_value=root),
                patch(
                    "runtime_environment.resource_path",
                    return_value=root / "missing.exe",
                ),
                patch.object(runtime_environment.shutil, "which", return_value=None),
                patch("runtime_environment._ffmpeg_version", return_value="ffmpeg 2"),
            ):
                with patch.object(
                    runtime_environment.importlib,
                    "import_module",
                    return_value=provider,
                ):
                    self.assertEqual(resolve_ffmpeg().source, FFMPEG_SOURCE_IMAGEIO)

            system = root / "system.exe"
            system.write_bytes(b"exe")
            with (
                patch("runtime_environment.application_directory", return_value=root),
                patch(
                    "runtime_environment.resource_path",
                    return_value=root / "missing.exe",
                ),
                patch.object(
                    runtime_environment.shutil, "which", return_value=str(system)
                ),
                patch("runtime_environment._ffmpeg_version", return_value="ffmpeg 3"),
            ):
                with patch.object(
                    runtime_environment.importlib,
                    "import_module",
                    side_effect=ImportError,
                ):
                    self.assertEqual(resolve_ffmpeg().source, FFMPEG_SOURCE_SYSTEM)

    def test_missing_ffmpeg_returns_none(self) -> None:
        with (
            patch("runtime_environment.Path.is_file", return_value=False),
            patch.object(
                runtime_environment.importlib, "import_module", side_effect=ImportError
            ),
            patch.object(runtime_environment.shutil, "which", return_value=None),
        ):
            self.assertIsNone(resolve_ffmpeg())

    def test_diagnostics_and_private_path(self) -> None:
        info = FFmpegInfo(
            Path.home() / "tools" / "ffmpeg.exe", FFMPEG_SOURCE_BUNDLED, "ffmpeg 7.1"
        )
        report = diagnostics_text(info)
        self.assertIn("Media Batch Converter 0.1.0", report)
        self.assertIn("Pillow:", report)
        self.assertIn("imageio-ffmpeg:", report)
        self.assertIn("ffmpeg 7.1", report)
        self.assertIn("Ruta FFmpeg: ~", report)
        self.assertNotIn(str(Path.home()), report)

    def test_packaged_resource_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            # resource_path no resuelve la ruta, así que ambos lados parten del
            # mismo valor: en Windows el temporal puede llegar en forma 8.3.
            bundle = str(Path(temporary).resolve())
            with patch.object(runtime_environment.sys, "_MEIPASS", bundle, create=True):
                self.assertEqual(resource_path("asset.txt"), Path(bundle) / "asset.txt")

    def test_source_has_no_automatic_pip_invocation(self) -> None:
        project = Path(__file__).resolve().parent.parent
        sources = [project / "run_app.py", *sorted((project / "ui").glob("*.py"))]
        self.assertGreater(len(sources), 1)
        combined = "".join(path.read_text(encoding="utf-8") for path in sources)
        self.assertNotIn("check_call", combined)
        self.assertNotIn('"pip", "install"', combined)


class AvailabilityUiTests(unittest.TestCase):
    def test_images_remain_enabled_when_ffmpeg_is_missing(self) -> None:
        try:
            root = Tk()
            root.withdraw()
        except TclError as error:
            self.skipTest(f"Tk unavailable: {error}")
        try:
            with patch("ui.app.resolve_ffmpeg", return_value=None):
                ConverterApp(root)
            notebook = find_notebook(root)
            tabs = notebook.tabs()
            self.assertEqual(notebook.tab(tabs[0], "state"), "normal")
            self.assertEqual(notebook.tab(tabs[1], "state"), "disabled")
            self.assertEqual(notebook.tab(tabs[2], "state"), "disabled")
            self.assertEqual(notebook.tab(tabs[3], "state"), "normal")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
