"""Conversor de imágenes, audio y vídeo con interfaz Tkinter."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk

from audio_encoding import (
    build_audio_args,
    encoder_available,
    manual_audio_settings,
    validate_audio_settings,
)
from animation_handling import (
    AnimationMode,
    animation_supported,
    frame_directory,
    frame_number_width,
    webp_frame_durations,
)
from batch_processing import discover_files, safe_output_directory
from conversion_report import (
    HashCancelled,
    build_report,
    report_path,
    sha256_file,
    write_report_atomic,
)
from conversion_results import (
    BatchSummary,
    FileResult,
    FrameResult,
    ResultStatus,
    safe_file_size,
)
from filename_normalization import collision_keys, output_filename, path_key
from output_policy import (
    OutputAction,
    OutputPolicy,
    cleanup_temporary,
    commit_output,
    plan_output,
)
from image_validation import (
    ImageValidationError,
    ImageWarning,
    ImageWarningCode,
    WarningSeverity,
    output_size_warnings,
    validate_image,
)
from image_resize import (
    ResizeConfig,
    ResizeMode,
    calculate_resize_dimensions,
    validate_resize_config,
)
from presets import (
    AUDIO_PRESETS,
    CUSTOM_PRESET_ID,
    IMAGE_PRESETS,
    VIDEO_PRESETS,
    AudioSettings,
    SettingsStore,
    preset_by_id,
    preset_matches,
)
from runtime_environment import diagnostics_text, resolve_ffmpeg
from summary_dialog import show_summary
from video_encoding import (
    VideoSettings,
    build_video_args,
    parse_progress_seconds,
    probe_media,
    validate_video_settings,
)
from webp_encoding import (
    WebPMode,
    resolve_webp_mode,
    webp_controls_visible,
    webp_save_options,
)


from PIL import Image, ImageOps, ImageSequence


FORMATOS_IMAGEN = {
    "WebP": ("WEBP", ".webp"),
    "JPEG": ("JPEG", ".jpg"),
    "PNG": ("PNG", ".png"),
    "TIFF": ("TIFF", ".tiff"),
    "BMP": ("BMP", ".bmp"),
    "GIF": ("GIF", ".gif"),
}
FORMATOS_AUDIO = {
    "MP3": ".mp3",
    "WAV": ".wav",
    "FLAC": ".flac",
    "OGG": ".ogg",
    "M4A": ".m4a",
    "Opus": ".opus",
}
FORMATOS_VIDEO = {
    "MP4": ".mp4",
    "MKV": ".mkv",
    "WebM": ".webm",
    "MOV": ".mov",
    "AVI": ".avi",
}
EXT_IMAGEN = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
EXT_AUDIO = {".mp3", ".wav", ".flac", ".ogg", ".oga", ".m4a", ".aac", ".opus", ".wma"}
EXT_VIDEO = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv", ".mpg", ".mpeg"}


def desired_output_path(
    output_root: Path,
    source_root: Path,
    source: Path,
    extension: str,
    normalize: bool,
) -> Path:
    directory = safe_output_directory(output_root, source_root, source)
    return directory / output_filename(source, extension, normalize)


def batch_name_collision_keys(
    output_root: Path,
    source_root: Path,
    sources: list[Path],
    extension: str,
    normalize: bool,
) -> set[str]:
    return collision_keys(
        [
            desired_output_path(output_root, source_root, source, extension, normalize)
            for source in sources
        ]
    )


class PanelConversor(ttk.Frame):
    """Controles compartidos por los tres tipos de conversión."""

    MEDIA_TYPE = "media"

    def __init__(
        self,
        parent,
        raiz: Tk,
        titulo: str,
        extensiones: set[str],
        formatos: dict[str, object],
    ) -> None:
        super().__init__(parent, padding=24)
        self.raiz, self.extensiones, self.formatos = raiz, extensiones, formatos
        self.seleccion, self.formato = (
            StringVar(),
            StringVar(value=next(iter(formatos))),
        )
        self.calidad, self.estado = (
            IntVar(value=85),
            StringVar(value="Selecciona un archivo o una carpeta."),
        )
        self.recursivo = BooleanVar(value=True)
        self.cancel_event = threading.Event()
        self.proceso_activo: subprocess.Popen[str] | None = None
        self.batch_started = 0.0
        self.files_discovered = 0
        self.last_summary: BatchSummary | None = None
        self.settings_store = SettingsStore()
        self.output_policy = StringVar(value=self.settings_store.load_output_policy())
        self.normalize_filenames = BooleanVar(
            value=self.settings_store.load_normalize_filenames()
        )
        self.output_name_preview = StringVar(
            value="Ejemplo: Character Happy.png → character_happy.webp"
        )
        self.generate_report = BooleanVar(
            value=self.settings_store.load_generate_report()
        )
        self.report_path_mode = StringVar(
            value=(
                "Absolutas"
                if self.settings_store.load_report_absolute_paths()
                else "Relativas"
            )
        )
        self.output_policy_help = StringVar()
        self._policy_by_display = {
            "Omitir": OutputPolicy.SKIP,
            "Sobrescribir de forma segura": OutputPolicy.OVERWRITE,
            "Crear un nombre único": OutputPolicy.UNIQUE,
            "Convertir si el origen es más reciente": OutputPolicy.SOURCE_NEWER,
        }
        self._policy_help = {
            OutputPolicy.SKIP: "Conserva cualquier destino existente (opción predeterminada).",
            OutputPolicy.OVERWRITE: "Reemplaza el destino solo después de convertir correctamente.",
            OutputPolicy.UNIQUE: "Conserva ambos archivos añadiendo _2, _3… al nombre.",
            OutputPolicy.SOURCE_NEWER: "Solo reemplaza si la fecha del origen es posterior.",
        }
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text=titulo, font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 18)
        )
        fila = ttk.Frame(self)
        fila.grid(row=1, column=0, sticky="ew")
        fila.columnconfigure(0, weight=1)
        ttk.Entry(fila, textvariable=self.seleccion, state="readonly").grid(
            row=0, column=0, sticky="ew", padx=(0, 10)
        )
        self.boton_archivo = ttk.Button(
            fila, text="Seleccionar archivo", command=self.seleccionar_archivo
        )
        self.boton_archivo.grid(row=0, column=1, padx=(0, 8))
        self.boton_carpeta = ttk.Button(
            fila, text="Seleccionar carpeta", command=self.seleccionar_carpeta
        )
        self.boton_carpeta.grid(row=0, column=2)

        self.opcion_recursiva = ttk.Checkbutton(
            self,
            text="Incluir subcarpetas (conservar estructura)",
            variable=self.recursivo,
        )
        self.opcion_recursiva.grid(row=2, column=0, sticky="w", pady=(14, 0))

        opciones = ttk.Frame(self)
        self.opciones_frame = opciones
        opciones.grid(row=3, column=0, sticky="ew", pady=16)
        opciones.columnconfigure(3, weight=1)
        ttk.Label(opciones, text="Formato de salida:").grid(
            row=0, column=0, padx=(0, 10)
        )
        self.selector_formato = ttk.Combobox(
            opciones,
            textvariable=self.formato,
            values=tuple(formatos),
            state="readonly",
            width=10,
        )
        self.selector_formato.grid(row=0, column=1, padx=(0, 22))
        ttk.Label(opciones, text="Calidad:").grid(row=0, column=2, padx=(0, 10))
        self.slider = ttk.Scale(
            opciones,
            from_=1,
            to=100,
            variable=self.calidad,
            command=lambda v: self.calidad.set(round(float(v))),
        )
        self.slider.grid(row=0, column=3, sticky="ew")
        ttk.Label(opciones, textvariable=self.calidad, width=4, anchor="e").grid(
            row=0, column=4, padx=(8, 0)
        )
        ttk.Label(opciones, text="Si el destino existe:").grid(
            row=2, column=0, padx=(0, 10), pady=(10, 0), sticky="w"
        )
        self.selector_policy = ttk.Combobox(
            opciones, values=tuple(self._policy_by_display), state="readonly", width=31
        )
        selected_policy_label = next(
            label
            for label, policy in self._policy_by_display.items()
            if policy.value == self.output_policy.get()
        )
        self.selector_policy.set(selected_policy_label)
        self.selector_policy.grid(
            row=2, column=1, padx=(0, 16), pady=(10, 0), sticky="w"
        )
        ttk.Label(opciones, textvariable=self.output_policy_help, wraplength=390).grid(
            row=2, column=2, columnspan=3, pady=(10, 0), sticky="w"
        )
        self.selector_policy.bind("<<ComboboxSelected>>", self.output_policy_changed)
        self.output_policy_help.set(
            self._policy_help[OutputPolicy(self.output_policy.get())]
        )
        self.normalize_check = ttk.Checkbutton(
            opciones,
            text="Normalizar nombres de salida",
            variable=self.normalize_filenames,
            command=self.normalize_filenames_changed,
        )
        self.normalize_check.grid(
            row=3, column=0, columnspan=2, pady=(10, 0), sticky="w"
        )
        ttk.Label(opciones, textvariable=self.output_name_preview, wraplength=470).grid(
            row=3, column=2, columnspan=3, pady=(10, 0), sticky="w"
        )
        self.formato.trace_add(
            "write", lambda *_args: self.update_output_name_preview()
        )
        self.report_check = ttk.Checkbutton(
            opciones,
            text="Generar informe JSON con SHA-256",
            variable=self.generate_report,
            command=self.report_settings_changed,
        )
        self.report_check.grid(row=4, column=0, columnspan=2, pady=(10, 0), sticky="w")
        ttk.Label(opciones, text="Rutas del informe:").grid(
            row=4, column=2, pady=(10, 0), sticky="e"
        )
        self.report_path_selector = ttk.Combobox(
            opciones,
            textvariable=self.report_path_mode,
            values=("Relativas", "Absolutas"),
            state="readonly",
            width=12,
        )
        self.report_path_selector.grid(row=4, column=3, pady=(10, 0), sticky="w")
        self.report_path_selector.bind(
            "<<ComboboxSelected>>", self.report_settings_changed
        )

        self.progreso = ttk.Progressbar(self, mode="determinate")
        self.progreso.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(self, textvariable=self.estado, wraplength=700).grid(
            row=5, column=0, sticky="w"
        )
        acciones = ttk.Frame(self)
        acciones.grid(row=6, column=0, sticky="e", pady=(20, 0))
        self.boton_cancelar = ttk.Button(
            acciones, text="Cancelar", command=self.cancelar, state="disabled"
        )
        self.boton_cancelar.grid(row=0, column=0, padx=(0, 8))
        self.boton_convertir = ttk.Button(
            acciones, text="Iniciar conversión", command=self.iniciar
        )
        self.boton_convertir.grid(row=0, column=1)

    def output_policy_changed(self, _event=None) -> None:
        policy = self._policy_by_display.get(
            self.selector_policy.get(), OutputPolicy.SKIP
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
        selected = Path(self.seleccion.get())
        if selected.is_file():
            format_value = self.formatos[self.formato.get()]
            extension = (
                format_value[1] if isinstance(format_value, tuple) else format_value
            )
            name = output_filename(selected, extension, self.normalize_filenames.get())
            self.output_name_preview.set(f"Nombre de salida: {name}")
        else:
            self.output_name_preview.set(
                "Ejemplo: Character Happy.png → character_happy.webp"
            )

    def report_settings_changed(self, _event=None) -> None:
        try:
            self.settings_store.save_generate_report(self.generate_report.get())
            self.settings_store.save_report_absolute_paths(
                self.report_path_mode.get() == "Absolutas"
            )
        except OSError:
            pass

    def archivos_en(self, carpeta: Path) -> list[Path]:
        return discover_files(carpeta, self.extensiones, self.recursivo.get()).files

    def seleccionar_archivo(self) -> None:
        patrones = " ".join(f"*{ext}" for ext in sorted(self.extensiones))
        ruta = filedialog.askopenfilename(
            title="Selecciona un archivo",
            filetypes=(("Archivos compatibles", patrones), ("Todos", "*.*")),
        )
        if ruta:
            self.seleccion.set(ruta)
            self.estado.set(f"Archivo seleccionado: {Path(ruta).name}")
            self.update_output_name_preview()

    def seleccionar_carpeta(self) -> None:
        ruta = filedialog.askdirectory(title="Selecciona una carpeta")
        if ruta:
            self.seleccion.set(ruta)
            self.estado.set(
                "Carpeta seleccionada. El contenido se descubrirá al iniciar."
            )
            self.update_output_name_preview()

    def iniciar(self) -> None:
        validation_error = self.validar_inicio()
        if validation_error:
            messagebox.showerror("Ajustes no válidos", validation_error)
            return
        elegido = Path(self.seleccion.get())
        if elegido.is_file() and elegido.suffix.lower() in self.extensiones:
            origen, archivos = elegido.parent, [elegido]
        elif elegido.is_dir():
            origen, archivos = elegido, None
        else:
            messagebox.showwarning(
                "Selección requerida",
                "Selecciona un archivo compatible o una carpeta válida.",
            )
            return

        self.cancel_event.clear()
        self.batch_started = time.monotonic()
        self.batch_started_at = datetime.now(timezone.utc)
        logging.getLogger(__name__).info("batch_start media=%s", type(self).__name__)
        self.bloquear(True)
        self.progreso.configure(mode="indeterminate", value=0)
        self.progreso.start(12)
        self.estado.set("Descubriendo archivos compatibles…")
        conversion_options = self.opciones_conversion()
        self.report_enabled = bool(conversion_options.get("generate_report", False))
        self.report_absolute = bool(
            conversion_options.get("report_absolute_paths", False)
        )
        self.report_source_root = origen
        self.report_output_format = self.formato.get()
        self.report_settings = {
            **conversion_options,
            "quality": self.calidad.get(),
            "recursive": self.recursivo.get(),
        }
        threading.Thread(
            target=self.preparar_lote,
            args=(
                origen,
                archivos,
                self.formato.get(),
                self.calidad.get(),
                self.recursivo.get(),
                conversion_options,
            ),
            daemon=True,
        ).start()

    def preparar_lote(
        self,
        origen: Path,
        archivos: list[Path] | None,
        formato: str,
        calidad: int,
        recursivo: bool,
        opciones: dict[str, object],
    ) -> None:
        errores_descubrimiento: list[str] = []
        if archivos is None:
            resultado = discover_files(
                origen, self.extensiones, recursivo, self.cancel_event
            )
            archivos = resultado.files
            errores_descubrimiento = resultado.errors
            if resultado.cancelled:
                self.raiz.after(0, self.conversion_cancelada, 0)
                return

        self.files_discovered = len(archivos)
        self.raiz.after(0, self.preparar_progreso_conversion, len(archivos))
        if not archivos:
            self.raiz.after(0, self.sin_archivos, errores_descubrimiento)
            return
        self.convertir_lote(
            origen, archivos, formato, calidad, errores_descubrimiento, opciones
        )

    def validar_inicio(self) -> str | None:
        return None

    def opciones_conversion(self) -> dict[str, object]:
        return {
            "output_policy": self.output_policy.get(),
            "normalize_filenames": self.normalize_filenames.get(),
            "generate_report": self.generate_report.get(),
            "report_absolute_paths": self.report_path_mode.get() == "Absolutas",
        }

    def preparar_progreso_conversion(self, total: int) -> None:
        self.progreso.stop()
        self.progreso.configure(mode="determinate", maximum=total, value=0)
        self.estado.set(f"Descubrimiento finalizado: {total} archivo(s). Convirtiendo…")

    def convertir_lote(
        self,
        origen: Path,
        archivos: list[Path],
        formato: str,
        calidad: int,
        errores_iniciales: list[str] | None = None,
        opciones: dict[str, object] | None = None,
    ) -> None:
        raise NotImplementedError

    def cancelar(self) -> None:
        self.cancel_event.set()
        self.estado.set("Cancelando operación…")
        proceso = self.proceso_activo
        if proceso is not None and proceso.poll() is None:
            proceso.terminate()

    def sin_archivos(self, errores: list[str]) -> None:
        self.progreso.stop()
        self.progreso.configure(mode="determinate", value=0)
        self.bloquear(False)
        detalle = "\n\nAvisos:\n" + "\n".join(errores[:5]) if errores else ""
        messagebox.showinfo(
            "Sin archivos", f"No se encontraron archivos compatibles.{detalle}"
        )

    def conversion_cancelada(self, convertidos: int) -> None:
        self.progreso.stop()
        self.bloquear(False)
        self.estado.set(f"Operación cancelada. {convertidos} archivo(s) convertido(s).")

    def notificar_avance(self, indice: int, total: int, nombre: str) -> None:
        self.raiz.after(0, self.estado.set, f"Convirtiendo {indice}/{total}: {nombre}")
        self.raiz.after(0, self.progreso.configure, {"value": indice})

    def bloquear(self, bloqueado: bool) -> None:
        estado = "disabled" if bloqueado else "normal"
        for boton in (
            self.boton_archivo,
            self.boton_carpeta,
            self.boton_convertir,
            self.slider,
        ):
            boton.configure(state=estado)
        self.selector_formato.configure(state="disabled" if bloqueado else "readonly")
        self.opcion_recursiva.configure(state=estado)
        self.boton_cancelar.configure(state="normal" if bloqueado else "disabled")
        self.selector_policy.configure(state="disabled" if bloqueado else "readonly")
        self.normalize_check.configure(state=estado)
        self.report_check.configure(state=estado)
        self.report_path_selector.configure(
            state="disabled" if bloqueado else "readonly"
        )

    def checksum_for_report(
        self, output: Path, enabled: bool
    ) -> tuple[str | None, tuple[str, ...]]:
        if not enabled:
            return None, ()
        try:
            checksum, warning = sha256_file(output, self.cancel_event)
        except HashCancelled:
            return None, ("SHA-256 cancelado; el archivo convertido se conserva.",)
        except OSError as error:
            return None, (f"No se pudo calcular SHA-256: {error}",)
        return checksum, (warning,) if warning else ()

    def finalizar_resultados(
        self,
        destino: Path,
        resultados: list[FileResult],
        errores_descubrimiento: list[str],
        cancelled: bool = False,
    ) -> None:
        summary = BatchSummary(
            files_discovered=self.files_discovered,
            results=tuple(resultados),
            elapsed_seconds=time.monotonic() - self.batch_started,
            cancelled=cancelled,
            discovery_errors=tuple(errores_descubrimiento),
        )
        if getattr(self, "report_enabled", False):
            self.estado.set("Generando informe JSON…")
            threading.Thread(
                target=self.generar_informe,
                args=(destino, summary),
                daemon=True,
            ).start()
            return
        self.mostrar_resultados(destino, summary, None)

    def generar_informe(self, destino: Path, summary: BatchSummary) -> None:
        completed_at = datetime.now(timezone.utc)
        generated_path = None
        try:
            report = build_report(
                summary,
                self.report_source_root,
                destino,
                self.MEDIA_TYPE,
                self.report_output_format,
                self.report_settings,
                self.batch_started_at,
                completed_at,
                self.report_absolute,
            )
            generated_path = report_path(destino, completed_at)
            write_report_atomic(generated_path, report)
        except Exception as error:
            generated_path = None
            warning = f"No se pudo escribir el informe JSON: {error}"
            summary = replace(summary, operation_warnings=(warning,))
        self.raiz.after(0, self.mostrar_resultados, destino, summary, generated_path)

    def mostrar_resultados(
        self, destino: Path, summary: BatchSummary, generated_report: Path | None
    ) -> None:
        self.last_summary = summary
        self.bloquear(False)
        self.estado.set(
            f"Finalizado: {summary.converted} convertido(s), {summary.skipped} omitido(s), "
            f"{summary.failed} fallido(s)."
        )
        logging.getLogger(__name__).info(
            "batch_complete discovered=%d processed=%d converted=%d skipped=%d failed=%d elapsed=%.3f cancelled=%s",
            summary.files_discovered,
            summary.files_processed,
            summary.converted,
            summary.skipped,
            summary.failed,
            summary.elapsed_seconds,
            summary.cancelled,
        )
        if summary.operation_warnings:
            messagebox.showwarning(
                "Informe no generado", "\n".join(summary.operation_warnings)
            )
        show_summary(self.raiz, summary, destino, generated_report)

    def completar(self, destino: Path, exitos: int, errores: list[str]) -> None:
        self.bloquear(False)
        if errores:
            self.estado.set(
                f"Finalizado: {exitos} convertido(s), {len(errores)} con error."
            )
            resumen = "\n".join(f"• {error}" for error in errores[:8])
            if len(errores) > 8:
                resumen += f"\n• ...y {len(errores) - 8} error(es) más."
            messagebox.showwarning(
                "Conversión finalizada con avisos",
                f"Archivos guardados en:\n{destino}\n\nNo se pudieron convertir:\n{resumen}",
            )
        else:
            self.estado.set(f"Conversión completada: {exitos} archivo(s).")
            messagebox.showinfo(
                "Conversión completada", f"Archivos guardados en:\n{destino}"
            )

    def fallar(self, detalle: str) -> None:
        self.bloquear(False)
        self.estado.set("La conversión se interrumpió debido a un error.")
        messagebox.showerror("Error de conversión", detalle)


class PanelImagen(PanelConversor):
    MEDIA_TYPE = "image"
    WEBP_HELP = {
        WebPMode.AUTOMATIC.value: "Automático elige por imagen entre tamaño reducido y fidelidad exacta.",
        WebPMode.LOSSY.value: "Con pérdida reduce más el tamaño y conserva la transparencia.",
        WebPMode.LOSSLESS.value: "Sin pérdida conserva exactamente los píxeles; la calidad no se aplica.",
    }

    def __init__(self, parent, raiz: Tk) -> None:
        super().__init__(
            parent, raiz, "Conversor de imágenes", EXT_IMAGEN, FORMATOS_IMAGEN
        )
        self.webp_mode = StringVar(value=WebPMode.AUTOMATIC.value)
        self.animation_mode = StringVar(value=self.settings_store.load_animation_mode())
        self.webp_help = StringVar()
        self.modos_seleccionados: dict[Path, WebPMode] = {}
        self._bloqueado = False
        self.settings_store = SettingsStore()
        self._applying_preset = False
        self.preset_description = StringVar(value="Ajustes elegidos manualmente.")
        self.preset_display = StringVar(value="Personalizado")
        self._preset_ids_by_display = {
            preset.display_name: preset.preset_id for preset in IMAGE_PRESETS
        }
        self.resize_mode = StringVar(value=ResizeMode.ORIGINAL.value)
        self.resize_width = StringVar(value="1024")
        self.resize_height = StringVar(value="1024")
        self.resize_percentage = StringVar(value="50")
        self.never_upscale = BooleanVar(value=True)
        self.resize_preview = StringVar(
            value="Se conservarán las dimensiones originales."
        )
        self._resize_modes_by_display = {
            "Conservar dimensiones": ResizeMode.ORIGINAL,
            "Anchura máxima": ResizeMode.MAX_WIDTH,
            "Altura máxima": ResizeMode.MAX_HEIGHT,
            "Ajustar dentro de dimensiones": ResizeMode.FIT,
            "Escalar por porcentaje": ResizeMode.PERCENT,
        }

        ttk.Label(self.opciones_frame, text="Preset:").grid(
            row=1, column=0, padx=(0, 10), pady=(10, 0), sticky="w"
        )
        self.selector_preset = ttk.Combobox(
            self.opciones_frame,
            textvariable=self.preset_display,
            values=(
                "Personalizado",
                *(preset.display_name for preset in IMAGE_PRESETS),
            ),
            state="readonly",
            width=28,
        )
        self.selector_preset.grid(
            row=1, column=1, padx=(0, 16), pady=(10, 0), sticky="w"
        )
        ttk.Label(
            self.opciones_frame, textvariable=self.preset_description, wraplength=390
        ).grid(row=1, column=2, columnspan=3, pady=(10, 0), sticky="w")
        self.selector_preset.bind(
            "<<ComboboxSelected>>", self.aplicar_preset_seleccionado
        )

        self.formato.trace_add("write", self.ajustes_modificados)
        self.calidad.trace_add("write", self.ajustes_modificados)
        self.webp_mode.trace_add("write", self.ajustes_modificados)
        for row in range(6, 3, -1):
            for widget in self.grid_slaves(row=row):
                widget.grid_configure(row=row + 1)

        self.marco_webp = ttk.LabelFrame(self, text="Modo WebP", padding=(10, 6))
        self.marco_webp.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        for column, (text, mode) in enumerate(
            (
                ("Automático", WebPMode.AUTOMATIC),
                ("Con pérdida", WebPMode.LOSSY),
                ("Sin pérdida", WebPMode.LOSSLESS),
            )
        ):
            ttk.Radiobutton(
                self.marco_webp,
                text=text,
                value=mode.value,
                variable=self.webp_mode,
                command=self.actualizar_controles_webp,
            ).grid(row=0, column=column, padx=(0, 14), sticky="w")
        ttk.Label(self.marco_webp, textvariable=self.webp_help, wraplength=680).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(5, 0)
        )
        self.selector_formato.bind(
            "<<ComboboxSelected>>", self.actualizar_controles_webp
        )
        for row in range(7, 4, -1):
            for widget in self.grid_slaves(row=row):
                widget.grid_configure(row=row + 1)
        self.marco_resize = ttk.LabelFrame(self, text="Redimensionar", padding=(10, 7))
        self.marco_resize.grid(row=5, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(self.marco_resize, text="Modo:").grid(row=0, column=0, padx=(0, 8))
        self.selector_resize = ttk.Combobox(
            self.marco_resize,
            values=tuple(self._resize_modes_by_display),
            state="readonly",
            width=29,
        )
        self.selector_resize.set("Conservar dimensiones")
        self.selector_resize.grid(row=0, column=1, padx=(0, 14), sticky="w")
        self.label_width = ttk.Label(self.marco_resize, text="Anchura (px):")
        self.entry_width = ttk.Entry(
            self.marco_resize, textvariable=self.resize_width, width=9
        )
        self.label_height = ttk.Label(self.marco_resize, text="Altura (px):")
        self.entry_height = ttk.Entry(
            self.marco_resize, textvariable=self.resize_height, width=9
        )
        self.label_percent = ttk.Label(self.marco_resize, text="Porcentaje (%):")
        self.entry_percent = ttk.Entry(
            self.marco_resize, textvariable=self.resize_percentage, width=9
        )
        self.never_upscale_check = ttk.Checkbutton(
            self.marco_resize,
            text="Nunca ampliar imágenes pequeñas",
            variable=self.never_upscale,
        )
        self.never_upscale_check.grid(row=1, column=4, padx=(12, 0), sticky="w")
        ttk.Label(
            self.marco_resize, textvariable=self.resize_preview, wraplength=700
        ).grid(row=2, column=0, columnspan=6, sticky="w", pady=(6, 0))
        self.selector_resize.bind("<<ComboboxSelected>>", self.resize_mode_changed)
        for variable in (
            self.resize_width,
            self.resize_height,
            self.resize_percentage,
            self.never_upscale,
        ):
            variable.trace_add("write", self.resize_settings_changed)
        self.actualizar_controles_resize()
        self.aplicar_preset_id(self.settings_store.load_last_image_preset())
        for row in range(8, 5, -1):
            for widget in self.grid_slaves(row=row):
                widget.grid_configure(row=row + 1)
        self.animation_frame = ttk.LabelFrame(
            self, text="Tratamiento de animaciones", padding=(10, 7)
        )
        self.animation_frame.grid(row=6, column=0, sticky="ew", pady=(0, 12))
        for column, (label, mode) in enumerate(
            (
                ("Conservar animación", AnimationMode.PRESERVE),
                ("Extraer fotogramas", AnimationMode.EXTRACT_FRAMES),
                ("Solo primer fotograma", AnimationMode.FIRST_FRAME),
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
            text="La política se aplica globalmente a las animaciones del lote.",
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
        selected = Path(self.seleccion.get())
        if not selected.is_file():
            return False
        try:
            with Image.open(selected) as image:
                return bool(getattr(image, "is_animated", False) and image.n_frames > 1)
        except OSError:
            return False

    def update_animation_controls(self) -> None:
        selected = Path(self.seleccion.get())
        relevant = selected.is_dir() or self.selected_file_is_animated()
        if relevant:
            self.animation_frame.grid()
            mode = AnimationMode(self.animation_mode.get())
            if mode is AnimationMode.PRESERVE:
                output_format = FORMATOS_IMAGEN[self.formato.get()][0]
                supported = animation_supported(output_format)
                self.animation_help.configure(
                    text=(
                        "El formato elegido admite animación."
                        if supported
                        else "El formato elegido no admite animación; elige extraer o usar el primer fotograma."
                    )
                )
            elif mode is AnimationMode.EXTRACT_FRAMES:
                self.animation_help.configure(
                    text="Se creará una carpeta nueva con todos los fotogramas numerados."
                )
            else:
                self.animation_help.configure(
                    text="Se convertirá explícitamente el fotograma 0 y se registrará el descarte."
                )
        else:
            self.animation_frame.grid_remove()

    def resize_mode_changed(self, _event=None) -> None:
        self.resize_mode.set(
            self._resize_modes_by_display.get(
                self.selector_resize.get(), ResizeMode.ORIGINAL
            ).value
        )
        self.actualizar_controles_resize()
        self.ajustes_modificados()

    def resize_settings_changed(self, *_args) -> None:
        if hasattr(self, "marco_resize"):
            self.actualizar_preview_resize()
            self.ajustes_modificados()

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

    def actualizar_controles_resize(self) -> None:
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
        self.actualizar_preview_resize()

    def actualizar_preview_resize(self) -> None:
        selected = Path(self.seleccion.get())
        if selected.is_dir():
            self.resize_preview.set(
                "El tamaño se calculará individualmente para cada imagen del lote."
            )
            return
        if not selected.is_file():
            self.resize_preview.set(
                "Selecciona una imagen para estimar el tamaño final."
            )
            return
        try:
            config = self.current_resize_config()
            validate_resize_config(config)
            with Image.open(selected) as image:
                oriented = ImageOps.exif_transpose(image)
                target = calculate_resize_dimensions(*oriented.size, config)
                self.resize_preview.set(
                    f"Original orientada: {oriented.width} × {oriented.height}. "
                    f"Salida estimada: {target[0]} × {target[1]}."
                )
        except (OSError, ValueError) as error:
            self.resize_preview.set(f"Ajuste pendiente: {error}")

    def seleccionar_archivo(self) -> None:
        super().seleccionar_archivo()
        self.actualizar_preview_resize()

    def seleccionar_carpeta(self) -> None:
        super().seleccionar_carpeta()
        self.actualizar_preview_resize()

    def aplicar_preset_seleccionado(self, _event=None) -> None:
        preset_id = self._preset_ids_by_display.get(
            self.preset_display.get(), CUSTOM_PRESET_ID
        )
        self.aplicar_preset_id(preset_id)

    def aplicar_preset_id(self, preset_id: str) -> None:
        preset = preset_by_id(preset_id)
        self._applying_preset = True
        try:
            if preset is None:
                self.preset_display.set("Personalizado")
                self.preset_description.set("Ajustes elegidos manualmente.")
                selected_id = CUSTOM_PRESET_ID
            else:
                self.preset_display.set(preset.display_name)
                self.preset_description.set(preset.description)
                self.formato.set(preset.output_format)
                if preset.quality is not None:
                    self.calidad.set(preset.quality)
                if preset.webp_mode is not None:
                    self.webp_mode.set(preset.webp_mode.value)
                self.resize_mode.set(preset.resize_mode)
                resize_label = next(
                    label
                    for label, mode in self._resize_modes_by_display.items()
                    if mode.value == preset.resize_mode
                )
                self.selector_resize.set(resize_label)
                selected_id = preset.preset_id
        finally:
            self._applying_preset = False
        self.actualizar_controles_webp()
        try:
            self.settings_store.save_last_image_preset(selected_id)
        except OSError:
            pass

    def ajustes_modificados(self, *_args) -> None:
        if self._applying_preset:
            return
        current_id = self._preset_ids_by_display.get(self.preset_display.get())
        current = preset_by_id(current_id)
        if current and preset_matches(
            current,
            self.formato.get(),
            self.calidad.get(),
            self.webp_mode.get(),
            self.resize_mode.get(),
        ):
            return
        self.preset_display.set("Personalizado")
        self.preset_description.set("Ajustes modificados manualmente.")
        try:
            self.settings_store.save_last_image_preset(CUSTOM_PRESET_ID)
        except OSError:
            pass

    def actualizar_controles_webp(self, _event=None) -> None:
        visible = webp_controls_visible(self.formato.get())
        if visible:
            self.marco_webp.grid()
            self.webp_help.set(self.WEBP_HELP[self.webp_mode.get()])
        else:
            self.marco_webp.grid_remove()
        if hasattr(self, "animation_frame"):
            self.update_animation_controls()
        calidad_aplicable = not (
            visible and self.webp_mode.get() == WebPMode.LOSSLESS.value
        )
        self.slider.configure(
            state="normal" if calidad_aplicable and not self._bloqueado else "disabled"
        )

    def validar_inicio(self) -> str | None:
        try:
            validate_resize_config(self.current_resize_config())
        except ValueError as error:
            return str(error)
        if (
            self.selected_file_is_animated()
            and AnimationMode(self.animation_mode.get()) is AnimationMode.PRESERVE
            and not animation_supported(FORMATOS_IMAGEN[self.formato.get()][0])
        ):
            return (
                "El formato elegido no puede conservar animación. "
                "Selecciona Extraer fotogramas o Solo primer fotograma."
            )
        return None

    def opciones_conversion(self) -> dict[str, object]:
        return {
            "webp_mode": self.webp_mode.get(),
            "resize_config": self.current_resize_config(),
            "output_policy": self.output_policy.get(),
            "normalize_filenames": self.normalize_filenames.get(),
            "generate_report": self.generate_report.get(),
            "report_absolute_paths": self.report_path_mode.get() == "Absolutas",
            "animation_mode": self.animation_mode.get(),
        }

    def bloquear(self, bloqueado: bool) -> None:
        self._bloqueado = bloqueado
        super().bloquear(bloqueado)
        self.selector_preset.configure(state="disabled" if bloqueado else "readonly")
        self.selector_resize.configure(state="disabled" if bloqueado else "readonly")
        animation_state = "disabled" if bloqueado else "normal"
        for child in self.animation_frame.winfo_children():
            if isinstance(child, ttk.Radiobutton):
                child.configure(state=animation_state)
        state = "disabled" if bloqueado else "normal"
        for widget in (
            self.entry_width,
            self.entry_height,
            self.entry_percent,
            self.never_upscale_check,
        ):
            widget.configure(state=state)
        self.actualizar_controles_webp()

    @staticmethod
    def preparar_estatica(
        imagen: Image.Image,
        formato: str,
        calidad: int,
        source: Path | str = "image.png",
        requested_webp_mode: WebPMode | str = WebPMode.AUTOMATIC,
    ) -> tuple[Image.Image, dict[str, object], WebPMode | None]:
        convertida = imagen.convert("RGBA")
        save_options: dict[str, object] = {}
        resolved_mode: WebPMode | None = None
        if formato == "JPEG":
            fondo = Image.new("RGB", convertida.size, "white")
            fondo.paste(convertida, mask=convertida.getchannel("A"))
            convertida = fondo
            save_options = {"quality": calidad, "optimize": True, "progressive": True}
        elif formato == "WEBP":
            resolved_mode = resolve_webp_mode(requested_webp_mode, imagen, source)
            save_options = webp_save_options(resolved_mode, calidad)
        elif formato == "PNG":
            save_options = {"optimize": True, "compress_level": 9}
        elif formato == "TIFF":
            save_options = {"compression": "tiff_deflate"}
        elif formato == "GIF":
            save_options = {"optimize": True}
        return convertida, save_options, resolved_mode

    @staticmethod
    def resize_frame(
        image: Image.Image, config: ResizeConfig, target: tuple[int, int] | None = None
    ) -> tuple[Image.Image, tuple[int, int]]:
        oriented = ImageOps.exif_transpose(image)
        target = target or calculate_resize_dimensions(*oriented.size, config)
        if oriented.size == target:
            return oriented, target
        return oriented.resize(target, Image.Resampling.LANCZOS), target

    def guardar_imagen(
        self,
        imagen: Image.Image,
        salida: Path,
        formato: str,
        calidad: int,
        source: Path | str | None = None,
        requested_webp_mode: WebPMode | str = WebPMode.AUTOMATIC,
        resize_config: ResizeConfig | None = None,
        animation_durations: tuple[int, ...] = (),
    ) -> WebPMode | None:
        source = source or salida
        resize_config = resize_config or ResizeConfig()
        es_animada = getattr(imagen, "is_animated", False) and animation_supported(
            formato
        )
        if not es_animada:
            imagen.seek(0)
            resized, _target = self.resize_frame(imagen, resize_config)
            convertida, save_options, resolved_mode = self.preparar_estatica(
                resized, formato, calidad, source, requested_webp_mode
            )
            convertida.save(salida, format=formato, **save_options)
            return resolved_mode

        resolved_mode: WebPMode | None = None
        if formato == "WEBP":
            resolved_mode = resolve_webp_mode(requested_webp_mode, imagen, source)
        frames: list[Image.Image] = []
        durations: list[int] = []
        target: tuple[int, int] | None = None
        for frame_index, frame in enumerate(ImageSequence.Iterator(imagen)):
            resized, target = self.resize_frame(
                frame.convert("RGBA"), resize_config, target
            )
            frames.append(resized.convert("RGBA"))
            durations.append(
                animation_durations[frame_index]
                if frame_index < len(animation_durations)
                else frame.info.get("duration", imagen.info.get("duration", 100))
            )

        save_options: dict[str, object] = {
            "save_all": True,
            "append_images": frames[1:],
            "duration": durations,
            "loop": imagen.info.get("loop", 0),
        }
        if formato in {"GIF", "PNG"}:
            save_options["disposal"] = [
                getattr(frame, "disposal_method", frame.info.get("disposal", 0))
                for frame in ImageSequence.Iterator(imagen)
            ]
        if formato == "WEBP":
            save_options.update(webp_save_options(resolved_mode, calidad))
        else:
            save_options["optimize"] = True
        frames[0].save(salida, format=formato, **save_options)
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
        formato: str,
        extension: str,
        calidad: int,
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
            if formato == "WEBP"
            else None
        )
        width = frame_number_width(image.n_frames)
        try:
            for index, frame in enumerate(ImageSequence.Iterator(image), 1):
                if self.cancel_event.is_set():
                    raise InterruptedError("Extracción de fotogramas cancelada.")
                duration = int(
                    frame.info.get("duration", image.info.get("duration", 100))
                )
                resized, target_size = self.resize_frame(
                    frame.convert("RGBA"), resize_config, target_size
                )
                output = directory / f"frame_{index:0{width}d}{extension}"
                plan = plan_output(source, output, OutputPolicy.OVERWRITE)
                try:
                    self.guardar_imagen(
                        resized,
                        plan.temporary,
                        formato,
                        calidad,
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

    def convertir_lote(
        self,
        origen: Path,
        archivos: list[Path],
        elegido: str,
        calidad: int,
        errores_iniciales: list[str] | None = None,
        opciones: dict[str, object] | None = None,
    ) -> None:
        formato, extension = FORMATOS_IMAGEN[elegido]
        requested_mode = (opciones or {}).get("webp_mode", WebPMode.AUTOMATIC.value)
        resize_config = (opciones or {}).get("resize_config", ResizeConfig())
        policy = OutputPolicy((opciones or {}).get("output_policy", OutputPolicy.SKIP))
        normalize = bool((opciones or {}).get("normalize_filenames", False))
        generate_report = bool((opciones or {}).get("generate_report", False))
        animation_policy = AnimationMode(
            (opciones or {}).get("animation_mode", AnimationMode.PRESERVE)
        )
        destino = origen / f"convertidos_{elegido.lower()}"
        discovery_errors = list(errores_iniciales or [])
        results: list[FileResult] = []
        name_collisions = batch_name_collision_keys(
            destino, origen, archivos, extension, normalize
        )
        self.modos_seleccionados = {}

        for indice, archivo in enumerate(archivos, 1):
            if self.cancel_event.is_set():
                self.raiz.after(
                    0,
                    self.finalizar_resultados,
                    destino,
                    results,
                    discovery_errors,
                    True,
                )
                return
            self.raiz.after(
                0,
                self.estado.set,
                f"Convirtiendo {indice}/{len(archivos)}: {archivo.name}",
            )
            started = time.monotonic()
            original_bytes = safe_file_size(archivo)
            plan = None
            collision = False
            validation_warnings: tuple[ImageWarning | str, ...] = ()
            try:
                desired = desired_output_path(
                    destino, origen, archivo, extension, normalize
                )
                desired.parent.mkdir(parents=True, exist_ok=True)
                collision = path_key(desired) in name_collisions
                validation_warnings = tuple(validate_image(archivo, formato))
                blocking = [
                    warning for warning in validation_warnings if warning.blocking
                ]
                if blocking:
                    raise ImageValidationError(list(validation_warnings))

                with Image.open(archivo) as probe:
                    is_animated = bool(
                        getattr(probe, "is_animated", False) and probe.n_frames > 1
                    )
                    frame_count = probe.n_frames if is_animated else None
                    animation_loop = (
                        int(probe.info.get("loop", 0)) if is_animated else None
                    )
                    frame_durations = (
                        tuple(
                            int(
                                frame.info.get(
                                    "duration", probe.info.get("duration", 100)
                                )
                            )
                            for frame in ImageSequence.Iterator(probe)
                        )
                        if is_animated
                        else ()
                    )
                    source_width, source_height = probe.size
                    if is_animated and probe.format == "WEBP":
                        parsed_durations = webp_frame_durations(archivo)
                        if len(parsed_durations) == frame_count:
                            frame_durations = parsed_durations

                if is_animated and animation_policy is not AnimationMode.PRESERVE:
                    validation_warnings = tuple(
                        warning
                        for warning in validation_warnings
                        if not isinstance(warning, ImageWarning)
                        or warning.code is not ImageWarningCode.ANIMATION_MAY_BE_LOST
                    )

                if is_animated and animation_policy is AnimationMode.EXTRACT_FRAMES:
                    with Image.open(archivo) as animation:
                        frame_root, frames, checksum_warnings, resolved_mode = (
                            self.extract_animation_frames(
                                animation,
                                archivo,
                                desired,
                                formato,
                                extension,
                                calidad,
                                requested_mode,
                                resize_config,
                                generate_report,
                                frame_durations,
                            )
                        )
                    output_bytes = sum(frame.output_bytes for frame in frames)
                    output_width, output_height = calculate_resize_dimensions(
                        source_width, source_height, resize_config
                    )
                    extraction_warning = self.animation_warning(
                        ImageWarningCode.FRAMES_EXTRACTED,
                        WarningSeverity.INFORMATION,
                        f"Se extrajeron {len(frames)} fotogramas.",
                        archivo,
                        frameCount=len(frames),
                        durationsMs=[frame.duration_ms for frame in frames],
                    )
                    size_warnings = tuple(
                        output_size_warnings(archivo, original_bytes, output_bytes)
                    )
                    results.append(
                        FileResult(
                            archivo,
                            frame_root,
                            ResultStatus.CONVERTED,
                            original_bytes,
                            output_bytes,
                            processing_seconds=time.monotonic() - started,
                            encoder_mode=(
                                resolved_mode.value if resolved_mode else None
                            ),
                            output_action=(
                                OutputAction.RENAME.value
                                if frame_root.name != f"{desired.stem}_frames"
                                else OutputAction.CONVERT.value
                            ),
                            name_collision=collision,
                            warnings=validation_warnings
                            + (extraction_warning,)
                            + size_warnings
                            + checksum_warnings,
                            width=source_width,
                            height=source_height,
                            output_width=output_width,
                            output_height=output_height,
                            quality=(
                                None if resolved_mode is WebPMode.LOSSLESS else calidad
                            ),
                            animation_mode=animation_policy.value,
                            frame_count=frame_count,
                            animation_loop=animation_loop,
                            frame_durations_ms=frame_durations,
                            frames=frames,
                        )
                    )
                    self.notificar_avance(indice, len(archivos), archivo.name)
                    continue

                if (
                    is_animated
                    and animation_policy is AnimationMode.PRESERVE
                    and not animation_supported(formato)
                ):
                    unsupported = self.animation_warning(
                        ImageWarningCode.ANIMATED_DESTINATION_UNSUPPORTED,
                        WarningSeverity.BLOCKING_ERROR,
                        "El formato elegido no puede conservar la animación; selecciona un fallback explícito.",
                        archivo,
                        targetFormat=formato,
                    )
                    raise ImageValidationError([*validation_warnings, unsupported])

                plan = plan_output(archivo, desired, policy)
                if not plan.should_convert:
                    results.append(
                        FileResult(
                            archivo,
                            plan.target,
                            ResultStatus.SKIPPED,
                            original_bytes,
                            error_message=(
                                "El destino ya existe."
                                if plan.action is OutputAction.SKIP_EXISTS
                                else "El destino está actualizado."
                            ),
                            processing_seconds=time.monotonic() - started,
                            output_action=plan.action.value,
                            name_collision=collision,
                            warnings=validation_warnings,
                        )
                    )
                    self.notificar_avance(indice, len(archivos), archivo.name)
                    continue

                if is_animated and animation_policy is AnimationMode.FIRST_FRAME:
                    discarded = self.animation_warning(
                        ImageWarningCode.ANIMATION_INTENTIONALLY_DISCARDED,
                        WarningSeverity.WARNING,
                        "Se convirtió explícitamente solo el primer fotograma.",
                        archivo,
                        discardedFrames=(frame_count or 1) - 1,
                    )
                    validation_warnings += (discarded,)

                with Image.open(archivo) as image:
                    oriented = ImageOps.exif_transpose(image)
                    source_width, source_height = oriented.size
                    output_width, output_height = calculate_resize_dimensions(
                        source_width, source_height, resize_config
                    )
                    image_to_save = image
                    if is_animated and animation_policy is AnimationMode.FIRST_FRAME:
                        image.seek(0)
                        image_to_save = image.convert("RGBA")
                    resolved_mode = self.guardar_imagen(
                        image_to_save,
                        plan.temporary,
                        formato,
                        calidad,
                        archivo,
                        requested_mode,
                        resize_config,
                        frame_durations,
                    )
                commit_output(plan)
                output_bytes = safe_file_size(plan.target)
                size_warnings = tuple(
                    output_size_warnings(archivo, original_bytes, output_bytes)
                )
                checksum, checksum_warnings = self.checksum_for_report(
                    plan.target, generate_report
                )
                if resolved_mode is not None:
                    self.modos_seleccionados[archivo] = resolved_mode
                reported_quality = (
                    None
                    if formato == "WEBP" and resolved_mode is WebPMode.LOSSLESS
                    else calidad
                )
                results.append(
                    FileResult(
                        archivo,
                        plan.target,
                        ResultStatus.CONVERTED,
                        original_bytes,
                        output_bytes,
                        processing_seconds=time.monotonic() - started,
                        encoder_mode=resolved_mode.value if resolved_mode else None,
                        output_action=plan.action.value,
                        name_collision=collision,
                        warnings=validation_warnings
                        + size_warnings
                        + checksum_warnings,
                        width=source_width,
                        height=source_height,
                        output_width=output_width,
                        output_height=output_height,
                        quality=reported_quality,
                        sha256=checksum,
                        animation_mode=(
                            animation_policy.value if is_animated else None
                        ),
                        frame_count=frame_count,
                        animation_loop=animation_loop,
                        frame_durations_ms=frame_durations,
                    )
                )
            except Exception as error:
                cleanup_temporary(plan)
                if isinstance(error, ImageValidationError):
                    validation_warnings = error.warnings
                if isinstance(error, InterruptedError) and self.cancel_event.is_set():
                    self.raiz.after(
                        0,
                        self.finalizar_resultados,
                        destino,
                        results,
                        discovery_errors,
                        True,
                    )
                    return
                results.append(
                    FileResult(
                        archivo,
                        None,
                        ResultStatus.FAILED,
                        original_bytes,
                        error_message=str(error),
                        processing_seconds=time.monotonic() - started,
                        name_collision=collision,
                        warnings=validation_warnings,
                    )
                )
            self.notificar_avance(indice, len(archivos), archivo.name)
        self.raiz.after(0, self.estado.set, "Finalizando lote…")
        self.raiz.after(
            0,
            self.finalizar_resultados,
            destino,
            results,
            discovery_errors,
            self.cancel_event.is_set(),
        )


class PanelAudio(PanelConversor):
    MEDIA_TYPE = "audio"

    def __init__(self, parent, raiz: Tk) -> None:
        super().__init__(parent, raiz, "Conversor de audio", EXT_AUDIO, FORMATOS_AUDIO)
        self._applying_audio_preset = False
        self.audio_preset_display = StringVar(value="Personalizado")
        self.audio_preset_description = StringVar(value="Ajustes de audio manuales.")
        self.audio_sample_rate = StringVar(value="Preservar")
        self.audio_channels = StringVar(value="Preservar")
        self.audio_bitrate = StringVar(value="192")
        self._audio_preset_ids = {
            preset.display_name: preset.preset_id for preset in AUDIO_PRESETS
        }

        ttk.Label(self.opciones_frame, text="Preset de audio:").grid(
            row=1, column=0, padx=(0, 10), pady=(10, 0), sticky="w"
        )
        self.audio_preset_selector = ttk.Combobox(
            self.opciones_frame,
            textvariable=self.audio_preset_display,
            values=(
                "Personalizado",
                *(preset.display_name for preset in AUDIO_PRESETS),
            ),
            state="readonly",
            width=28,
        )
        self.audio_preset_selector.grid(
            row=1, column=1, padx=(0, 16), pady=(10, 0), sticky="w"
        )
        ttk.Label(
            self.opciones_frame,
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
            self, text="Ajustes de audio", padding=(10, 7)
        )
        self.audio_advanced.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(self.audio_advanced, text="Frecuencia:").grid(row=0, column=0)
        self.audio_sample_selector = ttk.Combobox(
            self.audio_advanced,
            textvariable=self.audio_sample_rate,
            values=("Preservar", "44100", "48000"),
            state="readonly",
            width=11,
        )
        self.audio_sample_selector.grid(row=0, column=1, padx=(8, 20))
        ttk.Label(self.audio_advanced, text="Canales:").grid(row=0, column=2)
        self.audio_channel_selector = ttk.Combobox(
            self.audio_advanced,
            textvariable=self.audio_channels,
            values=("Preservar", "Mono", "Estéreo"),
            state="readonly",
            width=11,
        )
        self.audio_channel_selector.grid(row=0, column=3, padx=(8, 20))
        ttk.Label(self.audio_advanced, text="Bitrate (kbps):").grid(row=0, column=4)
        self.audio_bitrate_entry = ttk.Entry(
            self.audio_advanced, textvariable=self.audio_bitrate, width=7
        )
        self.audio_bitrate_entry.grid(row=0, column=5, padx=(8, 0))
        ttk.Label(
            self.audio_advanced,
            text="Sin normalización de sonoridad; se conserva la duración completa.",
        ).grid(row=1, column=0, columnspan=6, pady=(6, 0), sticky="w")

        for variable in (
            self.formato,
            self.calidad,
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
            self.audio_preset_display.set("Personalizado")
            self.audio_preset_description.set("Ajustes de audio manuales.")
            selected_id = CUSTOM_PRESET_ID
        else:
            settings = preset.audio_settings
            self._applying_audio_preset = True
            try:
                self.audio_preset_display.set(preset.display_name)
                self.audio_preset_description.set(preset.description)
                self.formato.set(preset.output_format)
                self.audio_sample_rate.set(
                    str(settings.sample_rate) if settings.sample_rate else "Preservar"
                )
                self.audio_channels.set(
                    {None: "Preservar", 1: "Mono", 2: "Estéreo"}[settings.channels]
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
        self.audio_preset_display.set("Personalizado")
        self.audio_preset_description.set("Ajustes de audio modificados manualmente.")
        try:
            self.settings_store.save_last_audio_preset(CUSTOM_PRESET_ID)
        except OSError:
            pass

    def current_audio_settings(self) -> AudioSettings:
        sample_rate = (
            None
            if self.audio_sample_rate.get() == "Preservar"
            else int(self.audio_sample_rate.get())
        )
        channels = {"Preservar": None, "Mono": 1, "Estéreo": 2}[
            self.audio_channels.get()
        ]
        bitrate_text = self.audio_bitrate.get().strip()
        bitrate = int(bitrate_text) if bitrate_text else None
        return manual_audio_settings(
            self.formato.get(),
            self.calidad.get(),
            sample_rate,
            channels,
            bitrate,
        )

    def validar_inicio(self) -> str | None:
        try:
            validate_audio_settings(self.formato.get(), self.current_audio_settings())
        except (KeyError, ValueError, NotImplementedError) as error:
            return str(error)
        return None

    def opciones_conversion(self) -> dict[str, object]:
        options = super().opciones_conversion()
        options["audio_settings"] = self.current_audio_settings()
        options["audio_preset"] = self._audio_preset_ids.get(
            self.audio_preset_display.get(), CUSTOM_PRESET_ID
        )
        return options

    def bloquear(self, bloqueado: bool) -> None:
        super().bloquear(bloqueado)
        selector_state = "disabled" if bloqueado else "readonly"
        self.audio_preset_selector.configure(state=selector_state)
        self.audio_sample_selector.configure(state=selector_state)
        self.audio_channel_selector.configure(state=selector_state)
        self.audio_bitrate_entry.configure(state="disabled" if bloqueado else "normal")

    def ejecutar_ffmpeg(
        self,
        comando: list[str],
        progress_callback=None,
    ) -> None:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = subprocess.Popen(
            comando,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=flags,
        )
        self.proceso_activo = process
        stderr_lines: list[str] = []
        try:
            if process.stderr is not None:
                for line in process.stderr:
                    stderr_lines.append(line.rstrip())
                    if len(stderr_lines) > 200:
                        del stderr_lines[:50]
                    seconds = parse_progress_seconds(line)
                    if seconds is not None and progress_callback is not None:
                        progress_callback(seconds)
            process.wait()
        finally:
            self.proceso_activo = None
        if process.returncode:
            detail = [line for line in stderr_lines if line]
            raise RuntimeError(
                detail[-1] if detail else "FFmpeg no pudo completar la conversión."
            )

    def convertir_ffmpeg_lote(
        self,
        origen: Path,
        archivos: list[Path],
        formato: str,
        extension: str,
        codec_args: list[str],
        errores_iniciales: list[str],
        opciones: dict[str, object] | None,
        audio_only: bool,
        required_encoder: str | tuple[str, ...] | None = None,
    ) -> None:
        destino = origen / f"convertidos_{formato.lower()}"
        policy = OutputPolicy((opciones or {}).get("output_policy", OutputPolicy.SKIP))
        normalize = bool((opciones or {}).get("normalize_filenames", False))
        generate_report = bool((opciones or {}).get("generate_report", False))
        results: list[FileResult] = []
        name_collisions = batch_name_collision_keys(
            destino, origen, archivos, extension, normalize
        )
        ffmpeg_info = resolve_ffmpeg()
        if ffmpeg_info is None:
            self.raiz.after(
                0,
                self.fallar,
                "FFmpeg no está disponible. Instala imageio-ffmpeg con "
                "'python -m pip install -r requirements.txt' o añade ffmpeg al PATH.",
            )
            return
        ffmpeg = str(ffmpeg_info.path)
        required_encoders = (
            (required_encoder,)
            if isinstance(required_encoder, str)
            else required_encoder or ()
        )
        missing_encoders = [
            codec for codec in required_encoders if not encoder_available(ffmpeg, codec)
        ]
        if missing_encoders:
            self.raiz.after(
                0,
                self.fallar,
                "FFmpeg no incluye los codificadores requeridos: "
                + ", ".join(missing_encoders)
                + ".",
            )
            return

        for index, source in enumerate(archivos, 1):
            if self.cancel_event.is_set():
                self.raiz.after(
                    0,
                    self.finalizar_resultados,
                    destino,
                    results,
                    errores_iniciales,
                    True,
                )
                return
            self.raiz.after(
                0,
                self.estado.set,
                f"Convirtiendo {index}/{len(archivos)}: {source.name}",
            )
            started = time.monotonic()
            original_bytes = safe_file_size(source)
            plan = None
            collision = False
            try:
                desired = desired_output_path(
                    destino, origen, source, extension, normalize
                )
                desired.parent.mkdir(parents=True, exist_ok=True)
                collision = path_key(desired) in name_collisions
                plan = plan_output(source, desired, policy)
                if not plan.should_convert:
                    results.append(
                        FileResult(
                            source,
                            plan.target,
                            ResultStatus.SKIPPED,
                            original_bytes,
                            error_message=(
                                "El destino ya existe."
                                if plan.action is OutputAction.SKIP_EXISTS
                                else "El destino está actualizado."
                            ),
                            processing_seconds=time.monotonic() - started,
                            output_action=plan.action.value,
                            name_collision=collision,
                        )
                    )
                    self.notificar_avance(index, len(archivos), source.name)
                    continue
                command = [ffmpeg, "-y", "-i", str(source), "-map_metadata", "0"]
                duration = None
                if audio_only:
                    command.append("-vn")
                else:
                    duration, _has_audio = probe_media(ffmpeg, source)
                    command.extend(("-progress", "pipe:2", "-nostats"))
                command.extend((*codec_args, str(plan.temporary)))

                def update_media_progress(seconds: float) -> None:
                    if duration and duration > 0:
                        value = (index - 1) + min(1.0, max(0.0, seconds / duration))
                        self.raiz.after(0, self.progreso.configure, {"value": value})

                if audio_only:
                    self.ejecutar_ffmpeg(command)
                else:
                    self.ejecutar_ffmpeg(command, update_media_progress)
                commit_output(plan)
                checksum, checksum_warnings = self.checksum_for_report(
                    plan.target, generate_report
                )
                results.append(
                    FileResult(
                        source,
                        plan.target,
                        ResultStatus.CONVERTED,
                        original_bytes,
                        safe_file_size(plan.target),
                        processing_seconds=time.monotonic() - started,
                        output_action=plan.action.value,
                        name_collision=collision,
                        warnings=checksum_warnings,
                        sha256=checksum,
                    )
                )
            except Exception as error:
                cleanup_temporary(plan)
                if self.cancel_event.is_set():
                    self.raiz.after(
                        0,
                        self.finalizar_resultados,
                        destino,
                        results,
                        errores_iniciales,
                        True,
                    )
                    return
                results.append(
                    FileResult(
                        source,
                        None,
                        ResultStatus.FAILED,
                        original_bytes,
                        error_message=str(error),
                        processing_seconds=time.monotonic() - started,
                        name_collision=collision,
                    )
                )
            self.notificar_avance(index, len(archivos), source.name)
        self.raiz.after(0, self.estado.set, "Finalizando lote…")
        self.raiz.after(
            0,
            self.finalizar_resultados,
            destino,
            results,
            errores_iniciales,
            self.cancel_event.is_set(),
        )

    def convertir_lote(
        self,
        origen: Path,
        archivos: list[Path],
        formato: str,
        calidad: int,
        errores_iniciales: list[str] | None = None,
        opciones: dict[str, object] | None = None,
    ) -> None:
        settings = (opciones or {}).get("audio_settings")
        if not isinstance(settings, AudioSettings):
            settings = manual_audio_settings(formato, calidad, None, None, None)
        codec_args = build_audio_args(formato, settings)
        self.convertir_ffmpeg_lote(
            origen,
            archivos,
            formato,
            FORMATOS_AUDIO[formato],
            codec_args,
            list(errores_iniciales or []),
            opciones,
            True,
            required_encoder=settings.codec,
        )


class PanelVideo(PanelAudio):
    MEDIA_TYPE = "video"
    ASPECT_LABELS = {
        "Conservar proporción": "preserve",
        "Ajustar con bandas": "fit",
        "Rellenar y recortar": "fill",
        "Estirar (puede deformar)": "stretch",
    }
    CODECS = {
        "MP4": ("libx264", "aac"),
        "MOV": ("libx264", "aac"),
        "MKV": ("libx264", "aac"),
        "WebM": ("libvpx-vp9", "libopus"),
        "AVI": ("mpeg4", "libmp3lame"),
    }

    def __init__(self, parent, raiz: Tk) -> None:
        PanelConversor.__init__(
            self, parent, raiz, "Conversor de vídeo", EXT_VIDEO, FORMATOS_VIDEO
        )
        self._applying_video_preset = False
        self.video_preset_display = StringVar(value="Personalizado")
        self.video_preset_description = StringVar(value="Ajustes de vídeo manuales.")
        self.video_width = StringVar(value="")
        self.video_height = StringVar(value="")
        self.video_fps = StringVar(value="30")
        self.video_aspect = StringVar(value="Conservar proporción")
        self.video_codec = StringVar(value="libx264")
        self.video_audio_codec = StringVar(value="aac")
        self.video_remove_audio = BooleanVar(value=False)
        self.video_background = StringVar(value="black")
        self.video_max_size = StringVar(value="")
        self.video_size_guidance = StringVar(
            value="El tamaño final se mostrará en el resumen; CRF no permite predecirlo con exactitud."
        )
        self._video_preset_ids = {
            preset.display_name: preset.preset_id for preset in VIDEO_PRESETS
        }

        ttk.Label(self.opciones_frame, text="Preset de vídeo:").grid(
            row=1, column=0, padx=(0, 10), pady=(10, 0), sticky="w"
        )
        self.video_preset_selector = ttk.Combobox(
            self.opciones_frame,
            textvariable=self.video_preset_display,
            values=("Personalizado", *(p.display_name for p in VIDEO_PRESETS)),
            state="readonly",
            width=25,
        )
        self.video_preset_selector.grid(row=1, column=1, pady=(10, 0), sticky="w")
        ttk.Label(
            self.opciones_frame,
            textvariable=self.video_preset_description,
            wraplength=390,
        ).grid(row=1, column=2, columnspan=3, pady=(10, 0), sticky="w")
        self.video_preset_selector.bind(
            "<<ComboboxSelected>>", self.apply_selected_video_preset
        )

        for row in range(6, 3, -1):
            for widget in self.grid_slaves(row=row):
                widget.grid_configure(row=row + 1)
        self.video_advanced = ttk.LabelFrame(
            self, text="Ajustes de vídeo", padding=(10, 7)
        )
        self.video_advanced.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(self.video_advanced, text="Resolución:").grid(row=0, column=0)
        self.video_width_entry = ttk.Entry(
            self.video_advanced, textvariable=self.video_width, width=6
        )
        self.video_width_entry.grid(row=0, column=1, padx=(6, 2))
        ttk.Label(self.video_advanced, text="×").grid(row=0, column=2)
        self.video_height_entry = ttk.Entry(
            self.video_advanced, textvariable=self.video_height, width=6
        )
        self.video_height_entry.grid(row=0, column=3, padx=(2, 14))
        ttk.Label(self.video_advanced, text="FPS máx.:").grid(row=0, column=4)
        self.video_fps_entry = ttk.Entry(
            self.video_advanced, textvariable=self.video_fps, width=5
        )
        self.video_fps_entry.grid(row=0, column=5, padx=(6, 14))
        self.video_aspect_selector = ttk.Combobox(
            self.video_advanced,
            textvariable=self.video_aspect,
            values=tuple(self.ASPECT_LABELS),
            state="readonly",
            width=24,
        )
        self.video_aspect_selector.grid(row=0, column=6)

        ttk.Label(self.video_advanced, text="Vídeo:").grid(row=1, column=0, pady=(7, 0))
        self.video_codec_selector = ttk.Combobox(
            self.video_advanced,
            textvariable=self.video_codec,
            values=("libx264", "libvpx-vp9", "mpeg4"),
            state="readonly",
            width=12,
        )
        self.video_codec_selector.grid(row=1, column=1, columnspan=2, pady=(7, 0))
        ttk.Label(self.video_advanced, text="Audio:").grid(row=1, column=3, pady=(7, 0))
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
            text="Eliminar audio",
            variable=self.video_remove_audio,
            command=self.video_settings_changed,
        )
        self.video_audio_check.grid(row=1, column=6, pady=(7, 0), sticky="w")
        ttk.Label(self.video_advanced, text="Color bandas:").grid(
            row=2, column=0, pady=(7, 0)
        )
        self.video_background_entry = ttk.Entry(
            self.video_advanced, textvariable=self.video_background, width=10
        )
        self.video_background_entry.grid(row=2, column=1, columnspan=2, pady=(7, 0))
        ttk.Label(self.video_advanced, text="Máx. MB (orientativo):").grid(
            row=2, column=3, columnspan=2, pady=(7, 0)
        )
        self.video_max_size_entry = ttk.Entry(
            self.video_advanced, textvariable=self.video_max_size, width=7
        )
        self.video_max_size_entry.grid(row=2, column=5, pady=(7, 0))
        ttk.Label(
            self.video_advanced, textvariable=self.video_size_guidance, wraplength=650
        ).grid(row=3, column=0, columnspan=7, pady=(7, 0), sticky="w")

        for variable in (
            self.formato,
            self.calidad,
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
        self.formato.trace_add("write", self.video_format_changed)
        self.apply_video_preset_id(self.settings_store.load_last_video_preset())

    def video_format_changed(self, *_args) -> None:
        if self._applying_video_preset:
            return
        codecs = self.CODECS.get(self.formato.get())
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
            self.video_preset_display.set("Personalizado")
            self.video_preset_description.set("Ajustes de vídeo manuales.")
            selected_id = CUSTOM_PRESET_ID
        else:
            settings = preset.video_settings
            self._applying_video_preset = True
            try:
                self.video_preset_display.set(preset.display_name)
                self.video_preset_description.set(preset.description)
                self.formato.set(preset.output_format)
                self.calidad.set(round((40 - settings.crf) / 0.24))
                self.video_width.set(str(settings.width) if settings.width else "")
                self.video_height.set(str(settings.height) if settings.height else "")
                self.video_fps.set(str(settings.fps_cap) if settings.fps_cap else "")
                label = next(
                    k
                    for k, v in self.ASPECT_LABELS.items()
                    if v == settings.aspect_mode
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
        self.video_preset_display.set("Personalizado")
        self.video_preset_description.set("Ajustes de vídeo modificados manualmente.")
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
            self.ASPECT_LABELS[self.video_aspect.get()],
            int(fps_text) if fps_text else None,
            round(40 - self.calidad.get() * 0.24),
            self.video_remove_audio.get(),
            self.video_background.get().strip() or "black",
            "yuv420p",
            self.formato.get() in {"MP4", "MOV"},
            int(max_size_text) if max_size_text else None,
        )

    def validar_inicio(self) -> str | None:
        try:
            settings = self.current_video_settings()
            validate_video_settings(self.formato.get(), settings)
            if settings.max_size_mb is not None and settings.max_size_mb <= 0:
                return "El tamaño máximo orientativo debe ser positivo."
        except (KeyError, ValueError) as error:
            return str(error)
        return None

    def opciones_conversion(self) -> dict[str, object]:
        options = PanelConversor.opciones_conversion(self)
        options["video_settings"] = self.current_video_settings()
        options["video_preset"] = self._video_preset_ids.get(
            self.video_preset_display.get(), CUSTOM_PRESET_ID
        )
        return options

    def bloquear(self, bloqueado: bool) -> None:
        PanelConversor.bloquear(self, bloqueado)
        readonly = "disabled" if bloqueado else "readonly"
        normal = "disabled" if bloqueado else "normal"
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

    def convertir_lote(
        self,
        origen: Path,
        archivos: list[Path],
        formato: str,
        calidad: int,
        errores_iniciales: list[str] | None = None,
        opciones: dict[str, object] | None = None,
    ) -> None:
        settings = (opciones or {}).get("video_settings")
        if not isinstance(settings, VideoSettings):
            codecs = self.CODECS[formato]
            settings = VideoSettings(
                codecs[0],
                codecs[1],
                None,
                None,
                "preserve",
                None,
                round(40 - calidad * 0.24),
                faststart=formato in {"MP4", "MOV"},
            )
        self.convertir_ffmpeg_lote(
            origen,
            archivos,
            formato,
            FORMATOS_VIDEO[formato],
            build_video_args(formato, settings),
            list(errores_iniciales or []),
            opciones,
            False,
            required_encoder=(
                (settings.video_codec,)
                if settings.remove_audio
                else (settings.video_codec, settings.audio_codec)
            ),
        )


class DiagnosticsPanel(ttk.Frame):
    def __init__(self, parent, raiz: Tk) -> None:
        super().__init__(parent, padding=24)
        self.raiz = raiz
        ttk.Label(self, text="Diagnóstico", font=("Segoe UI", 18, "bold")).pack(
            anchor="w", pady=(0, 14)
        )
        self.text = Text(self, wrap="word", height=22, width=90)
        self.text.pack(fill="both", expand=True)
        actions = ttk.Frame(self)
        actions.pack(anchor="e", pady=(12, 0))
        ttk.Button(actions, text="Actualizar", command=self.refresh).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(actions, text="Copiar diagnóstico", command=self.copy).pack(
            side="left"
        )
        self.refresh()

    def refresh(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", diagnostics_text())
        self.text.configure(state="disabled")

    def copy(self) -> None:
        self.raiz.clipboard_clear()
        self.raiz.clipboard_append(self.text.get("1.0", "end-1c"))
        self.raiz.update_idletasks()


class ConversorApp:
    def __init__(self, raiz: Tk) -> None:
        raiz.title("Conversor multimedia")
        raiz.geometry("900x780")
        raiz.minsize(760, 740)
        pestañas = ttk.Notebook(raiz)
        pestañas.pack(fill="both", expand=True)
        image_panel = PanelImagen(pestañas, raiz)
        audio_panel = PanelAudio(pestañas, raiz)
        video_panel = PanelVideo(pestañas, raiz)
        pestañas.add(image_panel, text=" Imágenes ")
        pestañas.add(audio_panel, text=" Audio ")
        pestañas.add(video_panel, text=" Vídeo ")
        pestañas.add(DiagnosticsPanel(pestañas, raiz), text=" Diagnóstico ")
        if resolve_ffmpeg() is None:
            unavailable = (
                "FFmpeg no disponible. Las imágenes siguen operativas; instala las "
                "dependencias o añade ffmpeg al PATH para habilitar esta sección."
            )
            audio_panel.estado.set(unavailable)
            video_panel.estado.set(unavailable)
            pestañas.tab(audio_panel, state="disabled")
            pestañas.tab(video_panel, state="disabled")


def main() -> None:
    raiz = Tk()
    ConversorApp(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
