from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import screenshot  # noqa: E402

from presets import (  # noqa: E402
    AUDIO_PRESETS,
    IMAGE_PRESETS,
    VIDEO_PRESETS,
    preset_by_id,
)
from ui.audio_panel import AudioPanel  # noqa: E402
from ui.image_panel import ImagePanel  # noqa: E402
from ui.video_panel import VideoPanel  # noqa: E402


class ToolContractTests(unittest.TestCase):
    """La herramienta usa la app por reflexión, así que un renombrado la
    rompería sin que nadie se entere hasta ir a regenerar las capturas."""

    PANELS = {0: ImagePanel, 1: AudioPanel, 2: VideoPanel}

    def test_preset_methods_exist_on_their_panels(self) -> None:
        for index, method in screenshot.PRESET_METHOD.items():
            with self.subTest(index=index):
                self.assertTrue(hasattr(self.PANELS[index], method), method)

    def test_readme_shots_use_known_tabs_and_presets(self) -> None:
        for tab, filename, preset_id in screenshot.README_SHOTS:
            with self.subTest(tab=tab):
                self.assertIn(tab, screenshot.TABS)
                self.assertTrue(filename.endswith(".png"))
                self.assertIsNotNone(
                    preset_by_id(preset_id), f"preset desconocido: {preset_id}"
                )

    def test_readme_shots_match_the_files_the_readme_references(self) -> None:
        readme = (screenshot.PROJECT / "README.md").read_text(encoding="utf-8")
        for _tab, filename, _preset in screenshot.README_SHOTS:
            with self.subTest(filename=filename):
                self.assertIn(f"docs/screenshots/{filename}", readme)

    def test_each_media_preset_belongs_to_its_own_tab(self) -> None:
        catalogues = {0: IMAGE_PRESETS, 1: AUDIO_PRESETS, 2: VIDEO_PRESETS}
        for tab, _filename, preset_id in screenshot.README_SHOTS:
            index = screenshot.TABS[tab]
            with self.subTest(tab=tab):
                self.assertIn(
                    preset_id, [preset.preset_id for preset in catalogues[index]]
                )


class IsolationTests(unittest.TestCase):
    def test_settings_directory_is_redirected_and_restored(self) -> None:
        before = os.environ.get("APPDATA")
        with screenshot.isolated_settings():
            redirected = os.environ["APPDATA"]
            self.assertNotEqual(redirected, before)
            self.assertTrue(Path(redirected).is_dir())
        self.assertEqual(os.environ.get("APPDATA"), before)

    def test_absent_variables_are_removed_again(self) -> None:
        previous = os.environ.pop("XDG_CONFIG_HOME", None)
        self.addCleanup(
            lambda: (
                os.environ.__setitem__("XDG_CONFIG_HOME", previous)
                if previous is not None
                else None
            )
        )
        with screenshot.isolated_settings():
            self.assertIn("XDG_CONFIG_HOME", os.environ)
        self.assertNotIn("XDG_CONFIG_HOME", os.environ)


class ArgumentTests(unittest.TestCase):
    def test_output_is_required_without_all(self) -> None:
        with self.assertRaises(SystemExit):
            screenshot.main(["--tab", "video"])

    def test_unknown_tab_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            screenshot.main(["--tab", "nope", "--output", "x.png"])


if __name__ == "__main__":
    unittest.main()
