from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from conversion_results import BatchSummary, FileResult, ResultStatus
from output_policy import (
    OutputAction,
    OutputPolicy,
    cleanup_temporary,
    commit_output,
    plan_output,
    unique_path,
)


class OutputPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.png"
        self.target = self.root / "output.webp"
        self.source.write_bytes(b"source")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_skip_preserves_existing_destination(self) -> None:
        self.target.write_bytes(b"old")
        plan = plan_output(self.source, self.target, OutputPolicy.SKIP)
        self.assertFalse(plan.should_convert)
        self.assertEqual(plan.action, OutputAction.SKIP_EXISTS)
        self.assertEqual(self.target.read_bytes(), b"old")

    def test_atomic_overwrite(self) -> None:
        self.target.write_bytes(b"old")
        plan = plan_output(self.source, self.target, OutputPolicy.OVERWRITE)
        plan.temporary.write_bytes(b"new")
        commit_output(plan)
        self.assertEqual(self.target.read_bytes(), b"new")
        self.assertFalse(plan.temporary.exists())

    def test_failed_overwrite_preserves_old_destination(self) -> None:
        self.target.write_bytes(b"old")
        plan = plan_output(self.source, self.target, OutputPolicy.OVERWRITE)
        plan.temporary.write_bytes(b"partial")
        cleanup_temporary(plan)
        self.assertEqual(self.target.read_bytes(), b"old")
        self.assertFalse(plan.temporary.exists())

    def test_replace_permission_error_keeps_destination(self) -> None:
        self.target.write_bytes(b"old")
        plan = plan_output(self.source, self.target, OutputPolicy.OVERWRITE)
        plan.temporary.write_bytes(b"new")
        with patch(
            "output_policy.os.replace", side_effect=PermissionError("read only")
        ):
            with self.assertRaises(PermissionError):
                commit_output(plan)
        cleanup_temporary(plan)
        self.assertEqual(self.target.read_bytes(), b"old")

    def test_unique_names_and_existing_suffixes(self) -> None:
        self.target.write_bytes(b"one")
        self.root.joinpath("output_2.webp").write_bytes(b"two")
        self.assertEqual(unique_path(self.target).name, "output_3.webp")

    def test_case_insensitive_collision(self) -> None:
        self.root.joinpath("OUTPUT.WEBP").write_bytes(b"old")
        self.assertEqual(unique_path(self.target).name, "output_2.webp")

    def test_skip_detects_case_insensitive_existing_destination(self) -> None:
        uppercase = self.root / "OUTPUT.WEBP"
        uppercase.write_bytes(b"old")
        plan = plan_output(self.source, self.target, OutputPolicy.SKIP)
        self.assertFalse(plan.should_convert)
        self.assertEqual(plan.target, uppercase)

    def test_two_background_plans_reserve_different_unique_names(self) -> None:
        first = plan_output(self.source, self.target, OutputPolicy.UNIQUE)
        second = plan_output(self.source, self.target, OutputPolicy.UNIQUE)
        try:
            self.assertNotEqual(first.target, second.target)
            self.assertEqual(second.target.name, "output_2.webp")
        finally:
            cleanup_temporary(first)
            cleanup_temporary(second)

    def test_source_newer_and_destination_newer(self) -> None:
        self.target.write_bytes(b"old")
        os.utime(self.source, ns=(2_000_000_000, 2_000_000_000))
        os.utime(self.target, ns=(1_000_000_000, 1_000_000_000))
        newer = plan_output(self.source, self.target, OutputPolicy.SOURCE_NEWER)
        self.assertTrue(newer.should_convert)
        self.assertEqual(newer.action, OutputAction.OVERWRITE)

        os.utime(self.target, ns=(3_000_000_000, 3_000_000_000))
        current = plan_output(self.source, self.target, OutputPolicy.SOURCE_NEWER)
        self.assertFalse(current.should_convert)
        self.assertEqual(current.action, OutputAction.SKIP_UP_TO_DATE)

    def test_equal_timestamp_is_up_to_date(self) -> None:
        self.target.write_bytes(b"old")
        os.utime(self.source, ns=(2_000_000_000, 2_000_000_000))
        os.utime(self.target, ns=(2_000_000_000, 2_000_000_000))
        plan = plan_output(self.source, self.target, OutputPolicy.SOURCE_NEWER)
        self.assertEqual(plan.action, OutputAction.SKIP_UP_TO_DATE)

    def test_cancellation_cleanup_removes_only_temporary(self) -> None:
        self.target.write_bytes(b"old")
        plan = plan_output(self.source, self.target, OutputPolicy.OVERWRITE)
        plan.temporary.write_bytes(b"partial")
        cleanup_temporary(plan)
        self.assertTrue(self.target.exists())
        self.assertFalse(plan.temporary.exists())


class PolicySummaryTests(unittest.TestCase):
    def test_summary_distinguishes_policy_outcomes(self) -> None:
        results = (
            FileResult(
                Path("a"),
                Path("a.out"),
                ResultStatus.CONVERTED,
                10,
                5,
                output_action="overwritten",
            ),
            FileResult(
                Path("b"),
                Path("b_2.out"),
                ResultStatus.CONVERTED,
                10,
                5,
                output_action="renamed",
            ),
            FileResult(
                Path("c"),
                Path("c.out"),
                ResultStatus.SKIPPED,
                10,
                output_action="skipped_exists",
            ),
            FileResult(
                Path("d"),
                Path("d.out"),
                ResultStatus.SKIPPED,
                10,
                output_action="skipped_up_to_date",
            ),
        )
        summary = BatchSummary(4, results, 1)
        self.assertEqual((summary.overwritten, summary.renamed), (1, 1))
        self.assertEqual((summary.skipped_existing, summary.skipped_up_to_date), (1, 1))


if __name__ == "__main__":
    unittest.main()
