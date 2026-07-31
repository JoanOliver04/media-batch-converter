"""Panel de conversión de imágenes."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, ttk

from PIL import Image, ImageOps, ImageSequence

from animation_handling import (
    AnimationMode,
    animation_supported,
    frame_directory,
    frame_number_width,
    webp_frame_durations,
)
from conversion_results import FileResult, FrameResult, ResultStatus, safe_file_size
from error_handling import describe_error
from filename_normalization import path_key
from i18n import t
from image_resize import (
    ResizeConfig,
    ResizeMode,
    calculate_resize_dimensions,
    validate_resize_config,
)
from image_validation import (
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
    OutputPolicy,
    cleanup_temporary,
    commit_output,
    plan_output,
)
from presets import CUSTOM_PRESET_ID, IMAGE_PRESETS, preset_by_id, preset_matches
from ui.base import BatchCancelled, ConverterPanel
from ui.formats import (
    IMAGE_EXTENSIONS,
    IMAGE_FORMATS,
    batch_name_collision_keys,
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
    image_format: str
    extension: str
    quality: int
    requested_mode: WebPMode | str
    resize_config: ResizeConfig
    policy: OutputPolicy
    normalize: bool
    generate_report: bool
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

    def __init__(self, parent, root: Tk) -> None:
        super().__init__(
            parent, root, t("ui.title.image"), IMAGE_EXTENSIONS, IMAGE_FORMATS
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
            self.options_frame, textvariable=self.preset_description, wraplength=390
        ).grid(row=1, column=2, columnspan=3, pady=(10, 0), sticky="w")
        self.preset_selector.bind("<<ComboboxSelected>>", self.apply_selected_preset)

        self.output_format.trace_add("write", self.settings_changed)
        self.quality.trace_add("write", self.settings_changed)
        self.webp_mode.trace_add("write", self.settings_changed)
        for row in range(6, 3, -1):
            for widget in self.grid_slaves(row=row):
                widget.grid_configure(row=row + 1)

        self.webp_frame = ttk.LabelFrame(self, text=t("ui.frame.webp"), padding=(10, 6))
        self.webp_frame.grid(row=4, column=0, sticky="ew", pady=(0, 12))
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
        ttk.Label(self.webp_frame, textvariable=self.webp_help, wraplength=680).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(5, 0)
        )
        self.format_selector.bind("<<ComboboxSelected>>", self.update_webp_controls)
        for row in range(7, 4, -1):
            for widget in self.grid_slaves(row=row):
                widget.grid_configure(row=row + 1)
        self.resize_box = ttk.LabelFrame(
            self, text=t("ui.frame.resize"), padding=(10, 7)
        )
        self.resize_box.grid(row=5, column=0, sticky="ew", pady=(0, 12))
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
        self.never_upscale_check.grid(row=1, column=4, padx=(12, 0), sticky="w")
        ttk.Label(
            self.resize_box, textvariable=self.resize_preview, wraplength=700
        ).grid(row=2, column=0, columnspan=6, sticky="w", pady=(6, 0))
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
        for row in range(8, 5, -1):
            for widget in self.grid_slaves(row=row):
                widget.grid_configure(row=row + 1)
        self.animation_frame = ttk.LabelFrame(
            self, text=t("ui.frame.animation"), padding=(10, 7)
        )
        self.animation_frame.grid(row=6, column=0, sticky="ew", pady=(0, 12))
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
        )
        self.animation_help.grid(row=1, column=0, columnspan=3, pady=(5, 0), sticky="w")
        self.update_animation_controls()

    def animation_mode_changed(self) -> None:
        try:
            self.settings_store.save_animation_mode(self.animation_mode.get())
        except OSError:
            pass
        self.update_animation_controls()

    def selected_file_is_animated(self) -> bool:
        selected = Path(self.selection.get())
        if not selected.is_file():
            return False
        try:
            with Image.open(selected) as image:
                return bool(getattr(image, "is_animated", False) and image.n_frames > 1)
        except OSError:
            return False

    def update_animation_controls(self) -> None:
        selected = Path(self.selection.get())
        relevant = selected.is_dir() or self.selected_file_is_animated()
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
        selected = Path(self.selection.get())
        if selected.is_dir():
            self.resize_preview.set(t("ui.resize.preview_batch"))
            return
        if not selected.is_file():
            self.resize_preview.set(t("ui.resize.preview_none"))
            return
        try:
            config = self.current_resize_config()
            validate_resize_config(config)
            with Image.open(selected) as image:
                oriented = ImageOps.exif_transpose(image)
                target = calculate_resize_dimensions(*oriented.size, config)
                self.resize_preview.set(
                    t(
                        "ui.resize.preview_estimate",
                        width=oriented.width,
                        height=oriented.height,
                        target_width=target[0],
                        target_height=target[1],
                    )
                )
        except (OSError, ValueError) as error:
            self.resize_preview.set(t("ui.resize.preview_pending", error=error))

    def select_file(self) -> None:
        super().select_file()
        self.update_resize_preview()

    def select_folder(self) -> None:
        super().select_folder()
        self.update_resize_preview()

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
        quality_applies = not (
            visible and self.webp_mode.get() == WebPMode.LOSSLESS.value
        )
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
        converted = image.convert("RGBA")
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
        desired_output: Path,
        image_format: str,
        extension: str,
        quality: int,
        requested_mode: WebPMode | str,
        resize_config: ResizeConfig,
        generate_report: bool,
        animation_durations: tuple[int, ...],
    ) -> tuple[Path, tuple[FrameResult, ...], tuple[str, ...], WebPMode | None]:
        directory = frame_directory(
            desired_output.with_name(f"{desired_output.stem}_frames")
        )
        directory.mkdir(parents=True, exist_ok=False)
        created: list[Path] = []
        frame_results: list[FrameResult] = []
        checksum_warnings: list[str] = []
        target_size: tuple[int, int] | None = None
        resolved_mode = (
            resolve_webp_mode(requested_mode, image, source)
            if image_format == "WEBP"
            else None
        )
        width = frame_number_width(image.n_frames)
        try:
            for index, frame in enumerate(ImageSequence.Iterator(image), 1):
                if self.cancel_event.is_set():
                    raise InterruptedError(t("ui.error.frame_extraction_cancelled"))
                duration = int(
                    frame.info.get("duration", image.info.get("duration", 100))
                )
                resized, target_size = self.resize_frame(
                    frame.convert("RGBA"), resize_config, target_size
                )
                output = directory / f"frame_{index:0{width}d}{extension}"
                plan = plan_output(source, output, OutputPolicy.OVERWRITE)
                try:
                    self.save_image(
                        resized,
                        plan.temporary,
                        image_format,
                        quality,
                        source,
                        resolved_mode or requested_mode,
                        ResizeConfig(),
                    )
                    commit_output(plan)
                except Exception:
                    cleanup_temporary(plan)
                    raise
                created.append(output)
                checksum, warnings_found = self.checksum_for_report(
                    output, generate_report
                )
                checksum_warnings.extend(warnings_found)
                frame_results.append(
                    FrameResult(output, duration, safe_file_size(output), checksum)
                )
        except Exception:
            for output in created:
                output.unlink(missing_ok=True)
            directory.rmdir()
            raise
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
                f"Convirtiendo {index}/{len(files)}: {file.name}",
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
        destination = source_root / f"convertidos_{chosen.lower()}"
        normalize = bool(options.get("normalize_filenames", False))
        return ImageBatch(
            source_root=source_root,
            destination=destination,
            image_format=image_format,
            extension=extension,
            quality=quality,
            requested_mode=options.get("webp_mode", WebPMode.AUTOMATIC.value),
            resize_config=options.get("resize_config", ResizeConfig()),
            policy=OutputPolicy(options.get("output_policy", OutputPolicy.SKIP)),
            normalize=normalize,
            generate_report=bool(options.get("generate_report", False)),
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
            if isinstance(error, InterruptedError) and self.cancel_event.is_set():
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
        desired.parent.mkdir(parents=True, exist_ok=True)
        context.collision = path_key(desired) in batch.name_collisions
        context.warnings = tuple(validate_image(file, batch.image_format))
        if [warning for warning in context.warnings if warning.blocking]:
            raise ImageValidationError(list(context.warnings))

        metadata = self._read_source_metadata(file)
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

        context.plan = plan_output(file, desired, batch.policy)
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
        with Image.open(file) as probe:
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
                if is_animated
                else ()
            )
            width, height = probe.size
            probe_format = probe.format
        if is_animated and probe_format == "WEBP":
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
        with Image.open(file) as animation:
            frame_root, frames, checksum_warnings, resolved_mode = (
                self.extract_animation_frames(
                    animation,
                    file,
                    desired,
                    batch.image_format,
                    batch.extension,
                    batch.quality,
                    batch.requested_mode,
                    batch.resize_config,
                    batch.generate_report,
                    metadata.frame_durations,
                )
            )
        output_bytes = sum(frame.output_bytes for frame in frames)
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
                OutputAction.RENAME.value
                if frame_root.name != f"{desired.stem}_frames"
                else OutputAction.CONVERT.value
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

        with Image.open(file) as image:
            oriented = ImageOps.exif_transpose(image)
            source_width, source_height = oriented.size
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
        commit_output(context.plan)
        output_bytes = safe_file_size(context.plan.target)
        size_warnings = tuple(
            output_size_warnings(file, context.original_bytes, output_bytes)
        )
        checksum, checksum_warnings = self.checksum_for_report(
            context.plan.target, batch.generate_report
        )
        if resolved_mode is not None:
            self.selected_modes[file] = resolved_mode
        reported_quality = (
            None
            if batch.image_format == "WEBP" and resolved_mode is WebPMode.LOSSLESS
            else batch.quality
        )
        return FileResult(
            file,
            context.plan.target,
            ResultStatus.CONVERTED,
            context.original_bytes,
            output_bytes,
            processing_seconds=time.monotonic() - context.started,
            encoder_mode=resolved_mode.value if resolved_mode else None,
            output_action=context.plan.action.value,
            name_collision=context.collision,
            warnings=context.warnings + size_warnings + checksum_warnings,
            width=source_width,
            height=source_height,
            output_width=output_width,
            output_height=output_height,
            quality=reported_quality,
            sha256=checksum,
            animation_mode=(
                batch.animation_policy.value if metadata.is_animated else None
            ),
            frame_count=metadata.frame_count,
            animation_loop=metadata.animation_loop,
            frame_durations_ms=metadata.frame_durations,
        )
