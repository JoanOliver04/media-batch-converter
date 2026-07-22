"""Typed, extensible conversion presets and lightweight settings persistence."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from webp_encoding import WebPMode


CUSTOM_PRESET_ID = "custom"


@dataclass(frozen=True, slots=True)
class ConversionPreset:
    preset_id: str
    display_name: str
    description: str
    media_category: str
    output_format: str
    quality: int | None = None
    webp_mode: WebPMode | None = None
    resize_mode: str = "original"
    audio_settings: dict[str, object] | None = None
    video_settings: dict[str, object] | None = None


IMAGE_PRESETS = (
    ConversionPreset(
        "high_quality_illustration",
        "Ilustración de alta calidad",
        "WebP detallado con buena reducción de tamaño.",
        "image",
        "WebP",
        90,
        WebPMode.LOSSY,
    ),
    ConversionPreset(
        "general_mobile_asset",
        "Recurso móvil general",
        "Equilibrio automático para recursos de uso general.",
        "image",
        "WebP",
        88,
        WebPMode.AUTOMATIC,
    ),
    ConversionPreset(
        "large_background",
        "Fondo grande",
        "Compresión eficiente para imágenes de fondo extensas.",
        "image",
        "WebP",
        82,
        WebPMode.LOSSY,
    ),
    ConversionPreset(
        "transparent_ui_asset",
        "Recurso de interfaz transparente",
        "WebP sin pérdida para bordes y transparencias exactos.",
        "image",
        "WebP",
        None,
        WebPMode.LOSSLESS,
    ),
    ConversionPreset(
        "thumbnail",
        "Miniatura",
        "WebP compacto; el redimensionado se podrá configurar más adelante.",
        "image",
        "WebP",
        78,
        WebPMode.LOSSY,
    ),
    ConversionPreset(
        "lossless_archive",
        "Archivo sin pérdida",
        "PNG con optimización máxima y sin pérdida de calidad.",
        "image",
        "PNG",
        None,
        None,
    ),
)

PRESETS_BY_ID = {preset.preset_id: preset for preset in IMAGE_PRESETS}


def preset_by_id(preset_id: str | None) -> ConversionPreset | None:
    return PRESETS_BY_ID.get(preset_id or "")


def normalized_preset_id(preset_id: str | None) -> str:
    return preset_id if preset_id in PRESETS_BY_ID else CUSTOM_PRESET_ID


def preset_matches(
    preset: ConversionPreset, output_format: str, quality: int, webp_mode: str
) -> bool:
    if preset.output_format != output_format:
        return False
    if preset.quality is not None and preset.quality != quality:
        return False
    if preset.webp_mode is not None and preset.webp_mode.value != webp_mode:
        return False
    return True


def default_settings_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "MediaBatchConverter" / "settings.json"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else default_settings_path()

    def load_last_image_preset(self) -> str:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return CUSTOM_PRESET_ID
        return normalized_preset_id(data.get("last_image_preset"))

    def save_last_image_preset(self, preset_id: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"last_image_preset": normalized_preset_id(preset_id)}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def public_preset_data() -> list[dict[str, object]]:
    """Expose serializable data for validation and future media categories."""
    return [asdict(preset) for preset in IMAGE_PRESETS]
