from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Event
from unittest.mock import patch

from conversion_report import (
    SCHEMA_VERSION,
    HashCancelled,
    build_report,
    report_path,
    sha256_file,
    write_report_atomic,
)
from conversion_results import BatchSummary, FileResult, ResultStatus
from png_a_webp import PanelConversor


class TrackingStream(BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class ImmediateRoot:
    def after(self, _delay, callback, *args):
        callback(*args)


class ConversionReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temporary.name)
        self.output_root = self.root / "converted"
        self.output_root.mkdir()
        self.now = datetime(2026, 7, 22, 15, 45, 30, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_sha256_known_fixture_and_chunked_reads(self) -> None:
        path = self.root / "fixture.bin"
        payload = b"known fixture" * 100
        path.write_bytes(payload)
        stream = TrackingStream(payload)
        digest, warning = sha256_file(path, chunk_size=17, opener=lambda *_: stream)
        self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
        self.assertIsNone(warning)
        self.assertGreater(len(stream.read_sizes), 2)
        self.assertTrue(all(size == 17 for size in stream.read_sizes))

    def test_hashing_honors_cancellation(self) -> None:
        path = self.root / "fixture.bin"
        path.write_bytes(b"data")
        cancelled = Event()
        cancelled.set()
        with self.assertRaises(HashCancelled):
            sha256_file(path, cancelled)

    def test_single_success_relative_paths_and_schema(self) -> None:
        source = self.root / "carpeta á" / "imagen.png"
        output = self.output_root / "carpeta á" / "imagen.webp"
        source.parent.mkdir()
        output.parent.mkdir()
        source.write_bytes(b"source")
        output.write_bytes(b"output")
        result = FileResult(
            source,
            output,
            ResultStatus.CONVERTED,
            6,
            6,
            encoder_mode="lossy",
            warnings=("aviso válido",),
            width=20,
            height=30,
            output_width=10,
            output_height=15,
            quality=90,
            sha256=hashlib.sha256(b"output").hexdigest(),
        )
        report = build_report(
            BatchSummary(1, (result,), 1.25),
            self.root,
            self.output_root,
            "image",
            "WebP",
            {"quality": 90},
            self.now,
            self.now,
        )
        self.assertEqual(report["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(report["elapsedMilliseconds"], 1250)
        self.assertEqual(report["files"][0]["source"], "carpeta á/imagen.png")
        self.assertEqual(report["files"][0]["output"], "carpeta á/imagen.webp")
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized)
        self.assertIn("aviso válido", serialized)

    def test_mixed_batch_keeps_order_and_valid_errors(self) -> None:
        results = (
            FileResult(
                Path("b.png"), None, ResultStatus.FAILED, 2, error_message="bad"
            ),
            FileResult(Path("á.png"), None, ResultStatus.SKIPPED, 3),
        )
        report = build_report(
            BatchSummary(2, results, 0.1),
            self.root,
            self.output_root,
            "image",
            "png",
            {},
            self.now,
            self.now,
        )
        self.assertEqual(
            [item["status"] for item in report["files"]], ["failed", "skipped"]
        )
        self.assertEqual(report["files"][0]["error"], "bad")
        json.loads(json.dumps(report, ensure_ascii=False))

    def test_cancelled_summary_and_absolute_paths_are_explicit(self) -> None:
        source = self.root / "input.wav"
        result = FileResult(source, None, ResultStatus.SKIPPED, 1)
        report = build_report(
            BatchSummary(1, (result,), 0.2, cancelled=True),
            self.root,
            self.output_root,
            "audio",
            "mp3",
            {},
            self.now,
            self.now,
            absolute_paths=True,
        )
        self.assertTrue(report["summary"]["cancelled"])
        self.assertTrue(Path(report["files"][0]["source"]).is_absolute())

    def test_atomic_write_and_deterministic_non_overwrite_name(self) -> None:
        first = report_path(self.output_root, self.now)
        write_report_atomic(first, {"schemaVersion": 1, "files": []})
        second = report_path(self.output_root, self.now)
        self.assertEqual(second.name, "conversion_report_2026-07-22_154530.json")
        write_report_atomic(second, {"schemaVersion": 1, "files": []})
        self.assertEqual(
            report_path(self.output_root, self.now).name,
            "conversion_report_2026-07-22_154530_2.json",
        )
        self.assertEqual(
            json.loads(first.read_text(encoding="utf-8"))["schemaVersion"], 1
        )

    def test_report_name_checks_case_insensitively(self) -> None:
        self.output_root.joinpath("CONVERSION_REPORT.JSON").write_text("{}")
        self.assertEqual(
            report_path(self.output_root, self.now).name,
            "conversion_report_2026-07-22_154530.json",
        )

    def test_application_report_failure_preserves_successful_media(self) -> None:
        output = self.output_root / "done.webp"
        output.write_bytes(b"done")
        summary = BatchSummary(
            1,
            (
                FileResult(
                    self.root / "source.png",
                    output,
                    ResultStatus.CONVERTED,
                    10,
                    4,
                ),
            ),
            1,
        )
        panel = PanelConversor.__new__(PanelConversor)
        panel.raiz = ImmediateRoot()
        panel.report_source_root = self.root
        panel.report_output_format = "WebP"
        panel.report_settings = {}
        panel.batch_started_at = self.now
        panel.report_absolute = False
        captured: dict[str, object] = {}
        panel.mostrar_resultados = lambda destination, result, report: captured.update(
            destination=destination, summary=result, report=report
        )
        with patch(
            "png_a_webp.write_report_atomic", side_effect=PermissionError("locked")
        ):
            panel.generar_informe(self.output_root, summary)
        final = captured["summary"]
        self.assertEqual(final.converted, 1)
        self.assertEqual(len(final.operation_warnings), 1)
        self.assertIsNone(captured["report"])

    def test_report_write_failure_leaves_no_partial_json(self) -> None:
        target = self.output_root / "conversion_report.json"
        with patch("conversion_report.os.link", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                write_report_atomic(target, {"schemaVersion": 1})
        self.assertFalse(target.exists())
        self.assertEqual(list(self.output_root.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
