from __future__ import annotations

import errno
import unittest

from error_handling import ErrorCode, describe_error


class ErrorHandlingTests(unittest.TestCase):
    def test_common_user_facing_errors_are_structured(self) -> None:
        cases = (
            (PermissionError("private path denied"), ErrorCode.PERMISSION_DENIED),
            (OSError(errno.ENOSPC, "disk full"), ErrorCode.DISK_FULL),
            (FileNotFoundError("missing"), ErrorCode.NOT_FOUND),
            (ValueError("bad resize"), ErrorCode.INVALID_SETTINGS),
            (NotImplementedError("codec"), ErrorCode.UNSUPPORTED),
            (InterruptedError("worker interrupted internally"), ErrorCode.CANCELLED),
            (RuntimeError("raw ffmpeg stderr"), ErrorCode.PROCESS_FAILED),
        )
        for error, expected in cases:
            with self.subTest(expected=expected):
                description = describe_error(error)
                self.assertEqual(description.code, expected)
                self.assertNotIn(str(error), description.message)
                self.assertEqual(description.detail, str(error))


if __name__ == "__main__":
    unittest.main()
