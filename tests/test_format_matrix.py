"""Round-trip tests with actual encoders and a fixture for each registered suffix."""

from __future__ import annotations

import math
import os
import re
import subprocess
import tempfile
import threading
import unittest
import wave
from array import array
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

from docx import Document
from openpyxl import Workbook
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.util import Inches
from reportlab.pdfgen.canvas import Canvas

from conversion_results import ResultStatus
from documents.conversion import choose_engine, read_document
from documents.formats import (
    BUILTIN_READERS,
    BUILTIN_WRITERS,
    DOCUMENT_FORMATS,
    SUFFIX_TO_FORMAT,
    format_from_path,
    libreoffice_supports,
)
from documents.libreoffice import resolve_libreoffice
from documents.settings import DocumentSettings
from process_control import creation_flags, text_kwargs
from runtime_environment import resolve_ffmpeg
from ui.audio_panel import AudioPanel
from ui.document_panel import DocumentPanel
from ui.formats import (
    AUDIO_EXTENSIONS,
    AUDIO_FORMATS,
    IMAGE_EXTENSIONS,
    IMAGE_FORMATS,
    VIDEO_EXTENSIONS,
    VIDEO_FORMATS,
)
from ui.image_panel import ImagePanel
from ui.video_panel import VideoPanel
from video_encoding import (
    CONTAINER_AUDIO_CODECS,
    CONTAINER_VIDEO_CODECS,
    VideoSettings,
    parse_duration,
)

IMAGE_SOURCES = {
    ".avif": "AVIF",
    ".bmp": "BMP",
    ".gif": "GIF",
    ".ico": "ICO",
    ".jpeg": "JPEG",
    ".jpg": "JPEG",
    ".png": "PNG",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".webp": "WEBP",
}
AUDIO_SOURCES = {
    ".aac": ("aac", "adts"),
    ".flac": ("flac", "flac"),
    ".m4a": ("aac", "ipod"),
    ".mp3": ("libmp3lame", "mp3"),
    ".oga": ("flac", "ogg"),
    ".ogg": ("libvorbis", "ogg"),
    ".opus": ("libopus", "opus"),
    ".wav": ("pcm_s16le", "wav"),
    ".wma": ("wmav2", "asf"),
}
VIDEO_SOURCES = {
    ".avi": ("mpeg4", "libmp3lame", "avi"),
    ".m4v": ("mpeg4", None, "m4v"),
    ".mkv": ("libx264", "aac", "matroska"),
    ".mov": ("libx264", "aac", "mov"),
    ".mp4": ("libx264", "aac", "mp4"),
    ".mpeg": ("mpeg2video", "mp2", "mpegts"),
    ".mpg": ("mpeg1video", "mp2", "mpeg"),
    ".webm": ("libvpx-vp9", "libopus", "webm"),
    ".wmv": ("wmv2", "wmav2", "asf"),
}
TEXT = "Asset manifest QA matrix"
SIZE = (64, 64)


class ImmediateRoot:
    def after(self, _delay, callback, *args):
        callback(*args)


def convert_batch(
    panel_type, root: Path, sources: list[Path], output: str, options=None
):
    panel = panel_type.__new__(panel_type)
    panel.root = ImmediateRoot()
    panel.status = Mock()
    panel.progress = Mock()
    panel.cancel_event = threading.Event()
    panel.report_progress = Mock()
    panel.finish_results = Mock()
    panel.fail = Mock()
    panel.convert_batch(root, sources, output, 85, options=options)
    panel.fail.assert_not_called()
    panel.finish_results.assert_called_once()
    return panel.finish_results.call_args.args[1]


class FormatMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def assert_batch(self, sources, results, suffix):
        self.assertEqual([result.source_path for result in results], sources)
        for result in results:
            with self.subTest(source=result.source_path.suffix, destination=suffix):
                self.assertIs(
                    result.status, ResultStatus.CONVERTED, result.error_message
                )
                self.assertEqual(result.output_path.suffix, suffix)
                self.assertEqual(result.output_bytes, result.output_path.stat().st_size)
        return [result for result in results if result.status is ResultStatus.CONVERTED]

    def test_every_image_suffix_to_every_image_output(self) -> None:
        self.assertEqual(set(IMAGE_SOURCES), IMAGE_EXTENSIONS)
        image = Image.new("RGB", SIZE, (32, 100, 212))
        ImageDraw.Draw(image).rectangle((12, 12, 40, 40), fill=(200, 72, 40))
        sources = []
        for suffix, format_name in IMAGE_SOURCES.items():
            path = self.root / f"imagen ñ {suffix[1:]}{suffix}"
            image.save(path, format=format_name)
            sources.append(path)
        for name, (format_name, suffix) in IMAGE_FORMATS.items():
            results = convert_batch(ImagePanel, self.root, sources, name)
            for result in self.assert_batch(sources, results, suffix):
                with self.subTest(source=result.source_path.suffix, destination=name):
                    with Image.open(result.output_path) as decoded:
                        decoded.load()
                        self.assertEqual(
                            (decoded.format, decoded.size), (format_name, SIZE)
                        )
                        if format_name in {"PNG", "TIFF", "BMP"}:
                            with Image.open(result.source_path) as original:
                                self.assertEqual(
                                    decoded.convert("RGB").tobytes(),
                                    original.convert("RGB").tobytes(),
                                )
                        if format_name == "ICO":
                            self.assertEqual(
                                decoded.ico.sizes(),
                                {(16, 16), (24, 24), (32, 32), (48, 48), SIZE},
                            )

    def test_every_audio_suffix_to_every_audio_output(self) -> None:
        self.assertEqual(set(AUDIO_SOURCES), AUDIO_EXTENSIONS)
        ffmpeg = self._ffmpeg()
        samples = array("h")
        for frame in range(24_000):
            samples.extend(
                (
                    round(14000 * math.sin(frame / 20)),
                    round(9000 * math.sin(frame / 13)),
                )
            )
        pcm = self.root / "mezcla ñ.wav"
        with wave.open(str(pcm), "wb") as stream:
            stream.setparams((2, 2, 48_000, 0, "NONE", ""))
            stream.writeframes(samples.tobytes())
        sources = []
        for suffix, (codec, muxer) in AUDIO_SOURCES.items():
            path = self.root / f"banda sonora ñ {suffix[1:]}{suffix}"
            self.run_ffmpeg(
                ffmpeg, "-i", str(pcm), "-c:a", codec, "-f", muxer, str(path)
            )
            sources.append(path)
        for name, suffix in AUDIO_FORMATS.items():
            results = convert_batch(AudioPanel, self.root, sources, name)
            for result in self.assert_batch(sources, results, suffix):
                with self.subTest(source=result.source_path.suffix, destination=name):
                    details = self.decode_media(ffmpeg, result.output_path)
                    self.assertIn("stereo", details)
                    self.assertNotIn("Video:", details)
                    self.assertAlmostEqual(parse_duration(details), 0.5, delta=0.17)
                    if result.source_path.suffix == ".wav":
                        decoded = subprocess.run(
                            [
                                ffmpeg,
                                "-v",
                                "error",
                                "-i",
                                str(result.output_path),
                                "-f",
                                "s16le",
                                "-",
                            ],
                            capture_output=True,
                            check=True,
                            timeout=20,
                            creationflags=creation_flags(),
                        )
                        if name in {"FLAC", "WAV"}:
                            self.assertEqual(decoded.stdout, samples.tobytes())
                        else:
                            output = array("h", decoded.stdout)
                            self.assertGreater(len(output), len(samples) * 0.9)
                            # Ignore encoder priming/tail padding and compare the
                            # sustained signal, not individual lossy-codec peaks.
                            centered = output[4_800:43_200]
                            for channel, amplitude in enumerate((14_000, 9_000)):
                                values = centered[channel::2]
                                rms = math.sqrt(
                                    sum(value * value for value in values) / len(values)
                                )
                                self.assertAlmostEqual(
                                    rms,
                                    amplitude / math.sqrt(2),
                                    delta=amplitude * 0.06,
                                )

    def test_every_video_suffix_to_every_video_output(self) -> None:
        self.assertEqual(set(VIDEO_SOURCES), VIDEO_EXTENSIONS)
        ffmpeg = self._ffmpeg()
        sources = []
        for suffix, (video, audio, muxer) in VIDEO_SOURCES.items():
            path = self.root / f"cinemática ñ {suffix[1:]}{suffix}"
            args = ["-f", "lavfi", "-i", "testsrc2=size=96x64:rate=25:duration=0.48"]
            if audio is not None:
                args.extend(
                    (
                        "-f",
                        "lavfi",
                        "-i",
                        "sine=frequency=440:duration=0.48",
                        "-c:a",
                        audio,
                        "-ar",
                        "48000",
                    )
                )
            args.extend(("-c:v", video, "-pix_fmt", "yuv420p", "-f", muxer, str(path)))
            self.run_ffmpeg(ffmpeg, *args)
            sources.append(path)
        for name, suffix in VIDEO_FORMATS.items():
            results = convert_batch(VideoPanel, self.root, sources, name)
            for result in self.assert_batch(sources, results, suffix):
                with self.subTest(source=result.source_path.suffix, destination=name):
                    details = self.decode_media(ffmpeg, result.output_path)
                    input_streams = details.partition("Stream mapping:")[0]
                    self.assertRegex(input_streams, r"Video: .*96x64")
                    self.assertEqual(self.frame_count(details), 12)
                    self.assertEqual(
                        "Audio:" in input_streams, result.source_path.suffix != ".m4v"
                    )
                    self.assertAlmostEqual(parse_duration(details), 0.48, delta=0.15)

        source = next(path for path in sources if path.suffix == ".mp4")
        codec_directory = self.root / "codec variants"
        settings = VideoSettings("libx264", "aac", None, None, "preserve", None, 25)
        for name, suffix in VIDEO_FORMATS.items():
            for video_codec in sorted(CONTAINER_VIDEO_CODECS[name.upper()]):
                for audio_codec in sorted(CONTAINER_AUDIO_CODECS[name.upper()]):
                    with self.subTest(
                        container=name, video_codec=video_codec, audio_codec=audio_codec
                    ):
                        variant = replace(
                            settings, video_codec=video_codec, audio_codec=audio_codec
                        )
                        output = codec_directory / f"{video_codec}-{audio_codec}"
                        result = convert_batch(
                            VideoPanel,
                            self.root,
                            [source],
                            name,
                            {
                                "destination_parent": output,
                                "video_settings": variant,
                            },
                        )[0]
                        self.assertIs(
                            result.status, ResultStatus.CONVERTED, result.error_message
                        )
                        self.assertEqual(result.output_path.suffix, suffix)
                        details = self.decode_media(
                            ffmpeg, result.output_path
                        ).partition("Stream mapping:")[0]
                        video_name = {
                            "libx264": "h264",
                            "libx265": "hevc",
                            "libvpx-vp9": "vp9",
                            "mpeg4": "mpeg4",
                        }[video_codec]
                        audio_name = {
                            "libopus": "opus",
                            "aac": "aac",
                            "libmp3lame": "mp3",
                        }[audio_codec]
                        self.assertIn(f"Video: {video_name}", details)
                        self.assertIn(f"Audio: {audio_name}", details)

    def test_every_builtin_document_pair_including_suffix_aliases(self) -> None:
        sources = write_document_fixtures(self.root)
        self.assertEqual(
            {SUFFIX_TO_FORMAT[path.suffix] for path in sources}, BUILTIN_READERS
        )
        self.assertEqual(
            {path.suffix for path in sources},
            {
                suffix
                for suffix, fmt in SUFFIX_TO_FORMAT.items()
                if fmt in BUILTIN_READERS
            },
        )
        settings = DocumentSettings(engine="builtin")
        for name in sorted(BUILTIN_WRITERS):
            results = convert_batch(
                DocumentPanel, self.root, sources, name, {"document_settings": settings}
            )
            for result in results:
                with self.subTest(source=result.source_path.suffix, destination=name):
                    self.assertIs(
                        result.status, ResultStatus.CONVERTED, result.error_message
                    )
                    self.assertEqual(result.output_path.suffix, DOCUMENT_FORMATS[name])
                    self.assertEqual(result.encoder_mode, "builtin")
                    assert_document_content(self, result.output_path, name, settings)

    def test_animation_preserves_frame_order_timing_and_loop(self) -> None:
        source = self.root / "animación ñ.png"
        first = Image.new("RGB", SIZE, "red")
        second = Image.new("RGB", SIZE, "blue")
        first.save(
            source, save_all=True, append_images=[second], duration=[90, 140], loop=2
        )
        for name in ("GIF", "PNG", "WebP"):
            with self.subTest(destination=name):
                result = convert_batch(ImagePanel, self.root, [source], name)[0]
                self.assertIs(
                    result.status, ResultStatus.CONVERTED, result.error_message
                )
                self.assertEqual(result.frame_durations_ms, (90, 140))
                with Image.open(result.output_path) as animation:
                    self.assertEqual(animation.n_frames, 2)
                    self.assertEqual(animation.info["loop"], 2)
                    animation.seek(0)
                    animation.load()
                    self.assertEqual(
                        animation.convert("RGB").getpixel((0, 0)), (255, 0, 0)
                    )
                    animation.seek(1)
                    animation.load()
                    self.assertEqual(
                        animation.convert("RGB").getpixel((0, 0)), (0, 0, 255)
                    )
                    if name != "WebP":
                        self.assertEqual(animation.info["duration"], 140)

    def test_image_formats_keep_alpha_or_apply_the_expected_matte(self) -> None:
        source = self.root / "alpha ñ.png"
        image = Image.new("RGBA", SIZE, (8, 24, 180, 0))
        ImageDraw.Draw(image).rectangle((22, 22, 42, 42), fill=(140, 60, 40, 128))
        image.save(source)
        for name in ("PNG", "TIFF", "WebP", "AVIF", "ICO (favicon)", "JPG"):
            with self.subTest(destination=name):
                result = convert_batch(ImagePanel, self.root, [source], name)[0]
                self.assertIs(
                    result.status, ResultStatus.CONVERTED, result.error_message
                )
                with Image.open(result.output_path) as decoded:
                    pixels = decoded.convert("RGBA")
                    if name == "JPG":
                        self.assertTrue(
                            all(channel >= 248 for channel in pixels.getpixel((0, 0)))
                        )
                    else:
                        alpha = pixels.getchannel("A")
                        self.assertEqual(alpha.getpixel((0, 0)), 0)
                        self.assertAlmostEqual(alpha.getpixel((32, 32)), 128, delta=3)

    def test_presentation_tables_fit_with_all_rows_on_multiple_slides(self) -> None:
        source = self.root / "cuadrícula ñ.csv"
        values = [(f"Asset {index}", str(index + 1)) for index in range(32)]
        source.write_text("\n".join(",".join(row) for row in values), encoding="utf-8")
        result = convert_batch(
            DocumentPanel,
            self.root,
            [source],
            "PPTX",
            {
                "document_settings": DocumentSettings(engine="builtin"),
            },
        )[0]
        self.assertIs(result.status, ResultStatus.CONVERTED, result.error_message)
        presentation = Presentation(result.output_path)
        self.assertGreater(len(presentation.slides), 1)
        recovered = []
        for slide in presentation.slides:
            for shape in slide.shapes:
                if shape.has_table:
                    self.assertLessEqual(
                        shape.top + shape.height, presentation.slide_height
                    )
                    recovered.extend(
                        tuple(cell.text for cell in row.cells)
                        for row in shape.table.rows
                    )
        self.assertEqual(recovered, values)

    def test_automatic_engine_uses_builtin_writer_for_cross_family_pairs(self) -> None:
        for source, output in (
            ("DOCX", "CSV"),
            ("XLSX", "PPTX"),
            ("PPTX", "HTML"),
            ("PDF", "DOCX"),
        ):
            with self.subTest(source=source, destination=output):
                self.assertFalse(libreoffice_supports(source, output))
                self.assertEqual(
                    choose_engine(source, output, DocumentSettings(), True), "builtin"
                )

    def test_size_limited_video_keeps_all_frames_or_preserves_previous_output(self):
        ffmpeg = self._ffmpeg()
        source = self.root / "clip.mkv"
        self.run_ffmpeg(
            ffmpeg,
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=640x360:r=24:d=2,noise=alls=65:allf=t+u",
            "-c:v",
            "ffv1",
            str(source),
        )
        folder = self.root / "convertidos_mp4"
        folder.mkdir()
        target = folder / "clip.mp4"
        target.write_bytes(b"previous output")
        settings = VideoSettings(
            "libx264",
            "aac",
            None,
            None,
            "preserve",
            None,
            12,
            remove_audio=True,
            max_size_mb=1,
        )
        options = {"video_settings": settings, "output_policy": "overwrite"}
        (failed,) = convert_batch(VideoPanel, self.root, [source], "MP4", options)
        self.assertIs(failed.status, ResultStatus.FAILED)
        self.assertEqual(target.read_bytes(), b"previous output")
        self.assertEqual(list(folder.iterdir()), [target])

        options["video_settings"] = replace(settings, width=96, height=64)
        (success,) = convert_batch(VideoPanel, self.root, [source], "MP4", options)
        self.assertIs(success.status, ResultStatus.CONVERTED, success.error_message)
        self.assertLessEqual(target.stat().st_size, settings.max_size_bytes)
        self.assertEqual(self.frame_count(self.decode_media(ffmpeg, target)), 48)

    def _ffmpeg(self) -> str:
        info = resolve_ffmpeg()
        if info is None:
            self.skipTest(
                "A working FFmpeg executable is required for the media matrix"
            )
        return str(info.path)

    def run_ffmpeg(self, ffmpeg: str, *args: str) -> str:
        completed = subprocess.run(
            [ffmpeg, "-nostdin", "-hide_banner", *args],
            capture_output=True,
            timeout=30,
            **text_kwargs(),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stderr

    def decode_media(self, ffmpeg: str, path: Path) -> str:
        return self.run_ffmpeg(
            ffmpeg,
            "-xerror",
            "-i",
            str(path),
            "-fps_mode",
            "passthrough",
            "-progress",
            "pipe:2",
            "-nostats",
            "-f",
            "null",
            "-",
        )

    @staticmethod
    def frame_count(details: str) -> int:
        frames = re.findall(r"^frame\s*=\s*(\d+)\s*$", details, re.MULTILINE)
        return int(frames[-1]) if frames else 0


def write_document_fixtures(directory: Path) -> list[Path]:
    base = directory / "documentación ñ"
    document = Document()
    document.add_paragraph(TEXT)
    docx = base.with_suffix(".docx")
    document.save(docx)
    workbook = Workbook()
    workbook.active.append([TEXT, 42])
    workbook.active.column_dimensions["A"].width = 38
    workbook.active.append(["café ñ", 16])
    xlsx = base.with_suffix(".xlsx")
    workbook.save(xlsx)
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1)).text = TEXT
    pptx = base.with_suffix(".pptx")
    presentation.save(pptx)
    pdf = base.with_suffix(".pdf")
    canvas = Canvas(str(pdf), pageCompression=0)
    canvas.drawString(36, 760, TEXT)
    canvas.save()
    result = [docx, xlsx, pptx, pdf]
    for extension, content in {
        ".txt": TEXT,
        ".md": f"# Notes\n\n{TEXT}",
        ".markdown": f"# Notes\n\n{TEXT}",
        ".html": f"<!DOCTYPE html><html><body><p>{TEXT}</p></body></html>",
        ".htm": f"<html><body><p>{TEXT}</p></body></html>",
        ".csv": f"{TEXT},42\n",
    }.items():
        # Alias fixtures need a different stem to exercise cases independently.
        path = base.with_name(f"{base.name} {extension[1:]}{extension}")
        path.write_text(content, encoding="utf-8")
        result.append(path)
    return result


