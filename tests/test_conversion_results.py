from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conversion_results import (
    BatchSummary,
    FileResult,
    ResultStatus,
    format_bytes,
    format_duration,
    summary_text,
)


def result(
    name: str,
    status: ResultStatus,
    original: int,
    output: int = 0,
    error: str | None = None,
) -> FileResult:
    return FileResult(
        Path(name),
        Path(name + ".out") if output else None,
        status,
        original,
        output,
        error,
    )


class FileResultTests(unittest.TestCase):
    def test_bytes_and_percentage(self) -> None:
        item = result("one", ResultStatus.CONVERTED, 1000, 250)
        self.assertEqual(item.bytes_saved, 750)
        self.assertEqual(item.percentage_change, 75.0)

    def test_zero_byte_percentage_is_safe(self) -> None:
        self.assertIsNone(result("zero", ResultStatus.FAILED, 0).percentage_change)


class BatchSummaryTests(unittest.TestCase):
    def test_successful_single_and_multi_file_totals(self) -> None:
        summary = BatchSummary(
            2,
            (
                result("a", ResultStatus.CONVERTED, 1000, 400),
                result("b", ResultStatus.CONVERTED, 500, 100),
            ),
            2.5,
        )
        self.assertEqual(summary.converted, 2)
        self.assertEqual(summary.original_bytes, 1500)
        self.assertEqual(summary.output_bytes, 500)
        self.assertAlmostEqual(summary.percentage_reduction, 66.666, places=2)

    def test_mixed_converted_skipped_failed(self) -> None:
        summary = BatchSummary(
            4,
            (
                result("ok", ResultStatus.CONVERTED, 100, 50),
                result("skip", ResultStatus.SKIPPED, 200),
                result("bad", ResultStatus.FAILED, 300, error="corrupt"),
            ),
            1,
            discovery_errors=("locked directory",),
        )
        self.assertEqual(
            (summary.converted, summary.skipped, summary.failed), (1, 1, 2)
        )
        self.assertEqual(summary.files_processed, 3)

    def test_failed_and_skipped_files_are_not_counted_as_savings(self) -> None:
        summary = BatchSummary(
            3,
            (
                result("ok", ResultStatus.CONVERTED, 100, 50),
                result("skip", ResultStatus.SKIPPED, 10_000),
                result("bad", ResultStatus.FAILED, 20_000, error="bad"),
            ),
            1,
        )
        self.assertEqual(summary.original_bytes, 30_100)
        self.assertEqual(summary.bytes_saved, 50)
        self.assertEqual(summary.percentage_reduction, 50.0)

    def test_output_larger_is_reported_as_increase(self) -> None:
        summary = BatchSummary(1, (result("a", ResultStatus.CONVERTED, 100, 150),), 1)
        text = summary_text(summary)
        self.assertIn("Aumento de tamaño: 50 B", text)
        self.assertIn("Incremento: 50.0%", text)

    def test_cancelled_partial_results(self) -> None:
        summary = BatchSummary(
            10, (result("a", ResultStatus.CONVERTED, 100, 50),), 0.25, cancelled=True
        )
        self.assertIn("Estado: Cancelada", summary_text(summary))
        self.assertEqual(summary.files_processed, 1)

    def test_preexisting_output_is_not_counted(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            old = Path(temporary) / "old.webp"
            old.write_bytes(b"x" * 5000)
            summary = BatchSummary(
                1, (result("current", ResultStatus.CONVERTED, 100, 40),), 1
            )
            self.assertEqual(summary.output_bytes, 40)

    def test_name_collisions_are_counted_and_reported(self) -> None:
        collision = FileResult(
            Path("My File.png"),
            Path("my_file.webp"),
            ResultStatus.CONVERTED,
            100,
            50,
            name_collision=True,
        )
        summary = BatchSummary(1, (collision,), 1)
        self.assertEqual(summary.name_collisions, 1)
        self.assertIn("Colisiones de nombre detectadas: 1", summary_text(summary))

    def test_file_warnings_are_aggregated(self) -> None:
        warned = FileResult(
            Path("a"),
            Path("a.out"),
            ResultStatus.CONVERTED,
            10,
            5,
            warnings=("one", "two"),
        )
        summary = BatchSummary(1, (warned,), 1)
        self.assertEqual(summary.warning_count, 2)
        self.assertIn("Avisos de archivos: 2", summary_text(summary))

    def test_elapsed_and_human_readable_formatting(self) -> None:
        summary = BatchSummary(0, (), 62.4)
        self.assertEqual(format_duration(summary.elapsed_seconds), "01:02")
        self.assertEqual(format_bytes(1536), "1.50 KB")
        self.assertIn("Tiempo transcurrido: 01:02", summary_text(summary))


if __name__ == "__main__":
    unittest.main()
