"""Capa de presentación Tkinter del conversor."""

from __future__ import annotations

from ui.app import ConverterApp, main
from ui.audio_panel import AudioPanel
from ui.base import ConverterPanel
from ui.diagnostics import DiagnosticsPanel
from ui.document_panel import DocumentPanel
from ui.ffmpeg_panel import FFmpegPanel
from ui.image_panel import ImagePanel
from ui.video_panel import VideoPanel
from ui.widgets import ScrollableTab

__all__ = [
    "AudioPanel",
    "ConverterApp",
    "ConverterPanel",
    "DiagnosticsPanel",
    "DocumentPanel",
    "FFmpegPanel",
    "ImagePanel",
    "ScrollableTab",
    "VideoPanel",
    "main",
]
