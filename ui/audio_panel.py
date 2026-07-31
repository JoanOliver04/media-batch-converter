"""Panel de conversión de audio."""

from __future__ import annotations

from pathlib import Path
from tkinter import StringVar, Tk, ttk

from audio_encoding import (
    build_audio_args,
    manual_audio_settings,
    validate_audio_settings,
)
from i18n import t
from presets import AUDIO_PRESETS, CUSTOM_PRESET_ID, AudioSettings, preset_by_id
from ui.ffmpeg_panel import FFmpegPanel
from ui.formats import AUDIO_EXTENSIONS, AUDIO_FORMATS


class AudioPanel(FFmpegPanel):
    MEDIA_TYPE = "audio"

    def __init__(self, parent, root: Tk) -> None:
        super().__init__(
            parent, root, t("ui.title.audio"), AUDIO_EXTENSIONS, AUDIO_FORMATS
        )
        self._applying_audio_preset = False
        self.audio_preset_display = StringVar(value=t("ui.preset.custom"))
        self.audio_preset_description = StringVar(value=t("ui.preset.audio_manual"))
        self.audio_sample_rate = StringVar(value=t("ui.audio.preserve"))
        self.audio_channels = StringVar(value=t("ui.audio.preserve"))
        self.audio_bitrate = StringVar(value="192")
        self._audio_preset_ids = {
            preset.display_name: preset.preset_id for preset in AUDIO_PRESETS
        }

        ttk.Label(self.options_frame, text=t("ui.label.audio_preset")).grid(
            row=1, column=0, padx=(0, 10), pady=(10, 0), sticky="w"
        )
        self.audio_preset_selector = ttk.Combobox(
            self.options_frame,
            textvariable=self.audio_preset_display,
            values=(
                t("ui.preset.custom"),
                *(preset.display_name for preset in AUDIO_PRESETS),
            ),
            state="readonly",
            width=28,
        )
        self.audio_preset_selector.grid(
            row=1, column=1, padx=(0, 16), pady=(10, 0), sticky="w"
        )
        ttk.Label(
            self.options_frame,
            textvariable=self.audio_preset_description,
            wraplength=390,
        ).grid(row=1, column=2, columnspan=3, pady=(10, 0), sticky="w")
        self.audio_preset_selector.bind(
            "<<ComboboxSelected>>", self.apply_selected_audio_preset
        )

        for row in range(6, 3, -1):
            for widget in self.grid_slaves(row=row):
                widget.grid_configure(row=row + 1)
        self.audio_advanced = ttk.LabelFrame(
            self, text=t("ui.frame.audio"), padding=(10, 7)
        )
        self.audio_advanced.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(self.audio_advanced, text=t("ui.label.sample_rate")).grid(
            row=0, column=0
        )
        self.audio_sample_selector = ttk.Combobox(
            self.audio_advanced,
            textvariable=self.audio_sample_rate,
            values=(t("ui.audio.preserve"), "44100", "48000"),
            state="readonly",
            width=11,
        )
        self.audio_sample_selector.grid(row=0, column=1, padx=(8, 20))
        ttk.Label(self.audio_advanced, text=t("ui.label.channels")).grid(
            row=0, column=2
        )
        self.audio_channel_selector = ttk.Combobox(
            self.audio_advanced,
            textvariable=self.audio_channels,
            values=(t("ui.audio.preserve"), t("ui.audio.mono"), t("ui.audio.stereo")),
            state="readonly",
            width=11,
        )
        self.audio_channel_selector.grid(row=0, column=3, padx=(8, 20))
        ttk.Label(self.audio_advanced, text=t("ui.label.bitrate")).grid(row=0, column=4)
        self.audio_bitrate_entry = ttk.Entry(
            self.audio_advanced, textvariable=self.audio_bitrate, width=7
        )
        self.audio_bitrate_entry.grid(row=0, column=5, padx=(8, 0))
        ttk.Label(
            self.audio_advanced,
            text=t("ui.audio.no_loudness_note"),
        ).grid(row=1, column=0, columnspan=6, pady=(6, 0), sticky="w")

        for variable in (
            self.output_format,
            self.quality,
            self.audio_sample_rate,
            self.audio_channels,
            self.audio_bitrate,
        ):
            variable.trace_add("write", self.audio_settings_changed)
        self.apply_audio_preset_id(self.settings_store.load_last_audio_preset())

    def apply_selected_audio_preset(self, _event=None) -> None:
        self.apply_audio_preset_id(
            self._audio_preset_ids.get(
                self.audio_preset_display.get(), CUSTOM_PRESET_ID
            )
        )

    def apply_audio_preset_id(self, preset_id: str) -> None:
        preset = preset_by_id(preset_id)
        if (
            preset is None
            or preset.media_category != "audio"
            or preset.audio_settings is None
        ):
            self.audio_preset_display.set(t("ui.preset.custom"))
            self.audio_preset_description.set(t("ui.preset.audio_manual"))
            selected_id = CUSTOM_PRESET_ID
        else:
            settings = preset.audio_settings
            self._applying_audio_preset = True
            try:
                self.audio_preset_display.set(preset.display_name)
                self.audio_preset_description.set(preset.description)
                self.output_format.set(preset.output_format)
                self.audio_sample_rate.set(
                    str(settings.sample_rate)
                    if settings.sample_rate
                    else t("ui.audio.preserve")
                )
                self.audio_channels.set(
                    {
                        None: t("ui.audio.preserve"),
                        1: t("ui.audio.mono"),
                        2: t("ui.audio.stereo"),
                    }[settings.channels]
                )
                self.audio_bitrate.set(
                    str(settings.bitrate_kbps) if settings.bitrate_kbps else ""
                )
                selected_id = preset.preset_id
            finally:
                self._applying_audio_preset = False
        try:
            self.settings_store.save_last_audio_preset(selected_id)
        except OSError:
            pass

    def audio_settings_changed(self, *_args) -> None:
        if self._applying_audio_preset:
            return
        self.audio_preset_display.set(t("ui.preset.custom"))
        self.audio_preset_description.set(t("ui.preset.audio_modified"))
        try:
            self.settings_store.save_last_audio_preset(CUSTOM_PRESET_ID)
        except OSError:
            pass

    def current_audio_settings(self) -> AudioSettings:
        sample_rate = (
            None
            if self.audio_sample_rate.get() == t("ui.audio.preserve")
            else int(self.audio_sample_rate.get())
        )
        channels = {
            t("ui.audio.preserve"): None,
            t("ui.audio.mono"): 1,
            t("ui.audio.stereo"): 2,
        }[self.audio_channels.get()]
        bitrate_text = self.audio_bitrate.get().strip()
        bitrate = int(bitrate_text) if bitrate_text else None
        return manual_audio_settings(
            self.output_format.get(),
            self.quality.get(),
            sample_rate,
            channels,
            bitrate,
        )

    def validate_start(self) -> str | None:
        try:
            validate_audio_settings(
                self.output_format.get(), self.current_audio_settings()
            )
        except (KeyError, ValueError, NotImplementedError) as error:
            return str(error)
        return None

    def conversion_options(self) -> dict[str, object]:
        options = super().conversion_options()
        options["audio_settings"] = self.current_audio_settings()
        options["audio_preset"] = self._audio_preset_ids.get(
            self.audio_preset_display.get(), CUSTOM_PRESET_ID
        )
        return options

    def set_busy(self, busy: bool) -> None:
        super().set_busy(busy)
        selector_state = "disabled" if busy else "readonly"
        self.audio_preset_selector.configure(state=selector_state)
        self.audio_sample_selector.configure(state=selector_state)
        self.audio_channel_selector.configure(state=selector_state)
        self.audio_bitrate_entry.configure(state="disabled" if busy else "normal")

    def convert_batch(
        self,
        source_root: Path,
        files: list[Path],
        output_format: str,
        quality: int,
        initial_errors: list[str] | None = None,
        options: dict[str, object] | None = None,
    ) -> None:
        settings = (options or {}).get("audio_settings")
        if not isinstance(settings, AudioSettings):
            settings = manual_audio_settings(output_format, quality, None, None, None)
        self.convert_ffmpeg_batch(
            source_root,
            files,
            output_format,
            AUDIO_FORMATS[output_format],
            build_audio_args(output_format, settings),
            list(initial_errors or []),
            options,
            True,
            required_encoder=settings.codec,
        )
