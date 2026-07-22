"""Safe, deterministic file discovery and destination path helpers."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path


OUTPUT_PREFIXES = ("converted_", "convertidos_")


@dataclass(slots=True)
class DiscoveryResult:
    files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False


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

    if not recursive:
        try:
            candidates = source.iterdir()
            result.files = [
                path
                for path in candidates
                if path.is_file()
                and not path.is_symlink()
                and path.suffix.casefold() in normalized_extensions
            ]
        except OSError as error:
            result.errors.append(f"{source}: {error}")
        result.files.sort(key=lambda path: path.as_posix().casefold())
        return result

    def record_error(error: OSError) -> None:
        result.errors.append(f"{error.filename or source}: {error.strerror or error}")

    for current, directory_names, file_names in os.walk(
        source, topdown=True, onerror=record_error, followlinks=False
    ):
        if cancel_event and cancel_event.is_set():
            result.cancelled = True
            break

        current_path = Path(current)
        directory_names[:] = sorted(
            (
                name
                for name in directory_names
                if not is_output_directory(current_path / name)
                and not (current_path / name).is_symlink()
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
                    not path.is_symlink()
                    and path.is_file()
                    and path.suffix.casefold() in normalized_extensions
                ):
                    result.files.append(path)
            except OSError as error:
                result.errors.append(f"{path}: {error}")

    result.files.sort(key=lambda path: path.relative_to(source).as_posix().casefold())
    return result


def safe_output_directory(
    output_root: Path, source_root: Path, source_file: Path
) -> Path:
    """Map a source file to its relative output directory, contained in output_root."""
    output_root = Path(output_root).resolve(strict=False)
    relative_parent = (
        Path(source_file)
        .resolve(strict=False)
        .relative_to(Path(source_root).resolve(strict=False))
        .parent
    )
    destination = (output_root / relative_parent).resolve(strict=False)
    if destination != output_root and output_root not in destination.parents:
        raise ValueError(
            "La ruta de salida calculada queda fuera del destino permitido."
        )
    return destination
