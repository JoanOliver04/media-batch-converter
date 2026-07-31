"""Controles y flujo de lote compartidos por los paneles de conversión."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import replace
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

from batch_processing import discover_files
from conversion_report import (
    HashCancelled,
    build_report,
    report_path,
    sha256_file,
    write_report_atomic,
)
from conversion_results import BatchSummary, FileResult
from error_handling import describe_error
from filename_normalization import output_filename
from i18n import t
from output_policy import OutputPolicy
from presets import SettingsStore
from summary_dialog import show_summary
from ui import theme

logging.getLogger(__name__).addHandler(logging.NullHandler())


class BatchCancelled(Exception):
    """Se solicitó cancelar mientras se convertía un archivo."""


class ConverterPanel(ttk.Frame):
    """Controles compartidos por los tres tipos de conversión."""

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
    ) -> None:
        super().__init__(parent, padding=24)
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
        self.cancel_event = threading.Event()
        self.busy = False
        self.active_process: subprocess.Popen[str] | None = None
        self.batch_started = 0.0
        self.files_discovered = 0
        self.last_summary: BatchSummary | None = None
        self.settings_store = SettingsStore()
        self.output_policy = StringVar(value=self.settings_store.load_output_policy())
        self.normalize_filenames = BooleanVar(
            value=self.settings_store.load_normalize_filenames()
        )
        self.output_name_preview = StringVar(value=t(self.NAME_EXAMPLE_KEY))
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
            row=0, column=0, sticky="w", pady=(0, 18)
        )
        selection_row = ttk.Frame(self)
        selection_row.grid(row=1, column=0, sticky="ew")
        selection_row.columnconfigure(0, weight=1)
        ttk.Entry(selection_row, textvariable=self.selection, state="readonly").grid(
            row=0, column=0, sticky="ew", padx=(0, 10)
        )
        self.file_button = ttk.Button(
            selection_row, text=t("ui.button.select_file"), command=self.select_file
        )
        self.file_button.grid(row=0, column=1, padx=(0, 8))
        self.folder_button = ttk.Button(
            selection_row, text=t("ui.button.select_folder"), command=self.select_folder
        )
        self.folder_button.grid(row=0, column=2)

        self.recursive_check = ttk.Checkbutton(
            self,
            text=t("ui.check.recursive"),
            variable=self.recursive,
        )
        self.recursive_check.grid(row=2, column=0, sticky="w", pady=(14, 0))

        options = ttk.Frame(self)
        self.options_frame = options
        options.grid(row=3, column=0, sticky="ew", pady=16)
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
        ttk.Label(options, text=t("ui.label.quality")).grid(
            row=0, column=2, padx=(0, 10)
        )
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
            highlightthickness=0,
            borderwidth=0,
            sliderrelief="flat",
            sliderlength=20,
            width=10,
        )
        self.slider.grid(row=0, column=3, sticky="ew")
        ttk.Label(
            options,
            textvariable=self.quality,
            width=4,
            anchor="e",
            style="Readout.TLabel",
        ).grid(row=0, column=4, padx=(8, 0))
        ttk.Label(options, text=t("ui.label.on_existing")).grid(
            row=2, column=0, padx=(0, 10), pady=(10, 0), sticky="w"
        )
        self.policy_selector = ttk.Combobox(
            options, values=tuple(self._policy_by_display), state="readonly", width=31
        )
        selected_policy_label = next(
            label
            for label, policy in self._policy_by_display.items()
            if policy.value == self.output_policy.get()
        )
        self.policy_selector.set(selected_policy_label)
        self.policy_selector.grid(
            row=2, column=1, padx=(0, 16), pady=(10, 0), sticky="w"
        )
        ttk.Label(
            options,
            textvariable=self.output_policy_help,
            wraplength=390,
            style="Muted.TLabel",
        ).grid(row=2, column=2, columnspan=3, pady=(10, 0), sticky="w")
        self.policy_selector.bind("<<ComboboxSelected>>", self.output_policy_changed)
        self.output_policy_help.set(
            self._policy_help[OutputPolicy(self.output_policy.get())]
        )
        self.normalize_check = ttk.Checkbutton(
            options,
            text=t("ui.check.normalize"),
            variable=self.normalize_filenames,
            command=self.normalize_filenames_changed,
        )
        self.normalize_check.grid(
            row=3, column=0, columnspan=2, pady=(10, 0), sticky="w"
        )
        ttk.Label(
            options,
            textvariable=self.output_name_preview,
            wraplength=470,
            style="Muted.TLabel",
        ).grid(row=3, column=2, columnspan=3, pady=(10, 0), sticky="w")
        self.output_format.trace_add(
            "write", lambda *_args: self.update_output_name_preview()
        )
        self.report_check = ttk.Checkbutton(
            options,
            text=t("ui.check.report"),
            variable=self.generate_report,
            command=self.report_settings_changed,
        )
        self.report_check.grid(row=4, column=0, columnspan=2, pady=(10, 0), sticky="w")
        ttk.Label(options, text=t("ui.label.report_paths")).grid(
            row=4, column=2, pady=(10, 0), sticky="e"
        )
        self.report_path_selector = ttk.Combobox(
            options,
            textvariable=self.report_path_mode,
            values=(t("ui.report_paths.relative"), t("ui.report_paths.absolute")),
            state="readonly",
            width=12,
        )
        self.report_path_selector.grid(row=4, column=3, pady=(10, 0), sticky="w")
        self.report_path_selector.bind(
            "<<ComboboxSelected>>", self.report_settings_changed
        )

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(
            self, textvariable=self.status, wraplength=700, style="Muted.TLabel"
        ).grid(row=5, column=0, sticky="w")
        actions = ttk.Frame(self)
        actions.grid(row=6, column=0, sticky="e", pady=(20, 0))
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
        selected = Path(self.selection.get())
        if selected.is_file():
            format_value = self.formats[self.output_format.get()]
            extension = (
                format_value[1] if isinstance(format_value, tuple) else format_value
            )
            name = output_filename(selected, extension, self.normalize_filenames.get())
            self.output_name_preview.set(t("ui.output_name.preview", name=name))
        else:
            self.output_name_preview.set(t(self.NAME_EXAMPLE_KEY))

    def report_settings_changed(self, _event=None) -> None:
        try:
            self.settings_store.save_generate_report(self.generate_report.get())
            self.settings_store.save_report_absolute_paths(
                self.report_path_mode.get() == t("ui.report_paths.absolute")
            )
        except OSError:
            pass

    def files_in(self, folder: Path) -> list[Path]:
        return discover_files(folder, self.extensions, self.recursive.get()).files

    def select_file(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(self.extensions))
        path_text = filedialog.askopenfilename(
            title=t("ui.dialog.select_file_title"),
            filetypes=(
                (t("ui.dialog.supported_files"), patterns),
                (t("ui.dialog.all_files"), "*.*"),
            ),
        )
        if path_text:
            self.selection.set(path_text)
            self.status.set(t("ui.status.file_selected", name=Path(path_text).name))
            self.update_output_name_preview()

    def select_folder(self) -> None:
        path_text = filedialog.askdirectory(title=t("ui.dialog.select_folder_title"))
        if path_text:
            self.selection.set(path_text)
            self.status.set(t("ui.status.folder_selected"))
            self.update_output_name_preview()

    def start(self) -> None:
        validation_error = self.validate_start()
        if validation_error:
            messagebox.showerror(
                t("ui.dialog.invalid_settings_title"), validation_error
            )
            return
        selected = Path(self.selection.get())
        if selected.is_file() and selected.suffix.lower() in self.extensions:
            source_root, files = selected.parent, [selected]
        elif selected.is_dir():
            source_root, files = selected, None
        else:
            messagebox.showwarning(
                t("ui.dialog.selection_required_title"),
                t("ui.dialog.selection_required_body"),
            )
            return

        self.cancel_event.clear()
        self.batch_started = time.monotonic()
        self.batch_started_at = datetime.now(timezone.utc)
        logging.getLogger(__name__).info("batch_start media=%s", type(self).__name__)
        self.set_busy(True)
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        self.status.set(t("ui.status.discovering"))
        options = self.conversion_options()
        self.report_enabled = bool(options.get("generate_report", False))
        self.report_absolute = bool(options.get("report_absolute_paths", False))
        self.report_source_root = source_root
        self.report_output_format = self.output_format.get()
        self.report_settings = {
            **options,
            "quality": self.quality.get(),
            "recursive": self.recursive.get(),
        }
        threading.Thread(
            target=self.prepare_batch,
            args=(
                source_root,
                files,
                self.output_format.get(),
                self.quality.get(),
                self.recursive.get(),
                options,
            ),
            daemon=True,
        ).start()

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
        self.status.set(t("ui.status.cancelling"))
        process = self.active_process
        if process is not None and process.poll() is None:
            process.terminate()

    def no_files_found(self, errors: list[str]) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.set_busy(False)
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
            self.convert_button,
            self.slider,
        ):
            button.configure(state=state)
        self.format_selector.configure(state="disabled" if busy else "readonly")
        self.recursive_check.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.policy_selector.configure(state="disabled" if busy else "readonly")
        self.normalize_check.configure(state=state)
        self.report_check.configure(state=state)
        self.report_path_selector.configure(state="disabled" if busy else "readonly")

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
        self.last_summary = summary
        self.set_busy(False)
        self.status.set(
            t(
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
                    result.source,
                    getattr(
                        getattr(warning, "code", None), "value", "OPERATION_WARNING"
                    ),
                    getattr(getattr(warning, "severity", None), "value", "warning"),
                    getattr(warning, "message", str(warning)),
                )
        for warning in summary.operation_warnings:
            logger.warning("batch_warning message=%s", warning)
        if summary.operation_warnings:
            messagebox.showwarning(
                t("ui.dialog.report_failed_title"),
                "\n".join(summary.operation_warnings),
            )
        show_summary(self.root, summary, destination, generated_report)

    def fail(self, detail: str) -> None:
        logging.getLogger(__name__).error("batch_aborted detail=%s", detail)
        self.set_busy(False)
        self.status.set(t("ui.status.aborted"))
        messagebox.showerror(t("ui.dialog.conversion_error_title"), detail)
