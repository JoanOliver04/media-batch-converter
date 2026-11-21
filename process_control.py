"""Encoding-safe subprocess helpers and reliable process shutdown."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

PROCESS_STOP_SECONDS = 2
PROCESS_KILL_SECONDS = 3
MEDIA_DEMUXERS = "aac,asf,avi,flac,matroska,webm,mov,mp4,m4a,mp3,mpeg,mpegts,ogg,wav"


def local_media_input(source: Path) -> list[str]:
    """Allow single-file media demuxers and the local file protocol."""
    return [
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        MEDIA_DEMUXERS,
        "-i",
        str(source),
    ]


def ffmpeg_transcode_args(source: Path) -> list[str]:
    return [
        "-nostdin",
        "-hide_banner",
        "-xerror",
        "-abort_on",
        "empty_output",
        "-y",
        *local_media_input(source),
        "-map_metadata",
        "0",
        "-progress",
        "pipe:2",
        "-nostats",
    ]


def creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def text_kwargs() -> dict[str, Any]:
    """UTF-8 text mode that never raises on decoder errors."""
    kwargs: dict[str, Any] = {
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    flags = creation_flags()
    if flags:
        kwargs["creationflags"] = flags
    return kwargs


def stop_process(process: subprocess.Popen[Any] | None, *, tree: bool = False) -> None:
    """Terminate *process*, then kill it (and its children when *tree*)."""
    if process is None or process.poll() is not None:
        return
    if tree:
        _kill_tree(process)
        return
    try:
        process.terminate()
        process.wait(timeout=PROCESS_STOP_SECONDS)
        return
    except (subprocess.TimeoutExpired, OSError):
        pass
    if process.poll() is not None:
        return
    try:
        process.kill()
        process.wait(timeout=PROCESS_KILL_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        _kill_tree(process)


def _kill_tree(process: subprocess.Popen[Any]) -> None:
    if sys.platform == "win32" and process.pid:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
                creationflags=creation_flags(),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            process.wait(timeout=PROCESS_KILL_SECONDS)
        except (subprocess.TimeoutExpired, OSError):
            return
        return
    try:
        process.kill()
        process.wait(timeout=PROCESS_KILL_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        return
