"""Controles y flujo de lote compartidos por los paneles de conversión."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from tkinter import (
    BooleanVar,
    IntVar,
    Scale,
    StringVar,
    Tk,
    filedialog,
    messagebox,
    ttk,
)

from batch_processing import checked_output_root, discover_files, is_link
from conversion_report import (
    HashCancelled,
    build_report,
    report_path,
    sha256_file,
    write_report_atomic,
)
from conversion_results import BatchSummary, FileResult, ResultStatus
from error_handling import UserFacingError, describe_error
from filename_normalization import output_filename
from i18n import t
from output_policy import OutputPolicy
from presets import SettingsStore
from process_control import stop_process
from ui import theme
from ui.formats import batch_output_root
from ui.summary_dialog import show_summary

logging.getLogger(__name__).addHandler(logging.NullHandler())


class BatchCancelled(Exception):
    """Se solicitó cancelar mientras se convertía un archivo."""


@dataclass(frozen=True, slots=True)
class BatchRequest:
    source_root: Path
    files: tuple[Path, ...] | None
    output_format: str
    quality: int
    recursive: bool
    options: dict[str, object]
    destination_parent: Path | None


@dataclass(frozen=True, slots=True)
class FinishedBatch:
    summary: BatchSummary
    destination: Path
    report: Path | None
    request: BatchRequest | None

    @property
    def failed_sources(self) -> tuple[Path, ...]:
        return tuple(
            item.source_path
            for item in self.summary.results
            if item.status is ResultStatus.FAILED
        )


class ConverterPanel(ttk.Frame):
    """Shared controls and batch lifecycle for the conversion tabs."""

    MEDIA_TYPE = "media"
    #: Ejemplo de renombrado; cada panel muestra el de su propio medio.
    NAME_EXAMPLE_KEY = "ui.output_name.example.image"

    def __init__(
        self,
        parent,
        root: Tk,
        title: str,
        extensions: set[str],
        formats: dict[str, object],
        footer_parent=None,
    ) -> None:
        super().__init__(parent, padding=20)
        self.root, self.extensions, self.formats = root, extensions, formats
        self.selection, self.output_format = (
            StringVar(),
            StringVar(value=next(iter(formats))),
        )
        self.quality, self.status = (
            IntVar(value=85),
            StringVar(value=t("ui.status.select_prompt")),
        )
        self.recursive = BooleanVar(value=True)
        self.selected_files: tuple[Path, ...] = ()
        self.selection_display = StringVar(value=t("ui.source.empty"))
        self.destination_parent: Path | None = None
        self.destination_preview = StringVar(value=t("ui.destination.default"))
        self.cancel_event = threading.Event()
        self.busy = False
        self.closing = False
        self.active_process: subprocess.Popen[str] | None = None
        self.batch_started = 0.0
        self.files_discovered = 0
        self.last_summary: BatchSummary | None = None
        self.finished_batch: FinishedBatch | None = None
        self._active_request: BatchRequest | None = None
        self._summary_window = None
        self.settings_store = SettingsStore()
        self.output_policy = StringVar(value=self.settings_store.load_output_policy())
        self.normalize_filenames = BooleanVar(
            value=self.settings_store.load_normalize_filenames()
        )
        self.output_name_preview = StringVar()
        self.generate_report = BooleanVar(
            value=self.settings_store.load_generate_report()
        )
        self.report_path_mode = StringVar(
            value=(
                t("ui.report_paths.absolute")
                if self.settings_store.load_report_absolute_paths()
                else t("ui.report_paths.relative")
            )
        )
        self.output_policy_help = StringVar()
        self._policy_by_display = {
            t("ui.policy.skip"): OutputPolicy.SKIP,
            t("ui.policy.overwrite"): OutputPolicy.OVERWRITE,
            t("ui.policy.unique"): OutputPolicy.UNIQUE,
            t("ui.policy.source_newer"): OutputPolicy.SOURCE_NEWER,
        }
        self._policy_help = {
            OutputPolicy.SKIP: t("ui.policy.help.skip"),
            OutputPolicy.OVERWRITE: t("ui.policy.help.overwrite"),
            OutputPolicy.UNIQUE: t("ui.policy.help.unique"),
            OutputPolicy.SOURCE_NEWER: t("ui.policy.help.source_newer"),
        }
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text=title, style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )
        selection_row = ttk.LabelFrame(self, text=t("ui.section.source"), padding=10)
        selection_row.grid(row=1, column=0, columnspan=2, sticky="ew")
        selection_row.columnconfigure(0, weight=1)
        ttk.Entry(
            selection_row,
            textvariable=self.selection_display,
            state="readonly",
            width=1,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 12))
        source_actions = ttk.Frame(selection_row)
        source_actions.grid(row=0, column=1, sticky="w")
        self.file_button = ttk.Button(
            source_actions, text=t("ui.button.select_files"), command=self.select_file
        )
        self.file_button.grid(row=0, column=0, padx=(0, 8))
        self.folder_button = ttk.Button(
            source_actions,
            text=t("ui.button.select_folder"),
            command=self.select_folder,
        )
        self.folder_button.grid(row=0, column=1)

        self.recursive_check = ttk.Checkbutton(
            selection_row,
            text=t("ui.check.recursive"),
            variable=self.recursive,
        )
        self.recursive_check.grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        self.recursive_check.state(("disabled",))

        self.encoding_column = ttk.Frame(self)
        self.encoding_column.grid(row=3, column=0, sticky="new", pady=(14, 0))
        self.encoding_column.columnconfigure(0, weight=1)
        options = ttk.LabelFrame(
            self.encoding_column, text=t("ui.section.encoding"), padding=12
        )
        self.options_frame = options
        options.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        options.columnconfigure(3, weight=1)
        ttk.Label(options, text=t("ui.label.output_format")).grid(
            row=0, column=0, padx=(0, 10)
        )
        self.format_selector = ttk.Combobox(
            options,
            textvariable=self.output_format,
            values=tuple(formats),
            state="readonly",
            width=10,
        )
        self.format_selector.grid(row=0, column=1, padx=(0, 22))
        quality_label = ttk.Label(options, text=t("ui.label.quality"))
        quality_label.grid(row=0, column=2, padx=(0, 10))
        # Scale clásico en vez de ttk: el trough de ttk.Scale ignora
        # `troughcolor` en clam y se queda con el canal claro por defecto,
        # que rompe el tema oscuro. El widget clásico sí es coloreable.
        self.slider = Scale(
            options,
            from_=1,
            to=100,
            orient="horizontal",
            variable=self.quality,
            command=lambda v: self.quality.set(round(float(v))),
            showvalue=False,
            troughcolor=theme.RAISED,
            background=theme.SIGNAL,
            activebackground=theme.SIGNAL_DIM,
            highlightthickness=1,
            highlightbackground=theme.PANEL,
            highlightcolor=theme.SIGNAL,
            borderwidth=0,
            sliderrelief="flat",
            sliderlength=20,
            width=10,
        )
        self.slider.grid(row=0, column=3, sticky="ew")
        quality_readout = ttk.Label(
            options,
            textvariable=self.quality,
            width=4,
            anchor="e",
            style="Readout.TLabel",
        )
        quality_readout.grid(row=0, column=4, padx=(8, 0))
        self.quality_widgets = (quality_label, self.slider, quality_readout)
        policy_box = ttk.LabelFrame(self, text=t("ui.section.destination"), padding=12)
        self.policy_box = policy_box
        policy_box.columnconfigure(0, weight=1)
        ttk.Entry(
            policy_box, textvariable=self.destination_preview, state="readonly", width=1
        ).grid(row=0, column=0, sticky="ew")
        destination_actions = ttk.Frame(policy_box)
        destination_actions.grid(row=1, column=0, sticky="w", pady=(8, 10))
        self.destination_button = ttk.Button(
            destination_actions,
            text=t("ui.button.change_destination"),
            command=self.select_destination,
        )
        self.destination_button.grid(row=0, column=0, padx=(0, 8))
        self.reset_destination_button = ttk.Button(
            destination_actions,
            text=t("ui.button.reset_destination"),
            command=self.reset_destination,
            state="disabled",
        )
        self.reset_destination_button.grid(row=0, column=1)
        ttk.Label(policy_box, text=t("ui.label.on_existing")).grid(
            row=2, column=0, sticky="w", pady=(4, 4)
        )
        self.policy_selector = ttk.Combobox(
            policy_box,
            values=tuple(self._policy_by_display),
            state="readonly",
            width=24,
        )
        selected_policy_label = next(
            label
            for label, policy in self._policy_by_display.items()
            if policy.value == self.output_policy.get()
        )
        self.policy_selector.set(selected_policy_label)
        self.policy_selector.grid(row=3, column=0, sticky="ew")
        ttk.Label(
            policy_box,
            textvariable=self.output_policy_help,
            wraplength=244,
            style="Muted.TLabel",
        ).grid(row=4, column=0, pady=(5, 0), sticky="w")
        self.policy_selector.bind("<<ComboboxSelected>>", self.output_policy_changed)
        self.output_policy_help.set(
            self._policy_help[OutputPolicy(self.output_policy.get())]
        )
        self.normalize_check = ttk.Checkbutton(
            policy_box,
            text=t("ui.check.normalize"),
            variable=self.normalize_filenames,
            command=self.normalize_filenames_changed,
        )
        self.normalize_check.grid(row=5, column=0, pady=(10, 0), sticky="w")
        ttk.Label(
            policy_box,
            textvariable=self.output_name_preview,
            wraplength=244,
            style="Muted.TLabel",
        ).grid(row=6, column=0, pady=(3, 0), sticky="w")
        self.output_format.trace_add("write", self._output_format_changed)
        self.selection.trace_add("write", self._selection_changed)
        self.report_check = ttk.Checkbutton(
            policy_box,
            text=t("ui.check.report"),
            variable=self.generate_report,
            command=self.report_settings_changed,
        )
        self.report_check.grid(row=7, column=0, pady=(10, 0), sticky="w")
        report_row = ttk.Frame(policy_box)
        report_row.grid(row=8, column=0, sticky="w", pady=(4, 0))
        ttk.Label(report_row, text=t("ui.label.report_paths")).pack(
            side="left", padx=(0, 8)
        )
        self.report_path_selector = ttk.Combobox(
            report_row,
            textvariable=self.report_path_mode,
            values=(t("ui.report_paths.relative"), t("ui.report_paths.absolute")),
            state="readonly" if self.generate_report.get() else "disabled",
            width=12,
        )
        self.report_path_selector.pack(side="left")
        self.report_path_selector.bind(
            "<<ComboboxSelected>>", self.report_settings_changed
        )

        self.compact = False
        self.reflow(True)
        self._build_footer(footer_parent)
        self._refresh_source_controls()
        self._output_format_changed()

    def _build_footer(self, footer_parent) -> None:
        footer = ttk.Frame(
            footer_parent or self, style="Surface.TFrame", padding=(16, 8, 16, 12)
        )
        footer.grid(
            row=5 if footer_parent is None else 2, column=0, columnspan=2, sticky="ew"
        )
        footer.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(footer, mode="determinate")
        self.progress.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        status_label = ttk.Label(
            footer, textvariable=self.status, style="Tagline.TLabel"
        )
        status_label.grid(row=1, column=0, sticky="w", padx=(0, 12))
        actions = ttk.Frame(footer, style="Surface.TFrame")
        actions.grid(row=1, column=1, sticky="e")
        footer.bind(
            "<Configure>",
            lambda event: status_label.configure(
                wraplength=max(80, event.width - actions.winfo_reqwidth() - 48)
            ),
        )
        self.cancel_button = ttk.Button(
            actions, text=t("ui.button.cancel"), command=self.cancel, state="disabled"
        )
        self.cancel_button.grid(row=0, column=0, padx=(0, 8))
        self.convert_button = ttk.Button(
            actions,
            text=t("ui.button.start"),
            command=self.start,
            style="Accent.TButton",
        )
        self.convert_button.grid(row=0, column=1)
        self.results_button = ttk.Button(
            actions,
            text=t("ui.button.last_results"),
            command=self.open_last_results,
        )
        self.results_button.grid(row=0, column=2, padx=(8, 0))
        self.results_button.grid_remove()

    def reflow(self, compact: bool) -> None:
        if self.compact == compact:
            return
        self.compact = compact
        self.policy_box.grid(
            row=4 if compact else 3,
            column=0 if compact else 1,
            padx=0 if compact else (16, 0),
            pady=(0, 8) if compact else (14, 0),
            sticky="ew" if compact else "new",
        )

    def show_quality_controls(self, visible: bool) -> None:
        for widget in self.quality_widgets:
            if visible:
                widget.grid()
            else:
                widget.grid_remove()

    def output_policy_changed(self, _event=None) -> None:
        policy = self._policy_by_display.get(
            self.policy_selector.get(), OutputPolicy.SKIP
        )
        self.output_policy.set(policy.value)
        self.output_policy_help.set(self._policy_help[policy])
        try:
            self.settings_store.save_output_policy(policy.value)
        except OSError:
            pass

    def normalize_filenames_changed(self) -> None:
        try:
            self.settings_store.save_normalize_filenames(self.normalize_filenames.get())
        except OSError:
            pass
        self.update_output_name_preview()

    def update_output_name_preview(self) -> None:
        selected = self.single_source()
        format_value = self.formats[self.output_format.get()]
        extension = format_value[1] if isinstance(format_value, tuple) else format_value
        if selected is not None:
            name = output_filename(selected, extension, self.normalize_filenames.get())
            self.output_name_preview.set(t("ui.output_name.preview", name=name))
        else:
            self.output_name_preview.set(t(self.NAME_EXAMPLE_KEY, extension=extension))

    def report_settings_changed(self, _event=None) -> None:
        self.report_path_selector.configure(
            state="readonly" if self.generate_report.get() else "disabled"
        )
        try:
            self.settings_store.save_generate_report(self.generate_report.get())
            self.settings_store.save_report_absolute_paths(
                self.report_path_mode.get() == t("ui.report_paths.absolute")
            )
        except OSError:
            pass

    def files_in(self, folder: Path) -> list[Path]:
        return discover_files(folder, self.extensions, self.recursive.get()).files

    def single_source(self) -> Path | None:
        selection = self.selection.get()
        if not selection or len(self.selected_files) > 1:
            return None
        path = Path(selection)
        return path if not is_link(path) and path.is_file() else None

    def _selection_changed(self, *_args) -> None:
        self.selection_display.set(self.selection.get() or t("ui.source.empty"))
        self._refresh_source_controls()
        self._output_format_changed()

    def _refresh_source_controls(self) -> None:
        selected = self.selection.get()
        self.convert_button.state(
            ("!disabled" if selected and not self.busy else "disabled",)
        )
        folder = selected and not self.selected_files and Path(selected).is_dir()
        self.recursive_check.state(
            ("!disabled" if folder and not self.busy else "disabled",)
        )

    def _output_format_changed(self, *_args) -> None:
        self.update_output_name_preview()
        selected = self.selection.get()
        parent = self.destination_parent
        if parent is None and selected:
            path = self.selected_files[0] if self.selected_files else Path(selected)
            parent = path if not self.selected_files and path.is_dir() else path.parent
        self.destination_preview.set(
            str(parent / f"convertidos_{self.output_format.get().lower()}")
            if parent is not None
            else t("ui.destination.default")
        )

    def restore_sources(self, selected: str, files: tuple[Path, ...]) -> None:
        self.selected_files = files
        if len(files) > 1:
            selected = t("ui.status.files_selected", count=len(files))
        self.selection.set(selected)
        if len(files) > 1:
            self.status.set(selected)
        elif selected:
            path = Path(selected)
            self.status.set(
                t("ui.status.file_selected", name=path.name)
                if path.is_file()
                else t("ui.status.folder_selected")
            )

    def set_destination(self, parent: Path | None) -> None:
        self.destination_parent = parent
        self.reset_destination_button.state(
            ("!disabled" if parent is not None else "disabled",)
        )
        self._output_format_changed()

    def select_destination(self) -> None:
        path = filedialog.askdirectory(
            parent=self.root, title=t("ui.dialog.destination_title"), mustexist=True
        )
        if path:
            self.set_destination(Path(path))

    def reset_destination(self) -> None:
        self.set_destination(None)

    def select_file(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(self.extensions))
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title=t("ui.dialog.select_file_title"),
            filetypes=(
                (t("ui.dialog.supported_files"), patterns),
                (t("ui.dialog.all_files"), "*.*"),
            ),
        )
        if paths:
            files = tuple(dict.fromkeys(Path(path) for path in paths))
            self.restore_sources(str(files[0]), files)

    def select_folder(self) -> None:
        path_text = filedialog.askdirectory(
            parent=self.root, title=t("ui.dialog.select_folder_title"), mustexist=True
        )
        if path_text:
            self.restore_sources(path_text, ())

    def start(self) -> None:
        if self.busy or self.closing:
            return
        try:
            source_root, files = self._batch_sources()
        except (OSError, ValueError) as error:
            messagebox.showwarning(
                t("ui.dialog.selection_required_title"), str(error), parent=self.root
            )
            return
        validation_error = self.validate_start()
        if validation_error:
            messagebox.showerror(
                t("ui.dialog.invalid_settings_title"),
                validation_error,
                parent=self.root,
            )
            return

        self._start_batch(
            BatchRequest(
                source_root,
                tuple(files) if files is not None else None,
                self.output_format.get(),
                self.quality.get(),
                self.recursive.get(),
                self.conversion_options(),
                self.destination_parent,
            )
        )

    def _start_batch(self, request: BatchRequest) -> None:
        self.close_results()
        self._active_request = request
        options = request.options.copy()
        self.cancel_event.clear()
        self.batch_started = time.monotonic()
        self.batch_started_at = datetime.now(timezone.utc)
        logging.getLogger(__name__).info("batch_start media=%s", type(self).__name__)
        self.set_busy(True)
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        self.status.set(t("ui.status.discovering"))
        self.report_enabled = bool(options.get("generate_report", False))
        self.report_absolute = bool(options.get("report_absolute_paths", False))
        self.report_source_root = request.source_root
        self.report_output_format = request.output_format
        self.report_settings = {
            **options,
            "quality": request.quality,
            "recursive": request.recursive,
        }
        options["destination_parent"] = request.destination_parent
        threading.Thread(
            target=self._run_batch,
            args=(
                request.source_root,
                list(request.files) if request.files is not None else None,
                request.output_format,
                request.quality,
                request.recursive,
                options,
            ),
            daemon=True,
        ).start()

    def retry_failed(self) -> bool:
        batch = self.finished_batch
        if self.busy or self.closing or batch is None or batch.request is None:
            return False
        files = batch.failed_sources
        if not files:
            return False
        self._start_batch(
            replace(
                batch.request,
                files=files,
                recursive=False,
                options={
                    **batch.request.options,
                    "output_policy": OutputPolicy.UNIQUE.value,
                },
            )
        )
        return True

    def _batch_sources(self) -> tuple[Path, list[Path] | None]:
        selected = self.selection.get()
        if not selected:
            raise ValueError(t("ui.dialog.selection_required_body"))
        path = Path(selected)
        if not self.selected_files and path.is_dir():
            if is_link(path):
                raise ValueError(t("discovery.unsafe_path"))
            return path.resolve(), None
        files = self.selected_files or (path,)
        source_root = files[0].parent.resolve()
        for file in files:
            if (
                file.parent.resolve() != source_root
                or is_link(file)
                or file.suffix.casefold() not in self.extensions
                or not file.is_file()
            ):
                raise ValueError(t("ui.error.invalid_source", name=file.name))
        return source_root, [source_root / file.name for file in files]

    def _run_batch(self, *args) -> None:
        try:
            self.prepare_batch(*args)
        except Exception as error:
            logging.getLogger(__name__).exception("batch_failed")
            self.root.after(0, self.fail, describe_error(error).message)

    def prepare_batch(
        self,
        source_root: Path,
        files: list[Path] | None,
        output_format: str,
        quality: int,
        recursive: bool,
        options: dict[str, object],
    ) -> None:
        discovery_errors: list[str] = []
        if is_link(source_root):
            raise UserFacingError(t("discovery.unsafe_path"))
        destination = batch_output_root(source_root, output_format, options)
        if destination == source_root or destination in source_root.parents:
            raise UserFacingError(t("ui.error.destination_contains_source"))
        if files is None:
            discovery = discover_files(
                source_root, self.extensions, recursive, self.cancel_event
            )
            files = discovery.files
            discovery_errors = discovery.errors
            if discovery.cancelled:
                self.root.after(0, self.conversion_cancelled, 0)
                return

        self.files_discovered = len(files)
        self.root.after(0, self.prepare_conversion_progress, len(files))
        if not files:
            self.root.after(0, self.no_files_found, discovery_errors)
            return
        self.convert_batch(
            source_root, files, output_format, quality, discovery_errors, options
        )

    def validate_start(self) -> str | None:
        return None

    def conversion_options(self) -> dict[str, object]:
        return {
            "output_policy": self.output_policy.get(),
            "normalize_filenames": self.normalize_filenames.get(),
            "generate_report": self.generate_report.get(),
            "report_absolute_paths": self.report_path_mode.get()
            == t("ui.report_paths.absolute"),
        }

    def prepare_conversion_progress(self, total: int) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=total, value=0)
        self.status.set(t("ui.status.discovery_done", total=total))

    def convert_batch(
        self,
        source_root: Path,
        files: list[Path],
        output_format: str,
        quality: int,
        initial_errors: list[str] | None = None,
        options: dict[str, object] | None = None,
    ) -> None:
        raise NotImplementedError

    def cancel(self) -> None:
        self.cancel_event.set()
        self.cancel_button.state(("disabled",))
        self.status.set(t("ui.status.cancelling"))
        process = self.active_process
        if process is not None:
            threading.Thread(target=stop_process, args=(process,), daemon=True).start()

    def no_files_found(self, errors: list[str]) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.set_busy(False)
        self.status.set(t("ui.status.no_files"))
        if self.closing:
            return
        detail = (
            t("ui.dialog.warnings_prefix") + "\n".join(errors[:5]) if errors else ""
        )
        messagebox.showinfo(
            t("ui.dialog.no_files_title"), t("ui.dialog.no_files_body", detail=detail)
        )

    def conversion_cancelled(self, converted: int) -> None:
        self.progress.stop()
        self.set_busy(False)
        self.status.set(t("ui.status.cancelled", converted=converted))

    def report_progress(self, index: int, total: int, name: str) -> None:
        self.root.after(
            0,
            self.status.set,
            t("ui.status.converting", index=index, total=total, name=name),
        )
        self.root.after(0, self.progress.configure, {"value": index})

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for button in (
            self.file_button,
            self.folder_button,
            self.destination_button,
            self.slider,
        ):
            button.configure(state=state)
        self.format_selector.configure(state="disabled" if busy else "readonly")
        self._refresh_source_controls()
        self.reset_destination_button.state(
            (
                "!disabled"
                if not busy and self.destination_parent is not None
                else "disabled",
            )
        )
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.results_button.configure(state=state)
        self.policy_selector.configure(state="disabled" if busy else "readonly")
        self.normalize_check.configure(state=state)
        self.report_check.configure(state=state)
        self.report_path_selector.configure(
            state="readonly" if not busy and self.generate_report.get() else "disabled"
        )

    def restore_finished_batch(self, batch: FinishedBatch | None) -> None:
        self.finished_batch = batch
        self.last_summary = batch.summary if batch is not None else None
        if batch is not None:
            self.results_button.grid()

    def close_results(self) -> None:
        if self._summary_window is not None and self._summary_window.winfo_exists():
            self._summary_window.destroy()
        self._summary_window = None

    def open_last_results(self) -> None:
        batch = self.finished_batch
        if batch is None or self.closing:
            return
        if self._summary_window is not None and self._summary_window.winfo_exists():
            self._summary_window.lift()
            self._summary_window.focus_set()
            return
        request = batch.request
        self._summary_window = show_summary(
            self.root,
            batch.summary,
            batch.destination,
            batch.report,
            source_root=request.source_root if request else None,
            retry=self.retry_failed if request and batch.failed_sources else None,
        )

    def checksum_for_report(
        self, output: Path, enabled: bool
    ) -> tuple[str | None, tuple[str, ...]]:
        if not enabled:
            return None, ()
        try:
            checksum, warning = sha256_file(output, self.cancel_event)
        except HashCancelled:
            return None, (t("ui.warning.hash_cancelled"),)
        except OSError as error:
            return None, (
                t("ui.warning.hash_failed", detail=describe_error(error).message),
            )
        return checksum, (warning,) if warning else ()

    def finish_results(
        self,
        destination: Path,
        results: list[FileResult],
        discovery_errors: list[str],
        cancelled: bool = False,
    ) -> None:
        summary = BatchSummary(
            files_discovered=self.files_discovered,
            results=tuple(results),
            elapsed_seconds=time.monotonic() - self.batch_started,
            cancelled=cancelled,
            discovery_errors=tuple(discovery_errors),
        )
        if getattr(self, "report_enabled", False):
            self.status.set(t("ui.status.generating_report"))
            threading.Thread(
                target=self.write_report,
                args=(destination, summary),
                daemon=True,
            ).start()
            return
        self.show_results(destination, summary, None)

    def write_report(self, destination: Path, summary: BatchSummary) -> None:
        completed_at = datetime.now(timezone.utc)
        generated_path = None
        try:
            destination = checked_output_root(destination)
            report = build_report(
                summary,
                self.report_source_root,
                destination,
                self.MEDIA_TYPE,
                self.report_output_format,
                self.report_settings,
                self.batch_started_at,
                completed_at,
                self.report_absolute,
            )
            generated_path = report_path(destination, completed_at)
            write_report_atomic(generated_path, report)
        except Exception as error:
            logging.getLogger(__name__).exception("report_generation_failed")
            generated_path = None
            warning = t(
                "ui.warning.report_failed", detail=describe_error(error).message
            )
            summary = replace(summary, operation_warnings=(warning,))
        self.root.after(0, self.show_results, destination, summary, generated_path)

    def show_results(
        self, destination: Path, summary: BatchSummary, generated_report: Path | None
    ) -> None:
        self.close_results()
        self.restore_finished_batch(
            FinishedBatch(
                summary,
                destination,
                generated_report,
                self._active_request,
            )
        )
        self.set_busy(False)
        self.status.set(
            t("ui.status.cancelled", converted=summary.converted)
            if summary.cancelled
            else t(
                "ui.status.finished",
                converted=summary.converted,
                skipped=summary.skipped,
                failed=summary.failed,
            )
        )
        logger = logging.getLogger(__name__)
        logger.info(
            "batch_complete discovered=%d processed=%d converted=%d skipped=%d failed=%d elapsed=%.3f cancelled=%s",
            summary.files_discovered,
            summary.files_processed,
            summary.converted,
            summary.skipped,
            summary.failed,
            summary.elapsed_seconds,
            summary.cancelled,
        )
        for result in summary.results:
            for warning in result.warnings:
                logger.warning(
                    "conversion_warning source=%s code=%s severity=%s message=%s",
                    result.source_path,
                    getattr(
                        getattr(warning, "code", None), "value", "OPERATION_WARNING"
                    ),
                    getattr(getattr(warning, "severity", None), "value", "warning"),
                    getattr(warning, "message", str(warning)),
                )
        for warning in summary.operation_warnings:
            logger.warning("batch_warning message=%s", warning)
        if getattr(self, "closing", False):
            return
        self.open_last_results()

    def fail(self, detail: str) -> None:
        logging.getLogger(__name__).error("batch_aborted detail=%s", detail)
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.set_busy(False)
        self.status.set(t("ui.status.aborted"))
        if not self.closing:
            messagebox.showerror(
                t("ui.dialog.conversion_error_title"), detail, parent=self.root
            )
