from __future__ import annotations

import errno
import unittest

from error_handling import ErrorCode, UserFacingError, describe_error


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

    def test_user_facing_error_keeps_the_translated_message(self) -> None:
        error = UserFacingError("El PDF está cifrado.", ErrorCode.UNSUPPORTED)
        description = describe_error(error)
        self.assertEqual(description.code, ErrorCode.UNSUPPORTED)
        self.assertEqual(description.message, "El PDF está cifrado.")


if __name__ == "__main__":
    unittest.main()
