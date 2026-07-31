"""Panel de conversión de vídeo."""

from __future__ import annotations

from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, ttk

from i18n import t
from presets import CUSTOM_PRESET_ID, VIDEO_PRESETS, preset_by_id
from ui.ffmpeg_panel import FFmpegPanel
from ui.formats import VIDEO_EXTENSIONS, VIDEO_FORMATS
from video_encoding import VideoSettings, build_video_args, validate_video_settings


class VideoPanel(FFmpegPanel):
    MEDIA_TYPE = "video"
    NAME_EXAMPLE_KEY = "ui.output_name.example.video"
    #: Clave de traducción por código estable de FFmpeg. La etiqueta visible se
    #: resuelve al construir el panel, nunca se almacena.
    ASPECT_MODES = (
        ("ui.video.aspect.preserve", "preserve"),
        ("ui.video.aspect.fit", "fit"),
        ("ui.video.aspect.fill", "fill"),
        ("ui.video.aspect.stretch", "stretch"),
    )
    CODECS = {
        "MP4": ("libx264", "aac"),
        "MOV": ("libx264", "aac"),
        "MKV": ("libx264", "aac"),
        "WebM": ("libvpx-vp9", "libopus"),
        "AVI": ("mpeg4", "libmp3lame"),
    }

    def __init__(self, parent, root: Tk) -> None:
        super().__init__(
            parent, root, t("ui.title.video"), VIDEO_EXTENSIONS, VIDEO_FORMATS
        )
        self._applying_video_preset = False
        self.video_preset_display = StringVar(value=t("ui.preset.custom"))
        self.video_preset_description = StringVar(value=t("ui.preset.video_manual"))
        self.video_width = StringVar(value="")
        self.video_height = StringVar(value="")
        self.video_fps = StringVar(value="30")
        self._aspect_by_display = {t(key): code for key, code in self.ASPECT_MODES}
        self.video_aspect = StringVar(value=t("ui.video.aspect.preserve"))
        self.video_codec = StringVar(value="libx264")
        self.video_audio_codec = StringVar(value="aac")
        self.video_remove_audio = BooleanVar(value=False)
        self.video_background = StringVar(value="black")
        self.video_max_size = StringVar(value="")
        self.video_size_guidance = StringVar(value=t("ui.video.size_guidance"))
        self._video_preset_ids = {
            preset.display_name: preset.preset_id for preset in VIDEO_PRESETS
        }

        ttk.Label(self.options_frame, text=t("ui.label.video_preset")).grid(
            row=1, column=0, padx=(0, 10), pady=(10, 0), sticky="w"
        )
        self.video_preset_selector = ttk.Combobox(
            self.options_frame,
            textvariable=self.video_preset_display,
            values=(t("ui.preset.custom"), *(p.display_name for p in VIDEO_PRESETS)),
            state="readonly",
            width=25,
        )
        self.video_preset_selector.grid(row=1, column=1, pady=(10, 0), sticky="w")
        ttk.Label(
            self.options_frame,
            textvariable=self.video_preset_description,
            wraplength=390,
            style="Muted.TLabel",
        ).grid(row=1, column=2, columnspan=3, pady=(10, 0), sticky="w")
        self.video_preset_selector.bind(
            "<<ComboboxSelected>>", self.apply_selected_video_preset
        )

        for row in range(6, 3, -1):
            for widget in self.grid_slaves(row=row):
                widget.grid_configure(row=row + 1)
        self.video_advanced = ttk.LabelFrame(
            self, text=t("ui.frame.video"), padding=(10, 7)
        )
        self.video_advanced.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(self.video_advanced, text=t("ui.label.resolution")).grid(
            row=0, column=0
        )
        self.video_width_entry = ttk.Entry(
            self.video_advanced, textvariable=self.video_width, width=6
        )
        self.video_width_entry.grid(row=0, column=1, padx=(6, 2))
        ttk.Label(self.video_advanced, text="×").grid(row=0, column=2)
        self.video_height_entry = ttk.Entry(
            self.video_advanced, textvariable=self.video_height, width=6
        )
        self.video_height_entry.grid(row=0, column=3, padx=(2, 14))
        ttk.Label(self.video_advanced, text=t("ui.label.fps_max")).grid(row=0, column=4)
        self.video_fps_entry = ttk.Entry(
            self.video_advanced, textvariable=self.video_fps, width=5
        )
        self.video_fps_entry.grid(row=0, column=5, padx=(6, 14))
        self.video_aspect_selector = ttk.Combobox(
            self.video_advanced,
            textvariable=self.video_aspect,
            values=tuple(self._aspect_by_display),
            state="readonly",
            width=24,
        )
        self.video_aspect_selector.grid(row=0, column=6)

        ttk.Label(self.video_advanced, text=t("ui.label.video_codec")).grid(
            row=1, column=0, pady=(7, 0)
        )
        self.video_codec_selector = ttk.Combobox(
            self.video_advanced,
            textvariable=self.video_codec,
            values=("libx264", "libvpx-vp9", "mpeg4"),
            state="readonly",
            width=12,
        )
        self.video_codec_selector.grid(row=1, column=1, columnspan=2, pady=(7, 0))
        ttk.Label(self.video_advanced, text=t("ui.label.audio_codec")).grid(
            row=1, column=3, pady=(7, 0)
        )
        self.video_audio_selector = ttk.Combobox(
            self.video_advanced,
            textvariable=self.video_audio_codec,
            values=("aac", "libopus", "libmp3lame"),
            state="readonly",
            width=12,
        )
        self.video_audio_selector.grid(row=1, column=4, columnspan=2, pady=(7, 0))
        self.video_audio_check = ttk.Checkbutton(
            self.video_advanced,
            text=t("ui.check.remove_audio"),
            variable=self.video_remove_audio,
            command=self.video_settings_changed,
        )
        self.video_audio_check.grid(row=1, column=6, pady=(7, 0), sticky="w")
        ttk.Label(self.video_advanced, text=t("ui.label.band_color")).grid(
            row=2, column=0, pady=(7, 0)
        )
        self.video_background_entry = ttk.Entry(
            self.video_advanced, textvariable=self.video_background, width=10
        )
        self.video_background_entry.grid(row=2, column=1, columnspan=2, pady=(7, 0))
        ttk.Label(self.video_advanced, text=t("ui.label.max_mb")).grid(
            row=2, column=3, columnspan=2, pady=(7, 0)
        )
        self.video_max_size_entry = ttk.Entry(
            self.video_advanced, textvariable=self.video_max_size, width=7
        )
        self.video_max_size_entry.grid(row=2, column=5, pady=(7, 0))
        ttk.Label(
            self.video_advanced,
            textvariable=self.video_size_guidance,
            wraplength=650,
            style="Muted.TLabel",
        ).grid(row=3, column=0, columnspan=7, pady=(7, 0), sticky="w")

        for variable in (
            self.output_format,
            self.quality,
            self.video_width,
            self.video_height,
            self.video_fps,
            self.video_aspect,
            self.video_codec,
            self.video_audio_codec,
            self.video_background,
            self.video_max_size,
        ):
            variable.trace_add("write", self.video_settings_changed)
        self.output_format.trace_add("write", self.video_format_changed)
        self.apply_video_preset_id(self.settings_store.load_last_video_preset())

    def video_format_changed(self, *_args) -> None:
        if self._applying_video_preset:
            return
        codecs = self.CODECS.get(self.output_format.get())
        if codecs:
            self._applying_video_preset = True
            try:
                self.video_codec.set(codecs[0])
                self.video_audio_codec.set(codecs[1])
            finally:
                self._applying_video_preset = False

    def apply_selected_video_preset(self, _event=None) -> None:
        self.apply_video_preset_id(
            self._video_preset_ids.get(
                self.video_preset_display.get(), CUSTOM_PRESET_ID
            )
        )

    def apply_video_preset_id(self, preset_id: str) -> None:
        preset = preset_by_id(preset_id)
        if (
            preset is None
            or preset.media_category != "video"
            or preset.video_settings is None
        ):
            self.video_preset_display.set(t("ui.preset.custom"))
            self.video_preset_description.set(t("ui.preset.video_manual"))
            selected_id = CUSTOM_PRESET_ID
        else:
            settings = preset.video_settings
            self._applying_video_preset = True
            try:
                self.video_preset_display.set(preset.display_name)
                self.video_preset_description.set(preset.description)
                self.output_format.set(preset.output_format)
                self.quality.set(round((40 - settings.crf) / 0.24))
                self.video_width.set(str(settings.width) if settings.width else "")
                self.video_height.set(str(settings.height) if settings.height else "")
                self.video_fps.set(str(settings.fps_cap) if settings.fps_cap else "")
                label = next(
                    display
                    for display, code in self._aspect_by_display.items()
                    if code == settings.aspect_mode
                )
                self.video_aspect.set(label)
                self.video_codec.set(settings.video_codec)
                self.video_audio_codec.set(settings.audio_codec)
                self.video_remove_audio.set(settings.remove_audio)
                self.video_background.set(settings.background)
                self.video_max_size.set(
                    str(settings.max_size_mb) if settings.max_size_mb else ""
                )
                selected_id = preset.preset_id
            finally:
                self._applying_video_preset = False
        try:
            self.settings_store.save_last_video_preset(selected_id)
        except OSError:
            pass

    def video_settings_changed(self, *_args) -> None:
        if self._applying_video_preset:
            return
        self.video_preset_display.set(t("ui.preset.custom"))
        self.video_preset_description.set(t("ui.preset.video_modified"))
        try:
            self.settings_store.save_last_video_preset(CUSTOM_PRESET_ID)
        except OSError:
            pass

    def current_video_settings(self) -> VideoSettings:
        width_text, height_text = (
            self.video_width.get().strip(),
            self.video_height.get().strip(),
        )
        fps_text = self.video_fps.get().strip()
        max_size_text = self.video_max_size.get().strip()
        return VideoSettings(
            self.video_codec.get(),
            self.video_audio_codec.get(),
            int(width_text) if width_text else None,
            int(height_text) if height_text else None,
            self._aspect_by_display[self.video_aspect.get()],
            int(fps_text) if fps_text else None,
            round(40 - self.quality.get() * 0.24),
            self.video_remove_audio.get(),
            self.video_background.get().strip() or "black",
            "yuv420p",
            self.output_format.get() in {"MP4", "MOV"},
            int(max_size_text) if max_size_text else None,
        )

    def validate_start(self) -> str | None:
        try:
            settings = self.current_video_settings()
            validate_video_settings(self.output_format.get(), settings)
            if settings.max_size_mb is not None and settings.max_size_mb <= 0:
                return t("ui.validate.max_size_positive")
        except (KeyError, ValueError) as error:
            return str(error)
        return None

    def conversion_options(self) -> dict[str, object]:
        options = super().conversion_options()
        options["video_settings"] = self.current_video_settings()
        options["video_preset"] = self._video_preset_ids.get(
            self.video_preset_display.get(), CUSTOM_PRESET_ID
        )
        return options

    def set_busy(self, busy: bool) -> None:
        super().set_busy(busy)
        readonly = "disabled" if busy else "readonly"
        normal = "disabled" if busy else "normal"
        for widget in (
            self.video_preset_selector,
            self.video_aspect_selector,
            self.video_codec_selector,
            self.video_audio_selector,
        ):
            widget.configure(state=readonly)
        for widget in (
            self.video_width_entry,
            self.video_height_entry,
            self.video_fps_entry,
            self.video_background_entry,
            self.video_max_size_entry,
        ):
            widget.configure(state=normal)
        self.video_audio_check.configure(state=normal)

    def convert_batch(
        self,
        source_root: Path,
        files: list[Path],
        output_format: str,
        quality: int,
        initial_errors: list[str] | None = None,
        options: dict[str, object] | None = None,
    ) -> None:
        settings = (options or {}).get("video_settings")
        if not isinstance(settings, VideoSettings):
            codecs = self.CODECS[output_format]
            settings = VideoSettings(
                codecs[0],
                codecs[1],
                None,
                None,
                "preserve",
                None,
                round(40 - quality * 0.24),
                faststart=output_format in {"MP4", "MOV"},
            )
        self.convert_ffmpeg_batch(
            source_root,
            files,
            output_format,
            VIDEO_FORMATS[output_format],
            build_video_args(output_format, settings),
            list(initial_errors or []),
            options,
            False,
            required_encoder=(
                (settings.video_codec,)
                if settings.remove_audio
                else (settings.video_codec, settings.audio_codec)
            ),
        )
