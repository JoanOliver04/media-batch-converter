"""Panel de conversión de documentos y hojas de cálculo."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, ttk

from batch_processing import remove_if_empty
from conversion_results import FileResult, ResultStatus, safe_file_size
from documents.conversion import convert_document
from documents.errors import DocumentError
from documents.formats import (
    DOCUMENT_EXTENSIONS,
    DOCUMENT_FORMATS,
    conversion_supported,
    format_from_path,
)
from documents.libreoffice import resolve_libreoffice
from documents.settings import DocumentSettings, validate_document_settings
from error_handling import describe_error
from filename_normalization import path_key
from i18n import t
from output_policy import (
    OutputAction,
    OutputPlan,
    OutputPolicy,
    cleanup_temporary,
    commit_output,
    plan_output,
    policy_for_name_collision,
)
from presets import (
    CUSTOM_PRESET_ID,
    DOCUMENT_PRESETS,
    document_preset_matches,
    preset_by_id,
)
from ui.base import BatchCancelled, ConverterPanel
from ui.formats import batch_name_collision_keys, desired_output_path

logging.getLogger(__name__).addHandler(logging.NullHandler())


@dataclass(frozen=True, slots=True)
class DocumentBatch:
    source_root: Path
    destination: Path
    extension: str
    output_format: str
    settings: DocumentSettings
    policy: OutputPolicy
    normalize: bool
    generate_report: bool
    name_collisions: set[str]


class DocumentPanel(ConverterPanel):
    MEDIA_TYPE = "document"
    NAME_EXAMPLE_KEY = "ui.output_name.example.document"
    ENGINES = (
        ("ui.document.engine.automatic", "automatic"),
        ("ui.document.engine.builtin", "builtin"),
        ("ui.document.engine.libreoffice", "libreoffice"),
    )
    PAGE_SIZES = (
        ("ui.document.page.a4", "a4"),
        ("ui.document.page.letter", "letter"),
    )
    ENGINE_HELP = {
        "automatic": "ui.document.help.automatic",
        "builtin": "ui.document.help.builtin",
        "libreoffice": "ui.document.help.libreoffice",
    }

    def __init__(self, parent, root: Tk) -> None:
        super().__init__(
            parent, root, t("ui.title.document"), DOCUMENT_EXTENSIONS, DOCUMENT_FORMATS
        )
        self._hide_quality_controls()
        self._applying_preset = False
        self.preset_display = StringVar(value=t("ui.preset.custom"))
        self.preset_description = StringVar(value=t("ui.preset.document_manual"))
        self._preset_ids = {
            preset.display_name: preset.preset_id for preset in DOCUMENT_PRESETS
        }
        self._engine_by_display = {t(key): code for key, code in self.ENGINES}
        self._page_by_display = {t(key): code for key, code in self.PAGE_SIZES}
        self.document_engine = StringVar(value=t("ui.document.engine.automatic"))
        self.document_page_size = StringVar(value=t("ui.document.page.a4"))
        self.page_markers = BooleanVar(value=True)
        self.engine_help = StringVar(value=t("ui.document.help.automatic"))
        office = resolve_libreoffice()
        self.office_status = StringVar(
            value=(
                t("ui.document.libreoffice_ready", version=office.version)
                if office
                else t("ui.document.libreoffice_missing")
            )
        )

        ttk.Label(self.options_frame, text=t("ui.label.document_preset")).grid(
            row=1, column=0, padx=(0, 10), pady=(10, 0), sticky="w"
        )
        self.preset_selector = ttk.Combobox(
            self.options_frame,
            textvariable=self.preset_display,
            values=(
                t("ui.preset.custom"),
                *(preset.display_name for preset in DOCUMENT_PRESETS),
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

        for row in range(6, 3, -1):
            for widget in self.grid_slaves(row=row):
                widget.grid_configure(row=row + 1)
        self.document_advanced = ttk.LabelFrame(
            self, text=t("ui.frame.document"), padding=(10, 7)
        )
        self.document_advanced.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(self.document_advanced, text=t("ui.label.engine")).grid(
            row=0, column=0
        )
        self.engine_selector = ttk.Combobox(
            self.document_advanced,
            textvariable=self.document_engine,
            values=tuple(self._engine_by_display),
            state="readonly",
            width=16,
        )
        self.engine_selector.grid(row=0, column=1, padx=(8, 20))
        ttk.Label(self.document_advanced, text=t("ui.label.page_size")).grid(
            row=0, column=2
        )
        self.page_selector = ttk.Combobox(
            self.document_advanced,
            textvariable=self.document_page_size,
            values=tuple(self._page_by_display),
            state="readonly",
            width=12,
        )
        self.page_selector.grid(row=0, column=3, padx=(8, 20))
        self.page_markers_check = ttk.Checkbutton(
            self.document_advanced,
            text=t("ui.check.page_markers"),
            variable=self.page_markers,
            command=self.document_settings_changed,
        )
        self.page_markers_check.grid(row=0, column=4, sticky="w")
        ttk.Label(
            self.document_advanced,
            textvariable=self.engine_help,
            wraplength=820,
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=5, pady=(8, 0), sticky="w")
        ttk.Label(
            self.document_advanced,
            textvariable=self.office_status,
            wraplength=820,
            style="Muted.TLabel",
        ).grid(row=2, column=0, columnspan=5, pady=(4, 0), sticky="w")

        self.engine_selector.bind("<<ComboboxSelected>>", self.engine_changed)
        for variable in (self.output_format, self.document_page_size):
            variable.trace_add("write", self.document_settings_changed)
        self.apply_document_preset_id(self.settings_store.load_last_document_preset())

    def _hide_quality_controls(self) -> None:
        for widget in self.options_frame.grid_slaves(row=0):
            column = int(widget.grid_info()["column"])
            if column >= 2:
                widget.grid_remove()

    def apply_selected_preset(self, _event=None) -> None:
        self.apply_document_preset_id(
            self._preset_ids.get(self.preset_display.get(), CUSTOM_PRESET_ID)
        )

    def apply_document_preset_id(self, preset_id: str) -> None:
        preset = preset_by_id(preset_id)
        if (
            preset is None
            or preset.media_category != "document"
            or preset.document_settings is None
        ):
            self.preset_display.set(t("ui.preset.custom"))
            self.preset_description.set(t("ui.preset.document_manual"))
            selected_id = CUSTOM_PRESET_ID
        else:
            settings = preset.document_settings
            self._applying_preset = True
            try:
                self.preset_display.set(preset.display_name)
                self.preset_description.set(preset.description)
                self.output_format.set(preset.output_format)
                self.document_engine.set(
                    self._display_for(self._engine_by_display, settings.engine)
                )
                self.document_page_size.set(
                    self._display_for(self._page_by_display, settings.page_size)
                )
                self.page_markers.set(settings.page_markers)
                selected_id = preset.preset_id
            finally:
                self._applying_preset = False
            self.update_engine_help()
        try:
            self.settings_store.save_last_document_preset(selected_id)
        except OSError:
            pass

    def engine_changed(self, _event=None) -> None:
        self.update_engine_help()
        self.document_settings_changed()

    def update_engine_help(self) -> None:
        code = self._engine_by_display.get(
            self.document_engine.get(), DocumentSettings().engine
        )
        self.engine_help.set(
            t(self.ENGINE_HELP.get(code, self.ENGINE_HELP["automatic"]))
        )

    def document_settings_changed(self, *_args) -> None:
        if self._applying_preset:
            return
        current_id = self._preset_ids.get(self.preset_display.get())
        current = preset_by_id(current_id)
        settings = self.current_document_settings()
        if current and document_preset_matches(
            current,
            self.output_format.get(),
            settings.page_size,
            settings.engine,
            settings.page_markers,
        ):
            return
        self.preset_display.set(t("ui.preset.custom"))
        self.preset_description.set(t("ui.preset.document_modified"))
        try:
            self.settings_store.save_last_document_preset(CUSTOM_PRESET_ID)
        except OSError:
            pass

    def current_document_settings(self) -> DocumentSettings:
        return DocumentSettings(
            page_size=self._page_by_display.get(
                self.document_page_size.get(), DocumentSettings().page_size
            ),
            engine=self._engine_by_display.get(
                self.document_engine.get(), DocumentSettings().engine
            ),
            page_markers=self.page_markers.get(),
        )

    def validate_start(self) -> str | None:
        try:
            validate_document_settings(self.current_document_settings())
        except ValueError as error:
            return str(error)
        selected = Path(self.selection.get())
        if selected.is_file():
            source_format = format_from_path(selected)
            if source_format is None:
                return t("document.unknown_extension")
            if not conversion_supported(
                source_format,
                self.output_format.get(),
                self.current_document_settings().engine,
                resolve_libreoffice() is not None,
            ):
                return t(
                    "document.pair_unsupported",
                    source=source_format,
                    dest=self.output_format.get(),
                )
        return None

    def conversion_options(self) -> dict[str, object]:
        options = super().conversion_options()
        options["document_settings"] = self.current_document_settings()
        options["document_preset"] = self._preset_ids.get(
            self.preset_display.get(), CUSTOM_PRESET_ID
        )
        return options

    def set_busy(self, busy: bool) -> None:
        super().set_busy(busy)
        selector = "disabled" if busy else "readonly"
        self.preset_selector.configure(state=selector)
        self.engine_selector.configure(state=selector)
        self.page_selector.configure(state=selector)
        self.page_markers_check.configure(state="disabled" if busy else "normal")

    def convert_batch(
        self,
        source_root: Path,
        files: list[Path],
        output_format: str,
        quality: int,
        initial_errors: list[str] | None = None,
        options: dict[str, object] | None = None,
    ) -> None:
        options = options or {}
        settings = options.get("document_settings")
        if not isinstance(settings, DocumentSettings):
            settings = DocumentSettings()
        destination = source_root / f"convertidos_{output_format.lower()}"
        normalize = bool(options.get("normalize_filenames", False))
        extension = DOCUMENT_FORMATS[output_format]
        batch = DocumentBatch(
            source_root=source_root,
            destination=destination,
            extension=extension,
            output_format=output_format,
            settings=settings,
            policy=OutputPolicy(options.get("output_policy", OutputPolicy.SKIP)),
            normalize=normalize,
            generate_report=bool(options.get("generate_report", False)),
            name_collisions=batch_name_collision_keys(
                destination, source_root, files, extension, normalize
            ),
        )
        results: list[FileResult] = []
        discovery_errors = list(initial_errors or [])
        office = resolve_libreoffice()
        for index, source in enumerate(files, 1):
            if self.cancel_event.is_set():
                self._finish(batch, results, discovery_errors, cancelled=True)
                return
            try:
                results.append(self._convert_file(batch, source, office))
            except BatchCancelled:
                self._finish(batch, results, discovery_errors, cancelled=True)
                return
            self.report_progress(index, len(files), source.name)
        self.root.after(0, self.status.set, t("ui.status.finalizing"))
        self._finish(
            batch, results, discovery_errors, cancelled=self.cancel_event.is_set()
        )

    def _finish(
        self,
        batch: DocumentBatch,
        results: list[FileResult],
        discovery_errors: list[str],
        cancelled: bool,
    ) -> None:
        remove_if_empty(batch.destination)
        self.root.after(
            0,
            self.finish_results,
            batch.destination,
            results,
            discovery_errors,
            cancelled,
        )

    def _convert_file(self, batch: DocumentBatch, source: Path, office) -> FileResult:
        started = time.monotonic()
        original_bytes = safe_file_size(source)
        plan: OutputPlan | None = None
        collision = False
        try:
            source_format = format_from_path(source)
            if source_format is None:
                raise DocumentError(t("document.unknown_extension"))
            if not conversion_supported(
                source_format,
                batch.output_format,
                batch.settings.engine,
                office is not None,
            ):
                raise DocumentError(
                    t(
                        "document.pair_unsupported",
                        source=source_format,
                        dest=batch.output_format,
                    )
                )
            desired = desired_output_path(
                batch.destination,
                batch.source_root,
                source,
                batch.extension,
                batch.normalize,
            )
            desired.parent.mkdir(parents=True, exist_ok=True)
            collision = path_key(desired) in batch.name_collisions
            plan = plan_output(
                source, desired, policy_for_name_collision(batch.policy, collision)
            )
            if not plan.should_convert:
                return FileResult(
                    source,
                    plan.target,
                    ResultStatus.SKIPPED,
                    original_bytes,
                    error_message=(
                        t("ui.skip.exists")
                        if plan.action is OutputAction.SKIP_EXISTS
                        else t("ui.skip.up_to_date")
                    ),
                    processing_seconds=time.monotonic() - started,
                    output_action=plan.action.value,
                    name_collision=collision,
                )
            if plan.temporary is None:
                raise DocumentError(t("error.unexpected"))
            outcome = convert_document(
                source,
                plan.temporary,
                batch.output_format,
                batch.settings,
                self.cancel_event,
                office,
            )
            commit_output(plan)
            checksum, checksum_warnings = self.checksum_for_report(
                plan.target, batch.generate_report
            )
            return FileResult(
                source,
                plan.target,
                ResultStatus.CONVERTED,
                original_bytes,
                safe_file_size(plan.target),
                processing_seconds=time.monotonic() - started,
                encoder_mode=outcome.engine,
                output_action=plan.action.value,
                name_collision=collision,
                warnings=(*outcome.warnings, *checksum_warnings),
                sha256=checksum,
            )
        except Exception as error:
            logging.getLogger(__name__).exception("conversion_failed source=%s", source)
            cleanup_temporary(plan)
            if self.cancel_event.is_set():
                raise BatchCancelled from error
            return FileResult(
                source,
                None,
                ResultStatus.FAILED,
                original_bytes,
                error_message=describe_error(error).message,
                processing_seconds=time.monotonic() - started,
                name_collision=collision,
            )

    @staticmethod
    def _display_for(mapping: dict[str, str], code: str) -> str:
        for label, value in mapping.items():
            if value == code:
                return label
        return next(iter(mapping))
