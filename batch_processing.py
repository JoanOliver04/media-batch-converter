"""Safe, deterministic file discovery and destination path helpers."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from error_handling import UserFacingError
from i18n import t

OUTPUT_PREFIXES = ("converted_", "convertidos_")


@dataclass(slots=True)
class DiscoveryResult:
    files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False


class UnsafePathError(UserFacingError, ValueError):
    def __init__(self) -> None:
        super().__init__(t("discovery.unsafe_path"))


def is_link(path: Path) -> bool:
    """True for symlinks and Windows directory junctions."""
    try:
        return path.is_symlink() or path.is_junction()
    except OSError:
        return True


def is_output_directory(path: Path) -> bool:
    """Return whether *path* looks like an application output folder."""
    return path.name.casefold().startswith(OUTPUT_PREFIXES)


def discover_files(
    source: Path,
    extensions: set[str],
    recursive: bool = True,
    cancel_event: threading.Event | None = None,
) -> DiscoveryResult:
    """Discover supported files without following directory symlinks."""
    source = Path(source)
    normalized_extensions = {extension.casefold() for extension in extensions}
    result = DiscoveryResult()

    if cancel_event and cancel_event.is_set():
        result.cancelled = True
        return result

    if is_link(source):
        result.errors.append(t("discovery.unsafe_path"))
        return result

    if not recursive:
        try:
            for path in source.iterdir():
                if cancel_event and cancel_event.is_set():
                    result.cancelled = True
                    break
                if (
                    path.suffix.casefold() in normalized_extensions
                    and not is_link(path)
                    and path.is_file()
                ):
                    result.files.append(path)
        except OSError as error:
            result.errors.append(f"{source}: {error}")
        result.files.sort(key=lambda path: (path.name.casefold(), path.name))
        return result

    def record_error(error: OSError) -> None:
        result.errors.append(f"{error.filename or source}: {error.strerror or error}")

    seen: set[str] = set()
    for current, directory_names, file_names in os.walk(
        source, topdown=True, onerror=record_error, followlinks=False
    ):
        if cancel_event and cancel_event.is_set():
            result.cancelled = True
            break

        current_path = Path(current)
        try:
            resolved = str(current_path.resolve(strict=False)).casefold()
        except OSError:
            directory_names[:] = []
            continue
        if resolved in seen:
            directory_names[:] = []
            continue
        seen.add(resolved)
        directory_names[:] = sorted(
            (
                name
                for name in directory_names
                if not is_output_directory(current_path / name)
                and not is_link(current_path / name)
            ),
            key=str.casefold,
        )
        for name in sorted(file_names, key=str.casefold):
            if cancel_event and cancel_event.is_set():
                result.cancelled = True
                break
            path = current_path / name
            try:
                if (
                    not is_link(path)
                    and path.is_file()
                    and path.suffix.casefold() in normalized_extensions
                ):
                    result.files.append(path)
            except OSError as error:
                result.errors.append(f"{path}: {error}")

    def sort_key(path: Path) -> tuple[str, str]:
        relative = path.relative_to(source).as_posix()
        return relative.casefold(), relative

    result.files.sort(key=sort_key)
    return result


def checked_output_root(output_root: Path) -> Path:
    if is_link(output_root):
        raise UnsafePathError()
    return output_root.resolve(strict=False)


def safe_output_directory(
    output_root: Path, source_root: Path, source_file: Path
) -> Path:
    """Map a source file to its relative output directory, contained in output_root."""
    output_root = checked_output_root(Path(output_root))
    if is_link(source_file):
        raise UnsafePathError()
    relative_parent = (
        Path(source_file)
        .resolve(strict=False)
        .relative_to(Path(source_root).resolve(strict=False))
        .parent
    )
    destination = output_root
    for component in relative_parent.parts:
        destination /= component
        if is_link(destination):
            raise UnsafePathError()
    return destination
