"""Conversor de imágenes, audio y vídeo con interfaz Tkinter."""

from __future__ import annotations

import importlib
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, Tk, filedialog, messagebox
from tkinter import ttk

from batch_processing import discover_files, safe_output_directory
from conversion_results import BatchSummary, FileResult, ResultStatus, safe_file_size
from output_policy import (
    OutputAction,
    OutputPolicy,
    cleanup_temporary,
    commit_output,
    plan_output,
)
from image_resize import (
    ResizeConfig,
    ResizeMode,
    calculate_resize_dimensions,
    validate_resize_config,
)
from presets import (
    CUSTOM_PRESET_ID,
    IMAGE_PRESETS,
    SettingsStore,
    preset_by_id,
    preset_matches,
)
from summary_dialog import show_summary
from webp_encoding import (
    WebPMode,
    resolve_webp_mode,
    webp_controls_visible,
    webp_save_options,
)


def instalar_dependencias() -> None:
    """Instala las dependencias usando el mismo intérprete de Python."""
    faltan = []
    for modulo in ("PIL", "imageio_ffmpeg"):
        try:
            importlib.import_module(modulo)
        except ImportError:
            faltan.append(modulo)
    if faltan:
        try:
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(Path(__file__).with_name("requirements.txt")),
                ]
            )
        except (subprocess.CalledProcessError, OSError) as error:
            raise RuntimeError(
                "No se pudieron instalar Pillow y FFmpeg automáticamente. "
                "Comprueba tu conexión a Internet y que pip esté disponible."
            ) from error


instalar_dependencias()
import imageio_ffmpeg  # noqa: E402
from PIL import Image, ImageOps, ImageSequence  # noqa: E402


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


class PanelConversor(ttk.Frame):
    """Controles compartidos por los tres tipos de conversión."""

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

    def seleccionar_carpeta(self) -> None:
        ruta = filedialog.askdirectory(title="Selecciona una carpeta")
        if ruta:
            self.seleccion.set(ruta)
            self.estado.set(
                "Carpeta seleccionada. El contenido se descubrirá al iniciar."
            )

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
        logging.getLogger(__name__).info("batch_start media=%s", type(self).__name__)
        self.bloquear(True)
        self.progreso.configure(mode="indeterminate", value=0)
        self.progreso.start(12)
        self.estado.set("Descubriendo archivos compatibles…")
        threading.Thread(
            target=self.preparar_lote,
            args=(
                origen,
                archivos,
                self.formato.get(),
                self.calidad.get(),
                self.recursivo.get(),
                self.opciones_conversion(),
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
        return {"output_policy": self.output_policy.get()}

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
        show_summary(self.raiz, summary, destino)

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
        return None

    def opciones_conversion(self) -> dict[str, object]:
        return {
            "webp_mode": self.webp_mode.get(),
            "resize_config": self.current_resize_config(),
            "output_policy": self.output_policy.get(),
        }

    def bloquear(self, bloqueado: bool) -> None:
        self._bloqueado = bloqueado
        super().bloquear(bloqueado)
        self.selector_preset.configure(state="disabled" if bloqueado else "readonly")
        self.selector_resize.configure(state="disabled" if bloqueado else "readonly")
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
    ) -> WebPMode | None:
        source = source or salida
        resize_config = resize_config or ResizeConfig()
        es_animada = getattr(imagen, "is_animated", False) and formato in {
            "GIF",
            "WEBP",
        }
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
        for frame in ImageSequence.Iterator(imagen):
            resized, target = self.resize_frame(
                frame.convert("RGBA"), resize_config, target
            )
            frames.append(resized.convert("RGBA"))
            durations.append(
                frame.info.get("duration", imagen.info.get("duration", 100))
            )

        save_options: dict[str, object] = {
            "save_all": True,
            "append_images": frames[1:],
            "duration": durations,
            "loop": imagen.info.get("loop", 0),
        }
        if formato == "WEBP":
            save_options.update(webp_save_options(resolved_mode, calidad))
        else:
            save_options["optimize"] = True
        frames[0].save(salida, format=formato, **save_options)
        return resolved_mode

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
        destino = origen / f"convertidos_{elegido.lower()}"
        discovery_errors = list(errores_iniciales or [])
        results: list[FileResult] = []
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
            try:
                output_directory = safe_output_directory(destino, origen, archivo)
                output_directory.mkdir(parents=True, exist_ok=True)
                desired = output_directory / f"{archivo.stem}{extension}"
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
                        )
                    )
                    self.notificar_avance(indice, len(archivos), archivo.name)
                    continue
                with Image.open(archivo) as image:
                    resolved_mode = self.guardar_imagen(
                        image,
                        plan.temporary,
                        formato,
                        calidad,
                        archivo,
                        requested_mode,
                        resize_config,
                    )
                commit_output(plan)
                if resolved_mode is not None:
                    self.modos_seleccionados[archivo] = resolved_mode
                results.append(
                    FileResult(
                        archivo,
                        plan.target,
                        ResultStatus.CONVERTED,
                        original_bytes,
                        safe_file_size(plan.target),
                        processing_seconds=time.monotonic() - started,
                        encoder_mode=resolved_mode.value if resolved_mode else None,
                        output_action=plan.action.value,
                    )
                )
            except Exception as error:
                cleanup_temporary(plan)
                results.append(
                    FileResult(
                        archivo,
                        None,
                        ResultStatus.FAILED,
                        original_bytes,
                        error_message=str(error),
                        processing_seconds=time.monotonic() - started,
                    )
                )
            self.notificar_avance(indice, len(archivos), archivo.name)
        self.raiz.after(0, self.estado.set, "Finalizando lote…")
        self.raiz.after(
            0, self.finalizar_resultados, destino, results, discovery_errors
        )


