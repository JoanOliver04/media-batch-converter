from __future__ import annotations

import unittest
from unittest.mock import Mock

from process_control import stop_process, text_kwargs


class ProcessControlTests(unittest.TestCase):
    def test_text_kwargs_use_utf8_and_replace(self) -> None:
        kwargs = text_kwargs()
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["errors"], "replace")
        self.assertTrue(kwargs["text"])

    def test_stop_process_skips_finished_handles(self) -> None:
        process = Mock()
        process.poll.return_value = 0
        stop_process(process)
        process.terminate.assert_not_called()

    def test_stop_process_kills_when_terminate_times_out(self) -> None:
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [
            __import__("subprocess").TimeoutExpired("x", 1),
            None,
        ]
        stop_process(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
