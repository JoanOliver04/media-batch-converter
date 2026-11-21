"""Panel de conversión de imágenes."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from tkinter import BooleanVar, StringVar, Tk, ttk

from PIL import Image, ImageOps, ImageSequence

from animation_handling import (
    MAX_ANIMATION_FRAMES,
    MAX_PRESERVED_FRAME_PIXELS,
    AnimationMode,
    animation_supported,
    animation_too_large,
    existing_directory,
    frame_directory,
    frame_number_width,
    publish_frame_directory,
    webp_frame_durations,
)
from conversion_results import FileResult, FrameResult, ResultStatus, safe_file_size
from error_handling import describe_error
from filename_normalization import path_key
from i18n import t
from image_optimization import (
    MAX_CANDIDATE_PIXELS,
    compact_image,
    exact_palette,
    keep_smaller_candidate,
)
from image_resize import (
    ResizeConfig,
    ResizeMode,
    calculate_resize_dimensions,
    validate_resize_config,
)
from image_validation import (
    open_supported_image,
    oriented_dimensions,
    ImageValidationError,
    ImageWarning,
    ImageWarningCode,
    WarningSeverity,
    output_size_warnings,
    validate_image,
)
from output_policy import (
    OutputAction,
    OutputPlan,
    OutputPlanner,
    OutputPolicy,
    cleanup_temporary,
    commit_output,
    policy_for_name_collision,
)
from presets import CUSTOM_PRESET_ID, IMAGE_PRESETS, preset_by_id, preset_matches
from ui.base import BatchCancelled, ConverterPanel
from ui.formats import (
    IMAGE_EXTENSIONS,
    IMAGE_FORMATS,
    batch_name_collision_keys,
    batch_output_root,
    desired_output_path,
)
from webp_encoding import (
    WebPMode,
    resolve_webp_mode,
    webp_controls_visible,
    webp_save_options,
)

logging.getLogger(__name__).addHandler(logging.NullHandler())


@dataclass(frozen=True, slots=True)
class ImageBatch:
    """Ajustes resueltos una sola vez para todo el lote."""

    source_root: Path
    destination: Path
    planner: OutputPlanner
    image_format: str
    extension: str
    quality: int
    requested_mode: WebPMode | str
    resize_config: ResizeConfig
    policy: OutputPolicy
    normalize: bool
    generate_report: bool
    only_smaller: bool
    animation_policy: AnimationMode
    name_collisions: set[str]


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Propiedades leídas del origen antes de convertirlo."""

    is_animated: bool
    frame_count: int | None
    animation_loop: int | None
    frame_durations: tuple[int, ...]
    width: int
    height: int


@dataclass(slots=True)
class FileContext:
    """Estado mutable de un archivo, necesario para informar de fallos."""

    started: float
    original_bytes: int
    plan: OutputPlan | None = None
    collision: bool = False
    warnings: tuple[ImageWarning | str, ...] = field(default_factory=tuple)