class PanelAudio(PanelConversor):
    def __init__(self, parent, raiz: Tk) -> None:
        super().__init__(parent, raiz, "Conversor de audio", EXT_AUDIO, FORMATOS_AUDIO)

    def ejecutar_ffmpeg(self, comando: list[str]) -> None:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = subprocess.Popen(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=flags,
        )
        self.proceso_activo = process
        try:
            _, stderr = process.communicate()
        finally:
            self.proceso_activo = None
        if process.returncode:
            detail = stderr.strip().splitlines()
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
    ) -> None:
        destino = origen / f"convertidos_{formato.lower()}"
        policy = OutputPolicy((opciones or {}).get("output_policy", OutputPolicy.SKIP))
        results: list[FileResult] = []
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as error:
            self.raiz.after(0, self.fallar, str(error))
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
            try:
                output_directory = safe_output_directory(destino, origen, source)
                output_directory.mkdir(parents=True, exist_ok=True)
                desired = output_directory / f"{source.stem}{extension}"
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
                        )
                    )
                    self.notificar_avance(index, len(archivos), source.name)
                    continue
                command = [ffmpeg, "-y", "-i", str(source), "-map_metadata", "0"]
                if audio_only:
                    command.append("-vn")
                command.extend((*codec_args, str(plan.temporary)))
                self.ejecutar_ffmpeg(command)
                commit_output(plan)
                results.append(
                    FileResult(
                        source,
                        plan.target,
                        ResultStatus.CONVERTED,
                        original_bytes,
                        safe_file_size(plan.target),
                        processing_seconds=time.monotonic() - started,
                        output_action=plan.action.value,
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
                    )
                )
            self.notificar_avance(index, len(archivos), source.name)
        self.raiz.after(0, self.estado.set, "Finalizando lote…")
        self.raiz.after(
            0, self.finalizar_resultados, destino, results, errores_iniciales
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
        bitrate = round(64 + calidad * 2.56)
        codecs = {
            "MP3": ["-c:a", "libmp3lame", "-b:a", f"{bitrate}k"],
            "WAV": ["-c:a", "pcm_s16le"],
            "FLAC": ["-c:a", "flac", "-compression_level", "8"],
            "OGG": ["-c:a", "libvorbis", "-q:a", str(max(1, round(calidad / 10)))],
            "M4A": ["-c:a", "aac", "-b:a", f"{bitrate}k"],
            "Opus": ["-c:a", "libopus", "-b:a", f"{min(bitrate, 256)}k"],
        }
        self.convertir_ffmpeg_lote(
            origen,
            archivos,
            formato,
            FORMATOS_AUDIO[formato],
            codecs[formato],
            list(errores_iniciales or []),
            opciones,
            True,
        )


class PanelVideo(PanelAudio):
    def __init__(self, parent, raiz: Tk) -> None:
        PanelConversor.__init__(
            self, parent, raiz, "Conversor de vídeo", EXT_VIDEO, FORMATOS_VIDEO
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
        crf = round(40 - calidad * 0.24)
        codecs = {
            "MP4": [
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
            ],
            "MKV": [
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                str(crf),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
            ],
            "WebM": [
                "-c:v",
                "libvpx-vp9",
                "-crf",
                str(crf),
                "-b:v",
                "0",
                "-c:a",
                "libopus",
                "-b:a",
                "160k",
            ],
            "MOV": [
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
            ],
            "AVI": [
                "-c:v",
                "mpeg4",
                "-q:v",
                str(max(2, round(31 - calidad * 0.29))),
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
            ],
        }
        self.convertir_ffmpeg_lote(
            origen,
            archivos,
            formato,
            FORMATOS_VIDEO[formato],
            codecs[formato],
            list(errores_iniciales or []),
            opciones,
            False,
        )


class ConversorApp:
    def __init__(self, raiz: Tk) -> None:
        raiz.title("Conversor multimedia")
        raiz.geometry("900x700")
        raiz.minsize(760, 640)
        pestañas = ttk.Notebook(raiz)
        pestañas.pack(fill="both", expand=True)
        pestañas.add(PanelImagen(pestañas, raiz), text=" Imágenes ")
        pestañas.add(PanelAudio(pestañas, raiz), text=" Audio ")
        pestañas.add(PanelVideo(pestañas, raiz), text=" Vídeo ")


def main() -> None:
    raiz = Tk()
    ConversorApp(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