def assert_document_content(
    test: unittest.TestCase, path: Path, output: str, settings: DocumentSettings
) -> None:
    document = read_document(path, output, settings)
    text = [document.title or "", *(block.text for block in document.blocks)]
    text.extend(cell for block in document.blocks for row in block.rows for cell in row)
    test.assertIn(TEXT, " ".join(" ".join(text).split()))


class NativeOfficeMatrixTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("MEDIA_BATCH_TEST_LIBREOFFICE_MATRIX") == "1",
        "Enable the extended LibreOffice matrix explicitly",
    )
    def test_every_libreoffice_pair(self) -> None:
        office = resolve_libreoffice()
        if office is None:
            self.skipTest("LibreOffice is required for the native document matrix")
        expected = {
            **dict.fromkeys(
                ("DOC", "DOCX", "ODT", "RTF", "TXT", "HTML"),
                {"PDF", "DOCX", "ODT", "RTF", "TXT", "HTML"},
            ),
            **dict.fromkeys(
                ("XLS", "XLSX", "CSV"), {"PDF", "XLSX", "CSV", "TXT", "HTML"}
            ),
            **dict.fromkeys(("PPT", "PPTX", "ODP"), {"PDF", "PPTX"}),
            "PDF": {"PDF", "HTML"},
        }
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            sources = {
                format_from_path(path): path for path in write_document_fixtures(root)
            }
            self._create_office_fixtures(office.path, root, sources)
            self.assertEqual(set(sources), set(SUFFIX_TO_FORMAT.values()))
            for source_format in sources:
                advertised = {
                    output
                    for output in DOCUMENT_FORMATS
                    if libreoffice_supports(source_format, output)
                }
                self.assertEqual(advertised, expected.get(source_format, set()))
            settings = DocumentSettings(engine="libreoffice")
            for output, suffix in DOCUMENT_FORMATS.items():
                inputs = [
                    sources[fmt]
                    for fmt, outputs in expected.items()
                    if output in outputs
                ]
                if not inputs:
                    continue
                results = convert_batch(
                    DocumentPanel, root, inputs, output, {"document_settings": settings}
                )
                for result in results:
                    with self.subTest(
                        source=result.source_path.suffix, destination=output
                    ):
                        self.assertIs(
                            result.status, ResultStatus.CONVERTED, result.error_message
                        )
                        self.assertEqual(result.output_path.suffix, suffix)
                        self.assertEqual(result.encoder_mode, "libreoffice")
                        if output == "RTF":
                            self.assertIn(
                                TEXT.encode(), result.output_path.read_bytes()
                            )
                        elif output == "ODT":
                            with ZipFile(result.output_path) as document:
                                self.assertIn(
                                    TEXT.encode(), document.read("content.xml")
                                )
                        else:
                            assert_document_content(
                                self, result.output_path, output, settings
                            )
                        if result.source_path.suffix == ".xlsx" and output in {
                            "TXT",
                            "CSV",
                        }:
                            self.assertIn(
                                "café ñ",
                                result.output_path.read_text(encoding="utf-8-sig"),
                            )

    def _create_office_fixtures(self, executable: Path, root: Path, sources) -> None:
        exe = (
            executable.with_suffix(".exe")
            if executable.suffix.lower() == ".com"
            else executable
        )
        (root / "legacy inputs").mkdir()
        for output, source in (
            ("doc", "DOCX"),
            ("odt", "DOCX"),
            ("rtf", "DOCX"),
            ("xls", "XLSX"),
            ("ppt", "PPTX"),
            ("odp", "PPTX"),
        ):
            directory = root / "legacy inputs"
            profile = (root / f"qa-profile-{output}").as_uri()
            completed = subprocess.run(
                [
                    str(exe),
                    f"-env:UserInstallation={profile}",
                    "--headless",
                    "--convert-to",
                    output,
                    "--outdir",
                    str(directory),
                    str(sources[source]),
                ],
                capture_output=True,
                timeout=25,
                **text_kwargs(),
            )
            path = directory / sources[source].with_suffix(f".{output}").name
            self.assertTrue(path.is_file(), f"{output}: {completed.stderr}")
            sources[output.upper()] = path
