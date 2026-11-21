from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_STORED, ZipFile

from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from audio_encoding import build_audio_args, manual_audio_settings
from conversion_results import ResultStatus
from documents.conversion import ConversionOutcome
from documents.optimization import optimize_document
from output_policy import OutputAction
from presets import preset_by_id
from ui.audio_panel import AudioPanel
from ui.document_panel import DocumentPanel
from ui.image_panel import ImagePanel
from video_encoding import build_video_args


class ImmediateRoot:
    def after(self, _delay, callback, *args):
        callback(*args)


class SizeOptimizationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def _batch_panel(self, panel_type):
        panel = panel_type.__new__(panel_type)
        panel.root = ImmediateRoot()
        panel.status = type("Status", (), {"set": lambda *_args: None})()
        panel.cancel_event = threading.Event()
        panel.report_progress = lambda *_args: None
        results = []
        panel.finish_results = lambda _destination, files, *_args: results.extend(files)
        return panel, results

    def test_png_candidate_keeps_every_pixel_and_alpha(self) -> None:
        source = Image.new("RGBA", (512, 128))
        for x in range(source.width):
            color = (140, 20, 200, 100) if x % 2 else (5, 220, 140, 255)
            source.paste(color, (x, 0, x + 1, source.height))
        original = self.root / "original.png"
        source.save(original, optimize=True)
        encoded = self.root / "encoded.png"
        ImagePanel.__new__(ImagePanel).save_image(source, encoded, "PNG", 85)
        with Image.open(encoded) as reopened:
            self.assertEqual(reopened.convert("RGBA").tobytes(), source.tobytes())
            self.assertEqual(reopened.mode, "P")
        self.assertLess(encoded.stat().st_size, original.stat().st_size)

    def test_png_keeps_16_bit_grayscale_samples(self) -> None:
        source = Image.new("I;16", (4, 3))
        source.putpixel((1, 1), 38_391)
        encoded = self.root / "depth.png"
        ImagePanel.__new__(ImagePanel).save_image(source, encoded, "PNG", 85)
        with Image.open(encoded) as reopened:
            self.assertEqual(reopened.getpixel((1, 1)), 38_391)

    def test_larger_image_is_skipped_without_replacing_an_existing_output(self) -> None:
        source = self.root / "icon.png"
        Image.new("RGB", (256, 256), "red").save(source)
        destination = self.root / "convertidos_bmp"
        destination.mkdir()
        existing = destination / "icon.bmp"
        existing.write_bytes(b"previous export")
        panel, results = self._batch_panel(ImagePanel)
        panel.convert_batch(
            self.root,
            [source],
            "BMP",
            85,
            options={"only_smaller": True, "output_policy": "overwrite"},
        )
        result = results[0]
        self.assertIs(result.status, ResultStatus.SKIPPED)
        self.assertEqual(result.output_action, OutputAction.SKIP_NO_SAVINGS)
        self.assertIsNone(result.output_path)
        self.assertGreater(result.attempted_output_bytes, source.stat().st_size)
        self.assertEqual(list(destination.iterdir()), [existing])
        self.assertEqual(existing.read_bytes(), b"previous export")

    def test_guard_counts_document_companions_before_writing_any_file(self) -> None:
        source = self.root / "page.txt"
        source.write_text("Short source", encoding="utf-8")
        panel, results = self._batch_panel(DocumentPanel)

        def render(_source, output, *_args):
            output.write_bytes(b"short")
            output.with_name("picture.png").write_bytes(b"x" * 200)
            return ConversionOutcome("libreoffice", ())

        with patch("ui.document_panel.convert_document", side_effect=render):
            panel.convert_batch(
                self.root, [source], "HTML", 85, options={"only_smaller": True}
            )
        self.assertIs(results[0].status, ResultStatus.SKIPPED)
        self.assertEqual(results[0].attempted_output_bytes, 205)
        self.assertFalse((self.root / "convertidos_html").exists())

    def test_guard_checks_combined_animation_frame_size(self) -> None:
        source = self.root / "motion.gif"
        first = Image.new("RGB", (32, 32), "red")
        second = Image.new("RGB", (32, 32), "blue")
        first.save(source, save_all=True, append_images=[second], duration=[30, 60])
        panel, results = self._batch_panel(ImagePanel)
        panel.convert_batch(
            self.root,
            [source],
            "BMP",
            85,
            options={"only_smaller": True, "animation_mode": "extract_frames"},
        )
        result = results[0]
        self.assertIs(result.status, ResultStatus.SKIPPED)
        self.assertGreater(result.attempted_output_bytes, 6_000)
        self.assertFalse((self.root / "convertidos_bmp").exists())

    def test_guard_skips_staged_ffmpeg_output_without_publishing_it(self) -> None:
        source = self.root / "theme.wav"
        source.write_bytes(b"input")
        panel, results = self._batch_panel(AudioPanel)

        def encode(command, _progress):
            Path(command[-1]).write_bytes(b"larger result")

        with (
            patch.object(panel, "_resolve_encoder", return_value="ffmpeg"),
            patch.object(panel, "run_ffmpeg", side_effect=encode),
        ):
            panel.convert_batch(
                self.root, [source], "MP3", 85, options={"only_smaller": True}
            )
        self.assertIs(results[0].status, ResultStatus.SKIPPED)
        self.assertEqual(results[0].attempted_output_bytes, 13)
        self.assertFalse((self.root / "convertidos_mp3").exists())

    def test_pdf_repack_preserves_rendered_text_and_saves_space(self) -> None:
        output = self.root / "guide.pdf"
        writer = Canvas(str(output), pageCompression=0)
        for i in range(200):
            writer.drawString(40, 740 - (i % 35) * 18, f"Resource note {i}")
        writer.save()
        size = output.stat().st_size
        text = PdfReader(output).pages[0].extract_text()
        optimize_document(output, "PDF", threading.Event())
        self.assertLess(output.stat().st_size, size)
        self.assertEqual(PdfReader(output).pages[0].extract_text(), text)

    def test_office_package_repack_keeps_member_bytes_and_odt_mimetype(self) -> None:
        output = self.root / "guide.odt"
        mime = b"application/vnd.oasis.opendocument.text"
        content = (
            b"<content>"
            + b" ".join(str(value).encode() for value in range(1000))
            + b"</content>"
        )
        with ZipFile(output, "w", ZIP_STORED) as archive:
            archive.writestr("mimetype", mime)
            archive.writestr("content.xml", content)
        size = output.stat().st_size
        optimize_document(output, "ODT", threading.Event())
        self.assertLess(output.stat().st_size, size)
        with ZipFile(output) as archive:
            self.assertEqual(archive.namelist(), ["mimetype", "content.xml"])
            self.assertEqual(archive.getinfo("mimetype").compress_type, ZIP_STORED)
            self.assertEqual(archive.read("content.xml"), content)

    def test_audio_and_video_settings_preserve_requested_constraints(self) -> None:
        mp3 = build_audio_args(
            "MP3", manual_audio_settings("MP3", 82, None, None, None)
        )
        self.assertIn("-q:a", mp3)
        self.assertNotIn("-b:a", mp3)
        opus = build_audio_args("Opus", preset_by_id("game_music_opus").audio_settings)
        self.assertIn("112k", opus)
        self.assertNotIn("-ac", opus)
        hevc = build_video_args("MP4", preset_by_id("game_video_hevc").video_settings)
        self.assertIn("hvc1", hevc)
        self.assertFalse(any("fps=" in argument for argument in hevc))
