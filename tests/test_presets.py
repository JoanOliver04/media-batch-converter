from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from tkinter import TclError, Tk

from presets import (
    CUSTOM_PRESET_ID,
    IMAGE_PRESETS,
    SettingsStore,
    normalized_preset_id,
    preset_by_id,
    preset_matches,
    public_preset_data,
)
from png_a_webp import PanelImagen
from webp_encoding import WebPMode


EXPECTED_IDS = {
    "high_quality_illustration",
    "general_mobile_asset",
    "large_background",
    "transparent_ui_asset",
    "thumbnail",
    "lossless_archive",
}


class PresetModelTests(unittest.TestCase):
    def test_ids_are_stable_and_unique(self) -> None:
        self.assertEqual({preset.preset_id for preset in IMAGE_PRESETS}, EXPECTED_IDS)
        self.assertEqual(len(IMAGE_PRESETS), len(EXPECTED_IDS))

    def test_required_preset_values(self) -> None:
        expected = {
            "high_quality_illustration": ("WebP", 90, WebPMode.LOSSY),
            "general_mobile_asset": ("WebP", 88, WebPMode.AUTOMATIC),
            "large_background": ("WebP", 82, WebPMode.LOSSY),
            "transparent_ui_asset": ("WebP", None, WebPMode.LOSSLESS),
            "thumbnail": ("WebP", 78, WebPMode.LOSSY),
            "lossless_archive": ("PNG", None, None),
        }
        for preset_id, values in expected.items():
            preset = preset_by_id(preset_id)
            self.assertIsNotNone(preset)
            self.assertEqual(
                (preset.output_format, preset.quality, preset.webp_mode), values
            )
            self.assertEqual(preset.resize_mode, "original")

    def test_manual_changes_no_longer_match_preset(self) -> None:
        preset = preset_by_id("general_mobile_asset")
        self.assertTrue(preset_matches(preset, "WebP", 88, "automatic"))
        self.assertFalse(preset_matches(preset, "WebP", 70, "automatic"))
        self.assertFalse(preset_matches(preset, "PNG", 88, "automatic"))

    def test_public_data_contains_only_generic_values(self) -> None:
        serialized = json.dumps(public_preset_data(), ensure_ascii=False).casefold()
        for forbidden in ("joanoliver", "c:\\proyectos", "secret", "confidential"):
            self.assertNotIn(forbidden, serialized)


class SettingsTests(unittest.TestCase):
    def test_round_trip_and_unknown_preset_fallback(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            path = Path(temporary) / "settings.json"
            store = SettingsStore(path)
            store.save_last_image_preset("thumbnail")
            self.assertEqual(store.load_last_image_preset(), "thumbnail")
            path.write_text(
                '{"last_image_preset": "renamed_or_missing"}', encoding="utf-8"
            )
            self.assertEqual(store.load_last_image_preset(), CUSTOM_PRESET_ID)
        self.assertEqual(normalized_preset_id("unknown"), CUSTOM_PRESET_ID)


class PresetUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.previous_appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self.temporary.name
        try:
            self.root = Tk()
            self.root.withdraw()
        except TclError as error:
            self.temporary.cleanup()
            self.skipTest(f"Tk unavailable: {error}")
        self.panel = PanelImagen(self.root, self.root)

    def tearDown(self) -> None:
        if hasattr(self, "root"):
            self.root.destroy()
        if self.previous_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self.previous_appdata
        if hasattr(self, "temporary"):
            self.temporary.cleanup()

    def test_apply_modify_and_reapply_preset(self) -> None:
        self.panel.aplicar_preset_id("general_mobile_asset")
        self.assertEqual(self.panel.formato.get(), "WebP")
        self.assertEqual(self.panel.calidad.get(), 88)
        self.assertEqual(self.panel.webp_mode.get(), "automatic")

        self.panel.calidad.set(70)
        self.assertEqual(self.panel.preset_display.get(), "Personalizado")

        self.panel.aplicar_preset_id("general_mobile_asset")
        self.assertEqual(self.panel.calidad.get(), 88)
        self.assertEqual(self.panel.preset_display.get(), "Recurso móvil general")

    def test_unknown_preset_is_safe_custom_state(self) -> None:
        self.panel.aplicar_preset_id("missing")
        self.assertEqual(self.panel.preset_display.get(), "Personalizado")

    def test_preset_options_apply_to_any_conversion_scope(self) -> None:
        self.panel.aplicar_preset_id("high_quality_illustration")
        expected = {"webp_mode": "lossy"}
        self.assertEqual(self.panel.opciones_conversion(), expected)


if __name__ == "__main__":
    unittest.main()