class ImagePanel(ConverterPanel):
    MEDIA_TYPE = "image"
    WEBP_HELP = {
        WebPMode.AUTOMATIC.value: "ui.webp.help.automatic",
        WebPMode.LOSSY.value: "ui.webp.help.lossy",
        WebPMode.LOSSLESS.value: "ui.webp.help.lossless",
    }

    def __init__(self, parent, root: Tk, footer_parent=None) -> None:
        super().__init__(
            parent,
            root,
            t("ui.title.image"),
            IMAGE_EXTENSIONS,
            IMAGE_FORMATS,
            footer_parent,
        )
        self.webp_mode = StringVar(value=WebPMode.AUTOMATIC.value)
        self.animation_mode = StringVar(value=self.settings_store.load_animation_mode())
        self.webp_help = StringVar()
        self.selected_modes: dict[Path, WebPMode] = {}
        self._applying_preset = False
        self.preset_description = StringVar(value=t("ui.preset.manual_description"))
        self.preset_display = StringVar(value=t("ui.preset.custom"))
        self._preset_ids_by_display = {
            preset.display_name: preset.preset_id for preset in IMAGE_PRESETS
        }
        self.resize_mode = StringVar(value=ResizeMode.ORIGINAL.value)
        self.resize_width = StringVar(value="1024")
        self.resize_height = StringVar(value="1024")
        self.resize_percentage = StringVar(value="50")
        self.never_upscale = BooleanVar(value=True)
        self.resize_preview = StringVar(value=t("ui.resize.preview_original"))
        self._resize_modes_by_display = {
            t("ui.resize.mode.original"): ResizeMode.ORIGINAL,
            t("ui.resize.mode.max_width"): ResizeMode.MAX_WIDTH,
            t("ui.resize.mode.max_height"): ResizeMode.MAX_HEIGHT,
            t("ui.resize.mode.fit"): ResizeMode.FIT,
            t("ui.resize.mode.percent"): ResizeMode.PERCENT,
        }

        ttk.Label(self.options_frame, text=t("ui.label.preset")).grid(
            row=1, column=0, padx=(0, 10), pady=(10, 0), sticky="w"
        )
        self.preset_selector = ttk.Combobox(
            self.options_frame,
            textvariable=self.preset_display,
            values=(
                t("ui.preset.custom"),
                *(preset.display_name for preset in IMAGE_PRESETS),
            ),
            state="readonly",
            width=28,
        )
        self.preset_selector.grid(
            row=1, column=1, padx=(0, 16), pady=(10, 0), sticky="w"
        )
        ttk.Label(
            self.options_frame,
            textvariable=self.preset_description,
            wraplength=390,
            style="Muted.TLabel",
        ).grid(row=1, column=2, columnspan=3, pady=(10, 0), sticky="w")
        self.preset_selector.bind("<<ComboboxSelected>>", self.apply_selected_preset)

        self.output_format.trace_add("write", self.settings_changed)
        self.quality.trace_add("write", self.settings_changed)
        self.webp_mode.trace_add("write", self.settings_changed)

        self.webp_frame = ttk.LabelFrame(
            self.encoding_column, text=t("ui.frame.webp"), padding=12
        )
        self.webp_frame.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for column, (text, mode) in enumerate(
            (
                (t("ui.webp.automatic"), WebPMode.AUTOMATIC),
                (t("ui.webp.lossy"), WebPMode.LOSSY),
                (t("ui.webp.lossless"), WebPMode.LOSSLESS),
            )
        ):
            ttk.Radiobutton(
                self.webp_frame,
                text=text,
                value=mode.value,
                variable=self.webp_mode,
                command=self.update_webp_controls,
            ).grid(row=0, column=column, padx=(0, 14), sticky="w")
        ttk.Label(
            self.webp_frame,
            textvariable=self.webp_help,
            wraplength=680,
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 0))
        self.format_selector.bind("<<ComboboxSelected>>", self.update_webp_controls)
        self.resize_box = ttk.LabelFrame(
            self.encoding_column, text=t("ui.frame.resize"), padding=12
        )
        self.resize_box.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(self.resize_box, text=t("ui.label.mode")).grid(
            row=0, column=0, padx=(0, 8)
        )
        self.resize_selector = ttk.Combobox(
            self.resize_box,
            values=tuple(self._resize_modes_by_display),
            state="readonly",
            width=29,
        )
        self.resize_selector.set(t("ui.resize.mode.original"))
        self.resize_selector.grid(row=0, column=1, padx=(0, 14), sticky="w")
        self.label_width = ttk.Label(self.resize_box, text=t("ui.label.width_px"))
        self.entry_width = ttk.Entry(
            self.resize_box, textvariable=self.resize_width, width=9
        )
        self.label_height = ttk.Label(self.resize_box, text=t("ui.label.height_px"))
        self.entry_height = ttk.Entry(
            self.resize_box, textvariable=self.resize_height, width=9
        )
        self.label_percent = ttk.Label(self.resize_box, text=t("ui.label.percent"))
        self.entry_percent = ttk.Entry(
            self.resize_box, textvariable=self.resize_percentage, width=9
        )
        self.never_upscale_check = ttk.Checkbutton(
            self.resize_box,
            text=t("ui.check.never_upscale"),
            variable=self.never_upscale,
        )
        self.never_upscale_check.grid(
            row=2, column=0, columnspan=4, pady=(5, 0), sticky="w"
        )
        ttk.Label(
            self.resize_box,
            textvariable=self.resize_preview,
            wraplength=700,
            style="Muted.TLabel",
        ).grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))
        self.resize_selector.bind("<<ComboboxSelected>>", self.resize_mode_changed)
        for variable in (
            self.resize_width,
            self.resize_height,
            self.resize_percentage,
            self.never_upscale,
        ):
            variable.trace_add("write", self.resize_settings_changed)
        self.update_resize_controls()
        self.apply_preset_id(self.settings_store.load_last_image_preset())
        self.animation_frame = ttk.LabelFrame(
            self.encoding_column, text=t("ui.frame.animation"), padding=12
        )
        self.animation_frame.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        for column, (label, mode) in enumerate(
            (
                (t("ui.animation.preserve"), AnimationMode.PRESERVE),
                (t("ui.animation.extract"), AnimationMode.EXTRACT_FRAMES),
                (t("ui.animation.first_frame"), AnimationMode.FIRST_FRAME),
            )
        ):
            ttk.Radiobutton(
                self.animation_frame,
                text=label,
                value=mode.value,
                variable=self.animation_mode,
                command=self.animation_mode_changed,
            ).grid(row=0, column=column, padx=(0, 16), sticky="w")
        self.animation_help = ttk.Label(
            self.animation_frame,
            text=t("ui.animation.help_global"),
            wraplength=700,
            style="Muted.TLabel",
        )
        self.animation_help.grid(row=1, column=0, columnspan=3, pady=(5, 0), sticky="w")
        self.selection.trace_add("write", self.image_source_changed)
        self.update_animation_controls()

    def image_source_changed(self, *_args) -> None:
        self.update_animation_controls()
        self.update_resize_preview()

    def animation_mode_changed(self) -> None:
        try:
            self.settings_store.save_animation_mode(self.animation_mode.get())
        except OSError:
            pass
        self.update_animation_controls()

    def selected_file_is_animated(self) -> bool:
        selected = self.single_source()
        if selected is None:
            return False
        try:
            with open_supported_image(selected) as image:
                return bool(getattr(image, "is_animated", False) and image.n_frames > 1)
        except (OSError, Image.DecompressionBombError):
            return False

    def update_animation_controls(self) -> None:
        selection = self.selection.get()
        relevant = bool(selection) and (
            len(self.selected_files) > 1
            or Path(selection).is_dir()
            or self.selected_file_is_animated()
        )
        if not relevant:
            self.animation_frame.grid_remove()
            return
        self.animation_frame.grid()
        mode = AnimationMode(self.animation_mode.get())
        if mode is AnimationMode.PRESERVE:
            output_format = IMAGE_FORMATS[self.output_format.get()][0]
            supported = animation_supported(output_format)
            self.animation_help.configure(
                text=(
                    t("ui.animation.help_supported")
                    if supported
                    else t("ui.animation.help_unsupported")
                )
            )
        elif mode is AnimationMode.EXTRACT_FRAMES:
            self.animation_help.configure(text=t("ui.animation.help_extract"))
        else:
            self.animation_help.configure(text=t("ui.animation.help_first_frame"))

    def resize_mode_changed(self, _event=None) -> None:
        self.resize_mode.set(
            self._resize_modes_by_display.get(
                self.resize_selector.get(), ResizeMode.ORIGINAL
            ).value
        )
        self.update_resize_controls()
        self.settings_changed()

    def resize_settings_changed(self, *_args) -> None:
        if hasattr(self, "resize_box"):
            self.update_resize_preview()
            self.settings_changed()

    def current_resize_config(self) -> ResizeConfig:
        def integer_or_none(value: str) -> int | None:
            try:
                return int(value.strip())
            except ValueError:
                return None

        def float_or_none(value: str) -> float | None:
            try:
                return float(value.strip().replace(",", "."))
            except ValueError:
                return None

        return ResizeConfig(
            mode=ResizeMode(self.resize_mode.get()),
            width=integer_or_none(self.resize_width.get()),
            height=integer_or_none(self.resize_height.get()),
            percentage=float_or_none(self.resize_percentage.get()),
            never_upscale=self.never_upscale.get(),
        )

    def update_resize_controls(self) -> None:
        for widget in (
            self.label_width,
            self.entry_width,
            self.label_height,
            self.entry_height,
            self.label_percent,
            self.entry_percent,
        ):
            widget.grid_remove()
        mode = ResizeMode(self.resize_mode.get())
        if mode in {ResizeMode.MAX_WIDTH, ResizeMode.FIT}:
            self.label_width.grid(row=1, column=0, pady=(7, 0), sticky="w")
            self.entry_width.grid(row=1, column=1, pady=(7, 0), sticky="w")
        if mode in {ResizeMode.MAX_HEIGHT, ResizeMode.FIT}:
            self.label_height.grid(
                row=1, column=2, padx=(12, 0), pady=(7, 0), sticky="w"
            )
            self.entry_height.grid(row=1, column=3, pady=(7, 0), sticky="w")
        if mode is ResizeMode.PERCENT:
            self.label_percent.grid(row=1, column=0, pady=(7, 0), sticky="w")
            self.entry_percent.grid(row=1, column=1, pady=(7, 0), sticky="w")
        self.update_resize_preview()

    def update_resize_preview(self) -> None:
        selection = self.selection.get()
        selected = self.single_source()
        if len(self.selected_files) > 1 or (selection and Path(selection).is_dir()):
            self.resize_preview.set(t("ui.resize.preview_batch"))
            return
        if selected is None:
            self.resize_preview.set(t("ui.resize.preview_none"))
            return
        try:
            config = self.current_resize_config()
            validate_resize_config(config)
            with open_supported_image(selected) as image:
                width, height = oriented_dimensions(image)
                target = calculate_resize_dimensions(width, height, config)
                self.resize_preview.set(
                    t(
                        "ui.resize.preview_estimate",
                        width=width,
                        height=height,
                        target_width=target[0],
                        target_height=target[1],
                    )
                )
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            self.resize_preview.set(t("ui.resize.preview_pending", error=error))

    def apply_selected_preset(self, _event=None) -> None:
        preset_id = self._preset_ids_by_display.get(
            self.preset_display.get(), CUSTOM_PRESET_ID
        )
        self.apply_preset_id(preset_id)

    def apply_preset_id(self, preset_id: str) -> None:
        preset = preset_by_id(preset_id)
        self._applying_preset = True
        try:
            if preset is None:
                self.preset_display.set(t("ui.preset.custom"))
                self.preset_description.set(t("ui.preset.manual_description"))
                selected_id = CUSTOM_PRESET_ID
            else:
                self.preset_display.set(preset.display_name)
                self.preset_description.set(preset.description)
                self.output_format.set(preset.output_format)
                if preset.quality is not None:
                    self.quality.set(preset.quality)
                if preset.webp_mode is not None:
                    self.webp_mode.set(preset.webp_mode.value)
                self.resize_mode.set(preset.resize_mode)
                resize_label = next(
                    label
                    for label, mode in self._resize_modes_by_display.items()
                    if mode.value == preset.resize_mode
                )
                self.resize_selector.set(resize_label)
                selected_id = preset.preset_id
        finally:
            self._applying_preset = False
        self.update_webp_controls()
        try:
            self.settings_store.save_last_image_preset(selected_id)
        except OSError:
            pass

    def settings_changed(self, *_args) -> None:
        if self._applying_preset:
            return
        current_id = self._preset_ids_by_display.get(self.preset_display.get())
        current = preset_by_id(current_id)
        if current and preset_matches(
            current,
            self.output_format.get(),
            self.quality.get(),
            self.webp_mode.get(),
            self.resize_mode.get(),
        ):
            return
        self.preset_display.set(t("ui.preset.custom"))
        self.preset_description.set(t("ui.preset.modified_description"))
        try:
            self.settings_store.save_last_image_preset(CUSTOM_PRESET_ID)
        except OSError:
            pass

    def update_webp_controls(self, _event=None) -> None:
        visible = webp_controls_visible(self.output_format.get())
        if visible:
            self.webp_frame.grid()
            self.webp_help.set(t(self.WEBP_HELP[self.webp_mode.get()]))
        else:
            self.webp_frame.grid_remove()
        if hasattr(self, "animation_frame"):
            self.update_animation_controls()
        quality_applies = self.output_format.get() in {"JPG", "AVIF"} or (
            visible and self.webp_mode.get() != WebPMode.LOSSLESS.value
        )
        self.show_quality_controls(quality_applies)
        self.slider.configure(
            state="normal" if quality_applies and not self.busy else "disabled"
        )

    def validate_start(self) -> str | None:
        try:
            validate_resize_config(self.current_resize_config())
        except ValueError as error:
            return str(error)
        if (
            self.selected_file_is_animated()
            and AnimationMode(self.animation_mode.get()) is AnimationMode.PRESERVE
            and not animation_supported(IMAGE_FORMATS[self.output_format.get()][0])
        ):
            return t("ui.validate.animation_unsupported")
        return None

    def conversion_options(self) -> dict[str, object]:
        options = super().conversion_options()
        options["webp_mode"] = self.webp_mode.get()
        options["resize_config"] = self.current_resize_config()
        options["animation_mode"] = self.animation_mode.get()
        return options

    def set_busy(self, busy: bool) -> None:
        super().set_busy(busy)
        self.preset_selector.configure(state="disabled" if busy else "readonly")
        self.resize_selector.configure(state="disabled" if busy else "readonly")
        animation_state = "disabled" if busy else "normal"
        for child in self.animation_frame.winfo_children():
            if isinstance(child, ttk.Radiobutton):
                child.configure(state=animation_state)
        state = "disabled" if busy else "normal"
        for widget in (
            self.entry_width,
            self.entry_height,
            self.entry_percent,
            self.never_upscale_check,
        ):
            widget.configure(state=state)
        self.update_webp_controls()

    @staticmethod
    def prepare_static(
        image: Image.Image,
        image_format: str,
        quality: int,
        source: Path | str = "image.png",
        requested_webp_mode: WebPMode | str = WebPMode.AUTOMATIC,
    ) -> tuple[Image.Image, dict[str, object], WebPMode | None]:
        converted = compact_image(image, image_format)
        save_options: dict[str, object] = {}
        resolved_mode: WebPMode | None = None
        if image_format == "JPEG":
            background = Image.new("RGB", converted.size, "white")
            background.paste(converted, mask=converted.getchannel("A"))
            converted = background
            save_options = {"quality": quality, "optimize": True, "progressive": True}
        elif image_format == "WEBP":
            resolved_mode = resolve_webp_mode(requested_webp_mode, image, source)
            save_options = webp_save_options(resolved_mode, quality)
        elif image_format == "PNG":
            save_options = {"optimize": True, "compress_level": 9}
        elif image_format == "AVIF":
            save_options = {"quality": quality, "speed": 4, "subsampling": "4:4:4"}
        elif image_format == "ICO":
            max_icon_size = min(converted.size)
            sizes = [
                (size, size)
                for size in (16, 24, 32, 48, 64, 128, 256)
                if size <= max_icon_size
            ]
            if sizes:
                save_options = {"sizes": sizes}
        elif image_format == "TIFF":
            save_options = {"compression": "tiff_deflate"}
        elif image_format == "GIF":
            save_options = {"optimize": True}
        return converted, save_options, resolved_mode

    @staticmethod
    def resize_frame(
        image: Image.Image, config: ResizeConfig, target: tuple[int, int] | None = None
    ) -> tuple[Image.Image, tuple[int, int]]:
        oriented = ImageOps.exif_transpose(image)
        target = target or calculate_resize_dimensions(*oriented.size, config)
        if oriented.size == target:
            return oriented, target
        return oriented.resize(target, Image.Resampling.LANCZOS), target

    def save_image(
        self,
        image: Image.Image,
        output: Path,
        image_format: str,
        quality: int,
        source: Path | str | None = None,
        requested_webp_mode: WebPMode | str = WebPMode.AUTOMATIC,
        resize_config: ResizeConfig | None = None,
        animation_durations: tuple[int, ...] = (),
    ) -> WebPMode | None:
        source = source or output
        resize_config = resize_config or ResizeConfig()
        keeps_animation = getattr(image, "is_animated", False) and animation_supported(
            image_format
        )
        if not keeps_animation:
            image.seek(0)
            resized, _target = self.resize_frame(image, resize_config)
            converted, save_options, resolved_mode = self.prepare_static(
                resized, image_format, quality, source, requested_webp_mode
            )
            converted.save(output, format=image_format, **save_options)
            if (
                image_format == "PNG"
                and (palette := exact_palette(converted)) is not None
            ):
                indexed, bits = palette
                keep_smaller_candidate(
                    output,
                    lambda path: indexed.save(
                        path, format="PNG", bits=bits, **save_options
                    ),
                )
            elif (
                image_format == "JPEG"
                and converted.width * converted.height <= MAX_CANDIDATE_PIXELS
            ):
                options = {**save_options, "progressive": False}
                keep_smaller_candidate(
                    output, lambda path: converted.save(path, format="JPEG", **options)
                )
            elif (
                image_format == "TIFF"
                and converted.mode in {"L", "RGB", "RGBA"}
                and converted.width * converted.height <= MAX_CANDIDATE_PIXELS
            ):
                options = {**save_options, "tiffinfo": {317: 2}}
                keep_smaller_candidate(
                    output, lambda path: converted.save(path, format="TIFF", **options)
                )
            elif (
                image_format == "WEBP"
                and WebPMode(requested_webp_mode) is WebPMode.AUTOMATIC
                and resolved_mode is WebPMode.LOSSY
                and converted.width * converted.height <= MAX_CANDIDATE_PIXELS
            ):
                options = webp_save_options(WebPMode.LOSSLESS, quality)
                if keep_smaller_candidate(
                    output, lambda path: converted.save(path, format="WEBP", **options)
                ):
                    resolved_mode = WebPMode.LOSSLESS
            return resolved_mode

        resolved_mode: WebPMode | None = None
        if image_format == "WEBP":
            resolved_mode = resolve_webp_mode(requested_webp_mode, image, source)
        frames: list[Image.Image] = []
        durations: list[int] = []
        target: tuple[int, int] | None = None
        for frame_index, frame in enumerate(ImageSequence.Iterator(image)):
            resized, target = self.resize_frame(
                frame.convert("RGBA"), resize_config, target
            )
            frames.append(resized.convert("RGBA"))
            durations.append(
                animation_durations[frame_index]
                if frame_index < len(animation_durations)
                else frame.info.get("duration", image.info.get("duration", 100))
            )

        save_options: dict[str, object] = {
            "save_all": True,
            "append_images": frames[1:],
            "duration": durations,
            "loop": image.info.get("loop", 0),
        }
        if image_format in {"GIF", "PNG"}:
            save_options["disposal"] = [
                getattr(frame, "disposal_method", frame.info.get("disposal", 0))
                for frame in ImageSequence.Iterator(image)
            ]
        if image_format == "WEBP":
            save_options.update(webp_save_options(resolved_mode, quality))
        elif image_format == "AVIF":
            save_options.update(quality=quality, speed=4, subsampling="4:4:4")
        else:
            save_options["optimize"] = True
        frames[0].save(output, format=image_format, **save_options)
        return resolved_mode

    @staticmethod
    def animation_warning(
        code: ImageWarningCode,
        severity: WarningSeverity,
        message: str,
        source: Path,
        **details,
    ) -> ImageWarning:
        return ImageWarning(code, severity, message, source, details)

    def extract_animation_frames(
        self,
        image: Image.Image,
        source: Path,
        directory: Path,
        image_format: str,
        extension: str,
        quality: int,
        requested_mode: WebPMode | str,
        resize_config: ResizeConfig,
        generate_report: bool,
        animation_durations: tuple[int, ...],
    ) -> tuple[Path, tuple[FrameResult, ...], tuple[str, ...], WebPMode | None]:
        frame_results: list[FrameResult] = []
        checksum_warnings: list[str] = []
        target_size: tuple[int, int] | None = None
        resolved_mode = (
            resolve_webp_mode(requested_mode, image, source)
            if image_format == "WEBP"
            else None
        )
        width = frame_number_width(image.n_frames)
        for index, frame in enumerate(ImageSequence.Iterator(image)):
            if self.cancel_event.is_set():
                raise InterruptedError(t("ui.error.frame_extraction_cancelled"))
            duration = (
                animation_durations[index]
                if index < len(animation_durations)
                else int(frame.info.get("duration", 100))
            )
            resized, target_size = self.resize_frame(
                frame.convert("RGBA"), resize_config, target_size
            )
            output = directory / f"frame_{index + 1:0{width}d}{extension}"
            self.save_image(
                resized,
                output,
                image_format,
                quality,
                source,
                resolved_mode or requested_mode,
                ResizeConfig(),
            )
            checksum, warnings_found = self.checksum_for_report(output, generate_report)
            checksum_warnings.extend(warnings_found)
            frame_results.append(
                FrameResult(output, duration, safe_file_size(output), checksum)
            )
        return directory, tuple(frame_results), tuple(checksum_warnings), resolved_mode

    def convert_batch(
        self,
        source_root: Path,
        files: list[Path],
        chosen: str,
        quality: int,
        initial_errors: list[str] | None = None,
        options: dict[str, object] | None = None,
    ) -> None:
        batch = self._plan_batch(source_root, files, chosen, quality, options)
        discovery_errors = list(initial_errors or [])
        results: list[FileResult] = []
        self.selected_modes = {}

        for index, file in enumerate(files, 1):
            if self.cancel_event.is_set():
                self._finish(batch, results, discovery_errors, cancelled=True)
                return
            self.root.after(
                0,
                self.status.set,
                t(
                    "ui.status.converting",
                    index=index,
                    total=len(files),
                    name=file.name,
                ),
            )
            try:
                results.append(self._convert_file(batch, file))
            except BatchCancelled:
                self._finish(batch, results, discovery_errors, cancelled=True)
                return
            self.report_progress(index, len(files), file.name)
        self.root.after(0, self.status.set, t("ui.status.finalizing"))
        self._finish(
            batch, results, discovery_errors, cancelled=self.cancel_event.is_set()
        )

    def _plan_batch(
        self,
        source_root: Path,
        files: list[Path],
        chosen: str,
        quality: int,
        options: dict[str, object] | None,
    ) -> ImageBatch:
        options = options or {}
        image_format, extension = IMAGE_FORMATS[chosen]
        destination = batch_output_root(source_root, chosen, options)
        normalize = bool(options.get("normalize_filenames", False))
        return ImageBatch(
            source_root=source_root,
            destination=destination,
            planner=OutputPlanner(),
            image_format=image_format,
            extension=extension,
            quality=quality,
            requested_mode=options.get("webp_mode", WebPMode.AUTOMATIC.value),
            resize_config=options.get("resize_config", ResizeConfig()),
            policy=OutputPolicy(options.get("output_policy", OutputPolicy.SKIP)),
            normalize=normalize,
            generate_report=bool(options.get("generate_report", False)),
            only_smaller=bool(options.get("only_smaller", False)),
            animation_policy=AnimationMode(
                options.get("animation_mode", AnimationMode.PRESERVE)
            ),
            name_collisions=batch_name_collision_keys(
                destination, source_root, files, extension, normalize
            ),
        )

    def _finish(
        self,
        batch: ImageBatch,
        results: list[FileResult],
        discovery_errors: list[str],
        cancelled: bool,
    ) -> None:
        batch.planner.prune_empty_directories()
        self.root.after(
            0,
            self.finish_results,
            batch.destination,
            results,
            discovery_errors,
            cancelled,
        )

    def _convert_file(self, batch: ImageBatch, file: Path) -> FileResult:
        context = FileContext(
            started=time.monotonic(), original_bytes=safe_file_size(file)
        )
        try:
            return self._run_conversion(batch, file, context)
        except Exception as error:
            logging.getLogger(__name__).exception("conversion_failed source=%s", file)
            cleanup_temporary(context.plan)
            if isinstance(error, ImageValidationError):
                context.warnings = error.warnings
            if self.cancel_event.is_set():
                raise BatchCancelled from error
            return FileResult(
                file,
                None,
                ResultStatus.FAILED,
                context.original_bytes,
                error_message=describe_error(error).message,
                processing_seconds=time.monotonic() - context.started,
                name_collision=context.collision,
                warnings=context.warnings,
            )

    def _run_conversion(
        self, batch: ImageBatch, file: Path, context: FileContext
    ) -> FileResult:
        desired = desired_output_path(
            batch.destination, batch.source_root, file, batch.extension, batch.normalize
        )
        context.collision = path_key(desired) in batch.name_collisions
        context.warnings = tuple(validate_image(file, batch.image_format))
        if [warning for warning in context.warnings if warning.blocking]:
            raise ImageValidationError(list(context.warnings))

        metadata = self._read_source_metadata(file)
        if animation_too_large(metadata.frame_count) and (
            batch.animation_policy is AnimationMode.PRESERVE
            or batch.animation_policy is AnimationMode.EXTRACT_FRAMES
        ):
            too_many = self.animation_warning(
                ImageWarningCode.ANIMATION_TOO_MANY_FRAMES,
                WarningSeverity.BLOCKING_ERROR,
                t("ui.warning.animation_too_many_frames", limit=MAX_ANIMATION_FRAMES),
                file,
                frameCount=metadata.frame_count,
                limit=MAX_ANIMATION_FRAMES,
            )
            raise ImageValidationError([*context.warnings, too_many])
        if metadata.is_animated and batch.animation_policy is AnimationMode.PRESERVE:
            width, height = calculate_resize_dimensions(
                metadata.width, metadata.height, batch.resize_config
            )
            if (
                width * height * (metadata.frame_count or 1)
                > MAX_PRESERVED_FRAME_PIXELS
            ):
                over_budget = self.animation_warning(
                    ImageWarningCode.ANIMATION_MEMORY_LIMIT,
                    WarningSeverity.BLOCKING_ERROR,
                    t("ui.warning.animation_memory_limit"),
                    file,
                )
                raise ImageValidationError([*context.warnings, over_budget])
        if (
            metadata.is_animated
            and batch.animation_policy is not AnimationMode.PRESERVE
        ):
            context.warnings = tuple(
                warning
                for warning in context.warnings
                if not isinstance(warning, ImageWarning)
                or warning.code is not ImageWarningCode.ANIMATION_MAY_BE_LOST
            )

        if (
            metadata.is_animated
            and batch.animation_policy is AnimationMode.EXTRACT_FRAMES
        ):
            batch.planner.ensure_directory(desired.parent)
            return self._convert_extracted_frames(
                batch, file, desired, metadata, context
            )

        if (
            metadata.is_animated
            and batch.animation_policy is AnimationMode.PRESERVE
            and not animation_supported(batch.image_format)
        ):
            unsupported = self.animation_warning(
                ImageWarningCode.ANIMATED_DESTINATION_UNSUPPORTED,
                WarningSeverity.BLOCKING_ERROR,
                t("ui.warning.animated_destination_unsupported"),
                file,
                targetFormat=batch.image_format,
            )
            raise ImageValidationError([*context.warnings, unsupported])

        context.plan = batch.planner.plan(
            file, desired, policy_for_name_collision(batch.policy, context.collision)
        )
        if not context.plan.should_convert:
            return FileResult(
                file,
                context.plan.target,
                ResultStatus.SKIPPED,
                context.original_bytes,
                error_message=(
                    t("ui.skip.exists")
                    if context.plan.action is OutputAction.SKIP_EXISTS
                    else t("ui.skip.up_to_date")
                ),
                processing_seconds=time.monotonic() - context.started,
                output_action=context.plan.action.value,
                name_collision=context.collision,
                warnings=context.warnings,
            )
        return self._convert_single_output(batch, file, metadata, context)

    @staticmethod
    def _read_source_metadata(file: Path) -> SourceMetadata:
        with open_supported_image(file) as probe:
            is_animated = bool(
                getattr(probe, "is_animated", False) and probe.n_frames > 1
            )
            frame_count = probe.n_frames if is_animated else None
            animation_loop = int(probe.info.get("loop", 0)) if is_animated else None
            frame_durations = (
                tuple(
                    int(frame.info.get("duration", probe.info.get("duration", 100)))
                    for frame in ImageSequence.Iterator(probe)
                )
                if is_animated and not animation_too_large(frame_count)
                else ()
            )
            probe.seek(0)
            width, height = oriented_dimensions(probe)
            probe_format = probe.format
        if (
            is_animated
            and probe_format == "WEBP"
            and not animation_too_large(frame_count)
        ):
            parsed_durations = webp_frame_durations(file)
            if len(parsed_durations) == frame_count:
                frame_durations = parsed_durations
        return SourceMetadata(
            is_animated=is_animated,
            frame_count=frame_count,
            animation_loop=animation_loop,
            frame_durations=frame_durations,
            width=width,
            height=height,
        )

    def _convert_extracted_frames(
        self,
        batch: ImageBatch,
        file: Path,
        desired: Path,
        metadata: SourceMetadata,
        context: FileContext,
    ) -> FileResult:
        desired_dir = desired.with_name(f"{desired.stem}_frames")
        policy = policy_for_name_collision(batch.policy, context.collision)
        existing = existing_directory(desired_dir)
        if existing is not None and policy is OutputPolicy.SKIP:
            return FileResult(
                file,
                existing,
                ResultStatus.SKIPPED,
                context.original_bytes,
                error_message=t("ui.skip.exists"),
                processing_seconds=time.monotonic() - context.started,
                output_action=OutputAction.SKIP_EXISTS.value,
                name_collision=context.collision,
                warnings=context.warnings,
                animation_mode=batch.animation_policy.value,
            )
        if existing is not None and policy is OutputPolicy.SOURCE_NEWER:
            try:
                newest = max(
                    child.stat().st_mtime_ns
                    for child in existing.iterdir()
                    if not child.is_symlink() and child.is_file()
                )
            except ValueError:
                newest = existing.stat().st_mtime_ns
            if file.stat().st_mtime_ns <= newest:
                return FileResult(
                    file,
                    existing,
                    ResultStatus.SKIPPED,
                    context.original_bytes,
                    error_message=t("ui.skip.up_to_date"),
                    processing_seconds=time.monotonic() - context.started,
                    output_action=OutputAction.SKIP_UP_TO_DATE.value,
                    name_collision=context.collision,
                    warnings=context.warnings,
                    animation_mode=batch.animation_policy.value,
                )
        overwrite = existing is not None and policy in {
            OutputPolicy.OVERWRITE,
            OutputPolicy.SOURCE_NEWER,
        }
        frame_root = existing if overwrite else frame_directory(desired_dir)
        with TemporaryDirectory(prefix=".frame-export-", dir=desired.parent) as stage:
            staged = Path(stage) / "frames"
            staged.mkdir()
            with open_supported_image(file) as animation:
                _, frames, checksum_warnings, resolved_mode = (
                    self.extract_animation_frames(
                        animation,
                        file,
                        staged,
                        batch.image_format,
                        batch.extension,
                        batch.quality,
                        batch.requested_mode,
                        batch.resize_config,
                        batch.generate_report,
                        metadata.frame_durations,
                    )
                )
            if self.cancel_event.is_set():
                raise BatchCancelled()
            output_bytes = sum(frame.output_bytes for frame in frames)
            if batch.only_smaller and output_bytes >= context.original_bytes:
                return FileResult(
                    file,
                    None,
                    ResultStatus.CONVERTED,
                    context.original_bytes,
                    output_bytes,
                    processing_seconds=time.monotonic() - context.started,
                    name_collision=context.collision,
                    warnings=context.warnings,
                    animation_mode=batch.animation_policy.value,
                ).require_savings(True)
            publish_frame_directory(staged, frame_root, overwrite)
        frames = tuple(
            FrameResult(
                frame_root / frame.output_path.name,
                frame.duration_ms,
                frame.output_bytes,
                frame.sha256,
            )
            for frame in frames
        )
        output_width, output_height = calculate_resize_dimensions(
            metadata.width, metadata.height, batch.resize_config
        )
        extraction_warning = self.animation_warning(
            ImageWarningCode.FRAMES_EXTRACTED,
            WarningSeverity.INFORMATION,
            t("ui.warning.frames_extracted", count=len(frames)),
            file,
            frameCount=len(frames),
            durationsMs=[frame.duration_ms for frame in frames],
        )
        size_warnings = tuple(
            output_size_warnings(file, context.original_bytes, output_bytes)
        )
        return FileResult(
            file,
            frame_root,
            ResultStatus.CONVERTED,
            context.original_bytes,
            output_bytes,
            processing_seconds=time.monotonic() - context.started,
            encoder_mode=resolved_mode.value if resolved_mode else None,
            output_action=(
                OutputAction.OVERWRITE.value
                if overwrite
                else (
                    OutputAction.RENAME.value
                    if frame_root != desired_dir
                    else OutputAction.CONVERT.value
                )
            ),
            name_collision=context.collision,
            warnings=context.warnings
            + (extraction_warning,)
            + size_warnings
            + checksum_warnings,
            width=metadata.width,
            height=metadata.height,
            output_width=output_width,
            output_height=output_height,
            quality=None if resolved_mode is WebPMode.LOSSLESS else batch.quality,
            animation_mode=batch.animation_policy.value,
            frame_count=metadata.frame_count,
            animation_loop=metadata.animation_loop,
            frame_durations_ms=metadata.frame_durations,
            frames=frames,
        )

    def _convert_single_output(
        self,
        batch: ImageBatch,
        file: Path,
        metadata: SourceMetadata,
        context: FileContext,
    ) -> FileResult:
        first_frame_only = (
            metadata.is_animated and batch.animation_policy is AnimationMode.FIRST_FRAME
        )
        if first_frame_only:
            context.warnings += (
                self.animation_warning(
                    ImageWarningCode.ANIMATION_INTENTIONALLY_DISCARDED,
                    WarningSeverity.WARNING,
                    t("ui.warning.first_frame_only"),
                    file,
                    discardedFrames=(metadata.frame_count or 1) - 1,
                ),
            )

        with open_supported_image(file) as image:
            source_width, source_height = oriented_dimensions(image)
            output_width, output_height = calculate_resize_dimensions(
                source_width, source_height, batch.resize_config
            )
            image_to_save = image
            if first_frame_only:
                image.seek(0)
                image_to_save = image.convert("RGBA")
            resolved_mode = self.save_image(
                image_to_save,
                context.plan.temporary,
                batch.image_format,
                batch.quality,
                file,
                batch.requested_mode,
                batch.resize_config,
                metadata.frame_durations,
            )
        if self.cancel_event.is_set():
            raise BatchCancelled()
        output_bytes = context.plan.temporary.stat().st_size
        size_warnings = tuple(
            output_size_warnings(file, context.original_bytes, output_bytes)
        )
        reported_quality = None
        if batch.image_format in {"JPEG", "AVIF"} or resolved_mode is WebPMode.LOSSY:
            reported_quality = batch.quality
        result = FileResult(
            file,
            context.plan.target,
            ResultStatus.CONVERTED,
            context.original_bytes,
            output_bytes,
            processing_seconds=time.monotonic() - context.started,
            encoder_mode=resolved_mode.value if resolved_mode else None,
            output_action=context.plan.action.value,
            name_collision=context.collision,
            warnings=context.warnings + size_warnings,
            width=source_width,
            height=source_height,
            output_width=output_width,
            output_height=output_height,
            quality=reported_quality,
            animation_mode=(
                batch.animation_policy.value if metadata.is_animated else None
            ),
            frame_count=metadata.frame_count,
            animation_loop=metadata.animation_loop,
            frame_durations_ms=metadata.frame_durations,
        ).require_savings(batch.only_smaller)
        if result.status is ResultStatus.SKIPPED:
            cleanup_temporary(context.plan)
            return result
        commit_output(context.plan)
        checksum, checksum_warnings = self.checksum_for_report(
            context.plan.target, batch.generate_report
        )
        if resolved_mode is not None:
            self.selected_modes[file] = resolved_mode
        return replace(
            result, sha256=checksum, warnings=result.warnings + checksum_warnings
        )
