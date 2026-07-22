from __future__ import annotations

import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from presets import VIDEO_PRESETS
from png_a_webp import PanelVideo
from video_encoding import (
    build_video_args,
    build_video_command,
    build_video_filter,
    parse_duration,
    parse_progress_seconds,
    probe_media,
    validate_video_settings,
)


EXPECTED = {
    "in_app_720p": ("MP4", "libx264", "aac", 1280, 720, "preserve", 30, 23),
    "high_quality_1080p": ("MP4", "libx264", "aac", 1920, 1080, "preserve", 30, 21),
    "vertical_social": ("MP4", "libx264", "aac", 1080, 1920, "fit", 30, 22),
    "horizontal_trailer": ("MP4", "libx264", "aac", 1920, 1080, "preserve", 30, 20),
    "webm_vp9": ("WebM", "libvpx-vp9", "libopus", None, None, "preserve", None, 30),
}


class VideoEncodingTests(unittest.TestCase):
    def test_preset_mapping(self) -> None:
        self.assertEqual({preset.preset_id for preset in VIDEO_PRESETS}, set(EXPECTED))
        for preset in VIDEO_PRESETS:
            item = preset.video_settings
            self.assertEqual(
                (
                    preset.output_format,
                    item.video_codec,
                    item.audio_codec,
                    item.width,
                    item.height,
                    item.aspect_mode,
                    item.fps_cap,
                    item.crf,
                ),
                EXPECTED[preset.preset_id],
            )

    def test_scale_only_and_odd_dimension_correction(self) -> None:
        settings = VIDEO_PRESETS[0].video_settings
        value = build_video_filter(settings)
        self.assertIn("force_original_aspect_ratio=decrease", value)
        self.assertIn("force_divisible_by=2", value)
        original = replace(settings, width=None, height=None)
        self.assertEqual(
            build_video_filter(original),
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=fps='min(30,source_fps)'",
        )

    def test_letterbox_crop_and_stretch_filters(self) -> None:
        base = VIDEO_PRESETS[2].video_settings
        letterbox = build_video_filter(base)
        self.assertIn("pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black", letterbox)
        crop = build_video_filter(replace(base, aspect_mode="fill"))
        self.assertIn("force_original_aspect_ratio=increase", crop)
        self.assertIn("crop=1080:1920", crop)
        stretch = build_video_filter(replace(base, aspect_mode="stretch"))
        self.assertTrue(stretch.startswith("scale=1080:1920,"))
        self.assertNotIn("crop", stretch)

    def test_h264_audio_removal_and_faststart(self) -> None:
        settings = replace(VIDEO_PRESETS[0].video_settings, remove_audio=True)
        args = build_video_args("MP4", settings)
        self.assertIn("libx264", args)
        self.assertIn("yuv420p", args)
        self.assertIn("-an", args)
        self.assertNotIn("-c:a", args)
        self.assertEqual(args[-2:], ["-movflags", "+faststart"])

    def test_vp9_opus_and_unicode_command(self) -> None:
        settings = VIDEO_PRESETS[4].video_settings
        command = build_video_command(
            "ffmpeg",
            Path("vídeo ü/source file.mov"),
            Path("salida ü/output file.webm"),
            "WebM",
            settings,
        )
        self.assertIn("libvpx-vp9", command)
        self.assertIn("libopus", command)
        self.assertEqual(command[3], str(Path("vídeo ü/source file.mov")))
        self.assertEqual(command[-1], str(Path("salida ü/output file.webm")))

    def test_invalid_container_codec_and_dimensions(self) -> None:
        with self.assertRaises(ValueError):
            validate_video_settings("MP4", VIDEO_PRESETS[4].video_settings)
        with self.assertRaises(ValueError):
            validate_video_settings(
                "MP4", replace(VIDEO_PRESETS[0].video_settings, width=1280, height=None)
            )

    def test_progress_duration_and_video_without_audio_probe(self) -> None:
        self.assertEqual(parse_progress_seconds("out_time=00:01:02.500000"), 62.5)
        self.assertEqual(parse_progress_seconds("frame=1 time=00:00:03.25"), 3.25)
        self.assertEqual(parse_duration("Duration: 00:02:03.50, start: 0"), 123.5)
        completed = Mock(stderr="Duration: 00:00:05.00\nStream #0:0: Video: h264")
        with patch("video_encoding.subprocess.run", return_value=completed):
            self.assertEqual(probe_media("ffmpeg", Path("silent.mp4")), (5.0, False))

    def test_missing_ffmpeg(self) -> None:
        with patch("video_encoding.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                probe_media("missing", Path("input.mp4"))


class ImmediateRoot:
    def after(self, _delay, callback, *args):
        callback(*args)


class DummyState:
    def set(self, _value):
        pass


class DummyProgress:
    def configure(self, *_args, **_kwargs):
        pass


class VideoBatchTests(unittest.TestCase):
    def make_panel(self) -> PanelVideo:
        panel = PanelVideo.__new__(PanelVideo)
        panel.raiz = ImmediateRoot()
        panel.estado = DummyState()
        panel.progreso = DummyProgress()
        panel.cancel_event = threading.Event()
        panel.notificar_avance = lambda *_args: None
        panel.finalizar_resultados = lambda *_args: None
        return panel

    def test_crop_conversion_accepts_source_without_audio_stream(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            source = root / "silent vídeo.mp4"
            source.write_bytes(b"source")
            panel = self.make_panel()
            commands: list[list[str]] = []
            completion: dict[str, object] = {}

            def execute(command, callback):
                commands.append(command)
                callback(1.0)
                Path(command[-1]).write_bytes(b"converted")

            panel.ejecutar_ffmpeg = execute
            panel.finalizar_resultados = lambda destination, results, errors, *args: (
                completion.update(results=results)
            )
            settings = replace(
                VIDEO_PRESETS[2].video_settings,
                aspect_mode="fill",
                remove_audio=False,
            )
            with (
                patch(
                    "png_a_webp.resolve_ffmpeg", return_value=Mock(path=Path("ffmpeg"))
                ),
                patch("png_a_webp.encoder_available", return_value=True),
                patch("png_a_webp.probe_media", return_value=(1.0, False)),
            ):
                panel.convertir_ffmpeg_lote(
                    root,
                    [source],
                    "MP4",
                    ".mp4",
                    build_video_args("MP4", settings),
                    [],
                    {},
                    False,
                    required_encoder=("libx264", "aac"),
                )
            self.assertIn("crop=1080:1920", commands[0][commands[0].index("-vf") + 1])
            self.assertEqual(completion["results"][0].status.value, "converted")

    def test_cancellation_cleans_temporary_output(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            source = root / "video.mp4"
            source.write_bytes(b"source")
            panel = self.make_panel()

            def cancel(command, _callback):
                Path(command[-1]).write_bytes(b"partial")
                panel.cancel_event.set()
                raise RuntimeError("cancelled")

            panel.ejecutar_ffmpeg = cancel
            with (
                patch(
                    "png_a_webp.resolve_ffmpeg", return_value=Mock(path=Path("ffmpeg"))
                ),
                patch("png_a_webp.encoder_available", return_value=True),
                patch("png_a_webp.probe_media", return_value=(10.0, True)),
            ):
                panel.convertir_ffmpeg_lote(
                    root,
                    [source],
                    "MP4",
                    ".mp4",
                    build_video_args("MP4", VIDEO_PRESETS[0].video_settings),
                    [],
                    {},
                    False,
                    required_encoder=("libx264", "aac"),
                )
            output = root / "convertidos_mp4"
            self.assertFalse(any(output.rglob("*.tmp")))
            self.assertFalse((output / "video.mp4").exists())


if __name__ == "__main__":
    unittest.main()
