from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from tkinter import TclError, Tk

from PIL import Image

from presets import (
    CUSTOM_PRESET_ID,
    IMAGE_PRESETS,
    SettingsStore,
    normalized_preset_id,
    preset_by_id,
    preset_matches,
    public_preset_data,
)
from png_a_webp import PanelAudio, PanelImagen, PanelVideo
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

    def test_output_policy_round_trip_preserves_other_settings(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            path = Path(temporary) / "settings.json"
            store = SettingsStore(path)
            store.save_last_image_preset("thumbnail")
            store.save_output_policy("overwrite")
            self.assertEqual(store.load_output_policy(), "overwrite")
            self.assertEqual(store.load_last_image_preset(), "thumbnail")
            store.save_normalize_filenames(True)
            self.assertTrue(store.load_normalize_filenames())
            self.assertEqual(store.load_output_policy(), "overwrite")
            store.save_generate_report(True)
            store.save_report_absolute_paths(True)
            self.assertTrue(store.load_generate_report())
            self.assertTrue(store.load_report_absolute_paths())
            store.save_animation_mode("first_frame")
            self.assertEqual(store.load_animation_mode(), "first_frame")
            store.save_last_audio_preset("voice_dialogue")
            self.assertEqual(store.load_last_audio_preset(), "voice_dialogue")
            store.save_last_audio_preset("unknown")
            self.assertEqual(store.load_last_audio_preset(), CUSTOM_PRESET_ID)
            store.save_last_video_preset("webm_vp9")
            self.assertEqual(store.load_last_video_preset(), "webm_vp9")
            store.save_last_video_preset("unknown")
            self.assertEqual(store.load_last_video_preset(), CUSTOM_PRESET_ID)

            store.save_output_policy("invalid")
            self.assertEqual(store.load_output_policy(), "skip")


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

    def test_filename_normalization_is_optional_and_previews_single_file(self) -> None:
        source = Path(self.temporary.name) / "Árbol Final.png"
        source.write_bytes(b"preview only")
        self.panel.seleccion.set(str(source))
        self.panel.formato.set("WebP")
        self.assertFalse(self.panel.normalize_filenames.get())
        self.panel.normalize_filenames.set(True)
        self.panel.normalize_filenames_changed()
        self.assertEqual(
            self.panel.output_name_preview.get(), "Nombre de salida: arbol_final.webp"
        )
        self.assertTrue(self.panel.opciones_conversion()["normalize_filenames"])

    def test_audio_preview_uses_complete_extension(self) -> None:
        panel = PanelAudio(self.root, self.root)
        source = Path(self.temporary.name) / "Voice Final.wav"
        source.write_bytes(b"preview only")
        panel.seleccion.set(str(source))
        panel.formato.set("MP3")
        panel.normalize_filenames.set(True)
        panel.update_output_name_preview()
        self.assertEqual(
            panel.output_name_preview.get(), "Nombre de salida: voice_final.mp3"
        )

    def test_audio_preset_applies_and_manual_override_is_custom(self) -> None:
        panel = PanelAudio(self.root, self.root)
        panel.apply_audio_preset_id("runtime_sound_effect")
        self.assertEqual(panel.formato.get(), "M4A")
        self.assertEqual(panel.audio_sample_rate.get(), "48000")
        self.assertEqual(panel.audio_channels.get(), "Mono")
        self.assertEqual(panel.audio_bitrate.get(), "128")
        settings = panel.opciones_conversion()["audio_settings"]
        self.assertEqual((settings.codec, settings.channels), ("aac", 1))

        panel.audio_channels.set("Estéreo")
        self.assertEqual(panel.audio_preset_display.get(), "Personalizado")
        self.assertEqual(panel.current_audio_settings().channels, 2)

    def test_audio_master_preserves_channels_and_uses_24_bit_pcm(self) -> None:
        panel = PanelAudio(self.root, self.root)
        panel.apply_audio_preset_id("master_wav")
        settings = panel.current_audio_settings()
        self.assertEqual(panel.formato.get(), "WAV")
        self.assertEqual(settings.codec, "pcm_s24le")
        self.assertIsNone(settings.channels)
        self.assertIsNone(settings.bitrate_kbps)

    def test_video_preset_applies_and_manual_change_is_custom(self) -> None:
        panel = PanelVideo(self.root, self.root)
        panel.apply_video_preset_id("vertical_social")
        self.assertEqual(panel.formato.get(), "MP4")
        self.assertEqual(
            (panel.video_width.get(), panel.video_height.get()), ("1080", "1920")
        )
        self.assertEqual(panel.video_aspect.get(), "Ajustar con bandas")
        self.assertEqual(panel.video_codec.get(), "libx264")
        self.assertEqual(panel.video_audio_codec.get(), "aac")

        panel.video_aspect.set("Rellenar y recortar")
        self.assertEqual(panel.video_preset_display.get(), "Personalizado")
        self.assertEqual(panel.current_video_settings().aspect_mode, "fill")

    def test_video_stretch_warning_and_audio_removal_are_explicit(self) -> None:
        panel = PanelVideo(self.root, self.root)
        self.assertTrue(any("deformar" in label for label in panel.ASPECT_LABELS))
        panel.apply_video_preset_id("in_app_720p")
        panel.video_remove_audio.set(True)
        panel.video_settings_changed()
        self.assertTrue(panel.current_video_settings().remove_audio)

    def test_report_defaults_are_private_and_optional(self) -> None:
        self.assertFalse(self.panel.generate_report.get())
        self.assertEqual(self.panel.report_path_mode.get(), "Relativas")
        options = self.panel.opciones_conversion()
        self.assertFalse(options["generate_report"])
        self.assertFalse(options["report_absolute_paths"])

    def test_animation_controls_hide_for_static_and_show_for_animation(self) -> None:
        static = Path(self.temporary.name) / "static.png"
        animated = Path(self.temporary.name) / "animated.gif"
        Image.new("RGB", (2, 2), "red").save(static)
        first = Image.new("RGB", (2, 2), "red")
        second = Image.new("RGB", (2, 2), "blue")
        first.save(animated, save_all=True, append_images=[second], duration=50)

        self.panel.seleccion.set(str(static))
        self.panel.update_animation_controls()
        self.assertFalse(self.panel.animation_frame.winfo_manager())

        self.panel.seleccion.set(str(animated))
        self.panel.update_animation_controls()
        self.assertTrue(self.panel.animation_frame.winfo_manager())
        self.panel.formato.set("JPEG")
        self.panel.animation_mode.set("preserve")
        self.assertIsNotNone(self.panel.validar_inicio())

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

    def test_resize_change_uses_relevant_fields_and_marks_custom(self) -> None:
        self.panel.aplicar_preset_id("thumbnail")
        self.panel.selector_resize.set("Anchura máxima")
        self.panel.resize_mode_changed()
        self.assertTrue(self.panel.entry_width.winfo_manager())
        self.assertFalse(self.panel.entry_height.winfo_manager())
        self.assertEqual(self.panel.preset_display.get(), "Personalizado")
        self.panel.resize_width.set("invalid")
        self.assertIsNotNone(self.panel.validar_inicio())

    def test_preset_options_apply_to_any_conversion_scope(self) -> None:
        self.panel.aplicar_preset_id("high_quality_illustration")
        options = self.panel.opciones_conversion()
        self.assertEqual(options["webp_mode"], "lossy")
        self.assertEqual(options["resize_config"].mode.value, "original")


if __name__ == "__main__":
    unittest.main()
