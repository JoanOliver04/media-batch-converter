"""Consistent, structured and safe user-facing error descriptions."""

from __future__ import annotations

import errno
from dataclasses import dataclass
from enum import StrEnum


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


def describe_error(error: BaseException) -> ErrorDescription:
    detail = str(error) or type(error).__name__
    if isinstance(error, InterruptedError):
        return ErrorDescription(
            ErrorCode.CANCELLED, "La operación fue cancelada.", detail
        )
    if isinstance(error, FileNotFoundError):
        return ErrorDescription(
            ErrorCode.NOT_FOUND,
            "No se encontró el archivo de origen o una herramienta requerida.",
            detail,
        )
    if isinstance(error, PermissionError):
        return ErrorDescription(
            ErrorCode.PERMISSION_DENIED,
            "Permiso denegado al leer el origen o escribir el destino.",
            detail,
        )
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return ErrorDescription(
            ErrorCode.DISK_FULL,
            "No hay espacio suficiente en el disco de destino.",
            detail,
        )
    if isinstance(error, (ValueError, KeyError)):
        return ErrorDescription(
            ErrorCode.INVALID_SETTINGS,
            "Los ajustes de conversión no son válidos.",
            detail,
        )
    if isinstance(error, NotImplementedError):
        return ErrorDescription(
            ErrorCode.UNSUPPORTED,
            "La operación solicitada no es compatible con esta configuración.",
            detail,
        )
    if isinstance(error, RuntimeError):
        return ErrorDescription(
            ErrorCode.PROCESS_FAILED,
            "El codificador no pudo completar la conversión. Consulta el registro local para ver el detalle.",
            detail,
        )
    if isinstance(error, OSError):
        return ErrorDescription(
            ErrorCode.IO_ERROR,
            "Se produjo un error al leer o escribir los archivos.",
            detail,
        )
    return ErrorDescription(
        ErrorCode.UNKNOWN,
        "Se produjo un error inesperado. Consulta el registro local para ver el detalle.",
        detail,
    )
