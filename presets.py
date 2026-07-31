"""Typed, extensible conversion presets and lightweight settings persistence."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from i18n import normalized_language, t
from video_encoding import VideoSettings
from webp_encoding import WebPMode

CUSTOM_PRESET_ID = "custom"


@dataclass(frozen=True, slots=True)
class AudioSettings:
    codec: str
    sample_rate: int | None
    channels: int | None
    bitrate_kbps: int | None
    quality_mode: str
    profile: str | None = None
    normalize_loudness: bool = False


@dataclass(frozen=True, slots=True)
class ConversionPreset:
    """Un preset.

    El nombre y la descripción visibles no se almacenan: se derivan del
    `preset_id` y se resuelven en cada acceso, de modo que siguen al idioma
    activo sin tener que reconstruir los presets.
    """

    preset_id: str
    media_category: str
    output_format: str
    quality: int | None = None
    webp_mode: WebPMode | None = None
    resize_mode: str = "original"
    audio_settings: AudioSettings | None = None
    video_settings: VideoSettings | None = None

    @property
    def display_name(self) -> str:
        return t(f"preset.{self.preset_id}.name")

    @property
    def description(self) -> str:
        return t(f"preset.{self.preset_id}.description")


IMAGE_PRESETS = (
    ConversionPreset(
        "high_quality_illustration",
        "image",
        "WebP",
        90,
        WebPMode.LOSSY,
    ),
    ConversionPreset(
        "general_mobile_asset",
        "image",
        "WebP",
        88,
        WebPMode.AUTOMATIC,
    ),
    ConversionPreset(
        "large_background",
        "image",
        "WebP",
        82,
        WebPMode.LOSSY,
    ),
    ConversionPreset(
        "transparent_ui_asset",
        "image",
        "WebP",
        None,
        WebPMode.LOSSLESS,
    ),
    ConversionPreset(
        "thumbnail",
        "image",
        "WebP",
        78,
        WebPMode.LOSSY,
    ),
    ConversionPreset(
        "lossless_archive",
        "image",
        "PNG",
        None,
        None,
    ),
)

AUDIO_PRESETS = (
    ConversionPreset(
        "runtime_music",
        "audio",
        "M4A",
        audio_settings=AudioSettings("aac", 48_000, 2, 192, "bitrate", "aac_low"),
    ),
    ConversionPreset(
        "runtime_ambience",
        "audio",
        "M4A",
        audio_settings=AudioSettings("aac", 48_000, 2, 160, "bitrate", "aac_low"),
    ),
    ConversionPreset(
        "runtime_sound_effect",
        "audio",
        "M4A",
        audio_settings=AudioSettings("aac", 48_000, 1, 128, "bitrate", "aac_low"),
    ),
    ConversionPreset(
        "master_wav",
        "audio",
        "WAV",
        audio_settings=AudioSettings("pcm_s24le", 48_000, None, None, "lossless"),
    ),
    ConversionPreset(
        "voice_dialogue",
        "audio",
        "M4A",
        audio_settings=AudioSettings("aac", 48_000, 1, 96, "bitrate", "aac_low"),
    ),
)

VIDEO_PRESETS = (
    ConversionPreset(
        "in_app_720p",
        "video",
        "MP4",
        video_settings=VideoSettings(
            "libx264", "aac", 1280, 720, "preserve", 30, 23, faststart=True
        ),
    ),
    ConversionPreset(
        "high_quality_1080p",
        "video",
        "MP4",
        video_settings=VideoSettings(
            "libx264", "aac", 1920, 1080, "preserve", 30, 21, faststart=True
        ),
    ),
    ConversionPreset(
        "vertical_social",
        "video",
        "MP4",
        video_settings=VideoSettings(
            "libx264", "aac", 1080, 1920, "fit", 30, 22, faststart=True
        ),
    ),
    ConversionPreset(
        "horizontal_trailer",
        "video",
        "MP4",
        video_settings=VideoSettings(
            "libx264", "aac", 1920, 1080, "preserve", 30, 20, faststart=True
        ),
    ),
    ConversionPreset(
        "webm_vp9",
        "video",
        "WebM",
        video_settings=VideoSettings(
            "libvpx-vp9", "libopus", None, None, "preserve", None, 30
        ),
    ),
)
PRESETS_BY_ID = {
    preset.preset_id: preset
    for preset in (*IMAGE_PRESETS, *AUDIO_PRESETS, *VIDEO_PRESETS)
}


def preset_by_id(preset_id: str | None) -> ConversionPreset | None:
    return PRESETS_BY_ID.get(preset_id or "")


def normalized_preset_id(preset_id: str | None) -> str:
    image_ids = {preset.preset_id for preset in IMAGE_PRESETS}
    return preset_id if preset_id in image_ids else CUSTOM_PRESET_ID


def preset_matches(
    preset: ConversionPreset,
    output_format: str,
    quality: int,
    webp_mode: str,
    resize_mode: str = "original",
) -> bool:
    if preset.output_format != output_format:
        return False
    if preset.quality is not None and preset.quality != quality:
        return False
    if preset.webp_mode is not None and preset.webp_mode.value != webp_mode:
        return False
    return preset.resize_mode == resize_mode


def default_settings_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "MediaBatchConverter" / "settings.json"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else default_settings_path()

    def _read(self) -> dict[str, object]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _update(self, key: str, value: object) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._read()
        payload[key] = value
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def load_last_image_preset(self) -> str:
        return normalized_preset_id(self._read().get("last_image_preset"))

    def save_last_image_preset(self, preset_id: str) -> None:
        self._update("last_image_preset", normalized_preset_id(preset_id))

    def load_output_policy(self) -> str:
        value = self._read().get("output_policy")
        return (
            value
            if value in {"skip", "overwrite", "unique", "source_newer"}
            else "skip"
        )

    def save_output_policy(self, policy: str) -> None:
        value = (
            policy
            if policy in {"skip", "overwrite", "unique", "source_newer"}
            else "skip"
        )
        self._update("output_policy", value)

    def load_language(self) -> str:
        return str(normalized_language(self._read().get("language")))

    def save_language(self, language: str) -> None:
        self._update("language", str(normalized_language(language)))

    def load_normalize_filenames(self) -> bool:
        return self._read().get("normalize_filenames") is True

    def save_normalize_filenames(self, enabled: bool) -> None:
        self._update("normalize_filenames", bool(enabled))

    def load_generate_report(self) -> bool:
        return self._read().get("generate_report") is True

    def save_generate_report(self, enabled: bool) -> None:
        self._update("generate_report", bool(enabled))

    def load_report_absolute_paths(self) -> bool:
        return self._read().get("report_absolute_paths") is True

    def save_report_absolute_paths(self, enabled: bool) -> None:
        self._update("report_absolute_paths", bool(enabled))

    def load_last_audio_preset(self) -> str:
        value = self._read().get("last_audio_preset")
        audio_ids = {preset.preset_id for preset in AUDIO_PRESETS}
        return value if value in audio_ids else CUSTOM_PRESET_ID

    def save_last_audio_preset(self, preset_id: str) -> None:
        audio_ids = {preset.preset_id for preset in AUDIO_PRESETS}
        self._update(
            "last_audio_preset",
            preset_id if preset_id in audio_ids else CUSTOM_PRESET_ID,
        )

    def load_last_video_preset(self) -> str:
        value = self._read().get("last_video_preset")
        video_ids = {preset.preset_id for preset in VIDEO_PRESETS}
        return value if value in video_ids else CUSTOM_PRESET_ID

    def save_last_video_preset(self, preset_id: str) -> None:
        video_ids = {preset.preset_id for preset in VIDEO_PRESETS}
        self._update(
            "last_video_preset",
            preset_id if preset_id in video_ids else CUSTOM_PRESET_ID,
        )

    def load_animation_mode(self) -> str:
        value = self._read().get("animation_mode")
        return (
            value
            if value in {"preserve", "extract_frames", "first_frame"}
            else "preserve"
        )

    def save_animation_mode(self, mode: str) -> None:
        value = (
            mode
            if mode in {"preserve", "extract_frames", "first_frame"}
            else "preserve"
        )
        self._update("animation_mode", value)


def public_preset_data() -> list[dict[str, object]]:
    """Expose serializable data for validation and future media categories.

    Los textos visibles se resuelven en el idioma activo, ya que no forman
    parte de los campos del preset.
    """
    return [
        {
            **asdict(preset),
            "display_name": preset.display_name,
            "description": preset.description,
        }
        for preset in (*IMAGE_PRESETS, *AUDIO_PRESETS, *VIDEO_PRESETS)
    ]
