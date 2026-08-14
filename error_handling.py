"""Consistent, structured and safe user-facing error descriptions."""

from __future__ import annotations

import errno
from dataclasses import dataclass
from enum import StrEnum

from i18n import t


class ErrorCode(StrEnum):
    CANCELLED = "CANCELLED"
    NOT_FOUND = "NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    DISK_FULL = "DISK_FULL"
    INVALID_SETTINGS = "INVALID_SETTINGS"
    UNSUPPORTED = "UNSUPPORTED"
    PROCESS_FAILED = "PROCESS_FAILED"
    IO_ERROR = "IO_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ErrorDescription:
    code: ErrorCode
    message: str
    detail: str


class UserFacingError(Exception):
    """An exception whose message is already translated for the user."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.UNSUPPORTED) -> None:
        super().__init__(message)
        self.user_message = message
        self.error_code = code


def describe_error(error: BaseException) -> ErrorDescription:
    detail = str(error) or type(error).__name__
    if isinstance(error, UserFacingError):
        return ErrorDescription(error.error_code, error.user_message, detail)
    if isinstance(error, InterruptedError):
        return ErrorDescription(ErrorCode.CANCELLED, t("error.cancelled"), detail)
    if isinstance(error, FileNotFoundError):
        return ErrorDescription(
            ErrorCode.NOT_FOUND,
            t("error.not_found"),
            detail,
        )
    if isinstance(error, PermissionError):
        return ErrorDescription(
            ErrorCode.PERMISSION_DENIED,
            t("error.permission"),
            detail,
        )
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return ErrorDescription(
            ErrorCode.DISK_FULL,
            t("error.disk_space"),
            detail,
        )
    if isinstance(error, (ValueError, KeyError)):
        return ErrorDescription(
            ErrorCode.INVALID_SETTINGS,
            t("error.invalid_settings"),
            detail,
        )
    if isinstance(error, NotImplementedError):
        return ErrorDescription(
            ErrorCode.UNSUPPORTED,
            t("error.unsupported"),
            detail,
        )
    if isinstance(error, RuntimeError):
        return ErrorDescription(
            ErrorCode.PROCESS_FAILED,
            t("error.encoder_failed"),
            detail,
        )
    if isinstance(error, OSError):
        return ErrorDescription(
            ErrorCode.IO_ERROR,
            t("error.io"),
            detail,
        )
    return ErrorDescription(
        ErrorCode.UNKNOWN,
        t("error.unexpected"),
        detail,
    )
