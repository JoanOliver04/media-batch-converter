from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from audio_encoding import (
    build_audio_args,
    build_audio_command,
    encoder_available,
    parse_ffmpeg_time,
    validate_audio_settings,
)
from presets import AUDIO_PRESETS, AudioSettings
from png_a_webp import PanelAudio


EXPECTED = {
    "runtime_music": ("M4A", "aac", 48_000, 2, 192, "aac_low"),
    "runtime_ambience": ("M4A", "aac", 48_000, 2, 160, "aac_low"),
    "runtime_sound_effect": ("M4A", "aac", 48_000, 1, 128, "aac_low"),
    "master_wav": ("WAV", "pcm_s24le", 48_000, None, None, None),
    "voice_dialogue": ("M4A", "aac", 48_000, 1, 96, "aac_low"),
}


class AudioPresetModelTests(unittest.TestCase):
    def test_preset_mappings_and_stable_ids(self) -> None:
        self.assertEqual({preset.preset_id for preset in AUDIO_PRESETS}, set(EXPECTED))
        for preset in AUDIO_PRESETS:
            settings = preset.audio_settings
            self.assertIsNotNone(settings)
            self.assertEqual(
                (
                    preset.output_format,
                    settings.codec,
                    settings.sample_rate,
                    settings.channels,
                    settings.bitrate_kbps,
                    settings.profile,
                ),
                EXPECTED[preset.preset_id],
            )
            self.assertFalse(settings.normalize_loudness)

    def test_aac_lc_and_mono_arguments(self) -> None:
        settings = AUDIO_PRESETS[2].audio_settings
        args = build_audio_args("M4A", settings)
        self.assertEqual(
            args,
            [
                "-c:a",
                "aac",
                "-profile:a",
                "aac_low",
                "-ar",
                "48000",
                "-ac",
                "1",
                "-b:a",
                "128k",
            ],
        )

    def test_master_wav_uses_24_bit_and_preserves_channels(self) -> None:
        args = build_audio_args("WAV", AUDIO_PRESETS[3].audio_settings)
        self.assertEqual(args, ["-c:a", "pcm_s24le", "-ar", "48000"])
        self.assertNotIn("-ac", args)
        self.assertNotIn("-b:a", args)

    def test_stereo_and_paths_with_spaces_are_separate_arguments(self) -> None:
        settings = AUDIO_PRESETS[0].audio_settings
        command = build_audio_command(
            "ffmpeg",
            Path("carpeta ü/input file.wav"),
            Path("salida ü/output file.m4a"),
            settings,
            "M4A",
        )
        self.assertEqual(command[3], str(Path("carpeta ü/input file.wav")))
        self.assertEqual(command[-1], str(Path("salida ü/output file.m4a")))
        self.assertIn("2", command)

    def test_invalid_combinations_and_profile(self) -> None:
        with self.assertRaises(ValueError):
            validate_audio_settings("WAV", AUDIO_PRESETS[0].audio_settings)
        invalid = AudioSettings("aac", 48_000, 2, 192, "bitrate", "aac_he")
        with self.assertRaises(ValueError):
            build_audio_args("M4A", invalid)
        normalized = AudioSettings("aac", 48_000, 2, 192, "bitrate", "aac_low", True)
        with self.assertRaises(NotImplementedError):
            build_audio_args("M4A", normalized)

    def test_encoder_capability_and_missing_ffmpeg(self) -> None:
        completed = Mock(returncode=0, stdout=" A..... aac AAC encoder\n")
        with patch("audio_encoding.subprocess.run", return_value=completed):
            self.assertTrue(encoder_available("ffmpeg", "aac"))
        with patch("audio_encoding.subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(encoder_available("missing", "aac"))

    def test_progress_parser(self) -> None:
        self.assertEqual(parse_ffmpeg_time("frame=1 time=01:02:03.50 speed=1x"), 3723.5)
        self.assertIsNone(parse_ffmpeg_time("no timestamp"))


class ImmediateRoot:
    def after(self, _delay, callback, *args):
        callback(*args)


class DummyState:
    def set(self, _value):
        pass


class AudioBatchTests(unittest.TestCase):
    def test_batch_command_is_argument_list_and_output_is_committed(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            source = root / "audio ü.wav"
            source.write_bytes(b"source")
            panel = PanelAudio.__new__(PanelAudio)
            panel.raiz = ImmediateRoot()
            panel.estado = DummyState()
            panel.cancel_event = threading.Event()
            panel.notificar_avance = lambda *_args: None
            commands: list[list[str]] = []

            def execute(command: list[str]) -> None:
                commands.append(command)
                Path(command[-1]).write_bytes(b"converted")

            panel.ejecutar_ffmpeg = execute
            completion: dict[str, object] = {}
            panel.finalizar_resultados = lambda destination, results, errors, *args: (
                completion.update(results=results)
            )
            with (
                patch(
                    "png_a_webp.imageio_ffmpeg.get_ffmpeg_exe",
                    return_value="ffmpeg",
                ),
                patch("png_a_webp.encoder_available", return_value=True),
            ):
                panel.convertir_ffmpeg_lote(
                    root,
                    [source],
                    "M4A",
                    ".m4a",
                    build_audio_args("M4A", AUDIO_PRESETS[0].audio_settings),
                    [],
                    {},
                    True,
                    required_encoder="aac",
                )
            self.assertIsInstance(commands[0], list)
            self.assertEqual(commands[0][3], str(source))
            self.assertEqual(completion["results"][0].status.value, "converted")


if __name__ == "__main__":
    unittest.main()
