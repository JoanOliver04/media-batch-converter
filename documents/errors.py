"""Document-specific failures that already carry a translated message."""

from __future__ import annotations

from error_handling import ErrorCode, UserFacingError


class DocumentError(UserFacingError):
    """A conversion or inspection problem the user can act on."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.UNSUPPORTED) -> None:
        super().__init__(message, code)
