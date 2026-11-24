from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from tkinter import Tk, TclError
from unittest.mock import patch

from PIL import Image

from ui.app import ConverterApp
from ui.batch_review import BatchReview, inspect_sources
from ui.file_list import PAGE_SIZE


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.source = self.directory / "source"
        self.source.mkdir()
        self.destination = self.directory / "outputs"
        self.destination.mkdir()

    def build_window(self):
        with_settings = patch.dict(
            os.environ, APPDATA=str(self.directory), XDG_CONFIG_HOME=str(self.directory)
        )
        with_settings.start()
        self.addCleanup(with_settings.stop)
        try:
            self.root = Tk()
        except TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.callback_errors = []
        self.root.report_callback_exception = (
            lambda _, error, tb: self.callback_errors.append(error)
        )
        app = ConverterApp(self.root)
        self.panel = app.panels[0]
        self.panel.restore_sources(str(self.source), ())
        self.panel.output_format.set("PNG")
        self.panel.set_destination(self.destination)
        self.panel.only_smaller.set(False)

    def open_review(self):
        self.panel.review_button.invoke()
        return next(w for w in self.root.winfo_children() if isinstance(w, BatchReview))

    def wait_until(self, condition):
        # Enter a real Tk event loop so worker-to-main-thread dispatch also runs.
        deadline = time.monotonic() + 12

        def check():
            if condition() or self.callback_errors or time.monotonic() >= deadline:
                self.root.quit()
            else:
                self.root.after(10, check)

        self.root.after(0, check)
        self.root.mainloop()
        self.assertEqual(self.callback_errors, [])
        self.assertTrue(condition(), "Timed out waiting for the review or conversion")

    def test_review_through_conversion_preserves_subset_settings_and_relative_paths(
        self,
    ):
        keep = self.source / "arte" / "Icono.png"
        keep.parent.mkdir()
        Image.new("RGBA", (12, 8), (12, 34, 56, 128)).save(keep)
        original = keep.read_bytes()
        omit = self.source / "otro.png"
        omit.write_bytes(original)
        ignored = self.source / "convertidos_webp"
        ignored.mkdir()
        (ignored / "old.png").write_bytes(original)
        self.build_window()
        review = self.open_review()
        self.wait_until(lambda: review.timer is None)
        self.assertEqual(len(review.rows), 2)
        review.exclude_matches.invoke()
        self.assertTrue(review.convert.instate(("disabled",)))
        review.query.set("ARTE/ICONO")
        review.toggle_button.invoke()
        review.query.set("otro")
        self.assertEqual(review.included_bytes, len(original))
        self.assertFalse(any(self.destination.iterdir()))
        (self.source / "later.png").write_bytes(original)
        review.convert.invoke()
        self.wait_until(lambda: self.panel.finished_batch is not None)
        output = self.destination / "convertidos_png"
        self.assertEqual(self.panel.last_summary.converted, 1)
        self.assertEqual(self.panel.finished_batch.request.files, (keep,))
        self.assertEqual(
            list(output.rglob("*.png")), [output / keep.relative_to(self.source)]
        )
        with Image.open(output / keep.relative_to(self.source)) as image:
            self.assertEqual(image.convert("RGBA").getpixel((0, 0)), (12, 34, 56, 128))
        self.assertEqual(keep.read_bytes(), original)

    def test_bulk_selection_spans_pages_and_closing_writes_nothing(self):
        self.build_window()
        for index in range(PAGE_SIZE + 3):
            (self.source / f"asset-{index:03}.png").write_bytes(b"x")
        review = self.open_review()
        self.wait_until(lambda: review.timer is None)
        review.listing.next.invoke()
        self.assertEqual(len(review.listing.table.get_children()), 3)
        review.exclude_matches.invoke()
        self.assertEqual(review.included_bytes, 0)
        review.query.set("asset-10")
        review.include_matches.invoke()
        self.assertEqual(review.included_bytes, 3)
        review.destroy()
        self.assertFalse(self.panel.busy)
        self.assertFalse(any(self.destination.iterdir()))

    def test_closing_during_discovery_cancels_worker_and_releases_modal(self):
        self.build_window()
        finished = Event()

        def slow_scan(root, files, recursive, extensions, cancel):
            if cancel.wait(5):
                finished.set()
            return [], []

        with patch("ui.batch_review.inspect_sources", side_effect=slow_scan):
            review = self.open_review()
            review.destroy()
            self.assertTrue(finished.wait(2))
        self.assertIsNone(self.root.grab_current())
        self.assertFalse(any(self.destination.iterdir()))

    def test_unavailable_review_source_is_reported_alongside_valid_files(self):
        valid = self.source / "keep.png"
        valid.write_bytes(b"123")
        missing = self.source / "missing.png"
        rows, errors = inspect_sources(
            self.source, (valid, missing), False, {".png"}, Event()
        )
        self.assertEqual([(row.source, row.size) for row in rows], [(valid, 3)])
        self.assertEqual(len(errors), 1)
        self.assertIn(str(missing), errors[0])
