# Conversor multimedia

Aplicación de escritorio con pestañas independientes para convertir imágenes, audio y vídeo, tanto archivo por archivo como por lotes.

## Uso

1. Ejecuta `iniciar.bat` o `python png_a_webp.py`.
2. Abre la pestaña **Imágenes**, **Audio** o **Vídeo**.
3. Selecciona un archivo o una carpeta, elige el formato de salida y ajusta la calidad.
4. Pulsa **Iniciar conversión**.

## Conversión recursiva

Al seleccionar una carpeta, la opción **Incluir subcarpetas** está activada de forma predeterminada. La aplicación busca archivos compatibles en todos los niveles y reproduce su estructura relativa dentro de la carpeta de salida. Puede desactivarse para procesar únicamente los archivos del primer nivel.

Las carpetas `converted_*` y `convertidos_*` se excluyen siempre del descubrimiento para evitar procesar resultados anteriores o crear ciclos. Los enlaces simbólicos a archivos y directorios tampoco se siguen; esta política evita ciclos y mantiene cada archivo asociado a una única ruta de origen.

El progreso diferencia el descubrimiento, la conversión y la finalización. La operación puede cancelarse durante el escaneo o entre archivos; en audio y vídeo también se detiene el proceso FFmpeg activo.

## Formatos

- Imágenes: PNG, JPEG, WebP, BMP, TIFF y GIF.
- Audio: MP3, WAV, FLAC, OGG, M4A/AAC y Opus.
- Vídeo: MP4, MKV, WebM, MOV y AVI.

Los resultados se guardan junto a los originales en una carpeta `convertidos_formato`. Los archivos originales nunca se modifican. Pillow e `imageio-ffmpeg` se instalan automáticamente mediante `pip` si no están disponibles.

La transparencia de imagen se conserva en los formatos compatibles; JPEG usa fondo blanco. Audio y vídeo conservan los metadatos compatibles y se procesan con FFmpeg. La barra de calidad controla el bitrate en audio y la compresión visual en vídeo.

## Protección y tolerancia a errores

Las conversiones anteriores no se sobrescriben: si un nombre ya existe, se añade un número. Un archivo dañado no detiene el resto del lote y el resumen final muestra los fallos. Las animaciones GIF/WebP se conservan cuando el formato de salida también admite animación.

## Modos WebP

- **Automático (predeterminado):** JPEG se codifica con pérdida; las animaciones, imágenes de paleta y muestras con 256 colores o menos se codifican sin pérdida; el resto se codifica con pérdida. Se consideran grandes las imágenes desde 1.000.000 de píxeles o 1.600 píxeles en cualquiera de sus dimensiones.
- **Con pérdida:** usa el control de calidad para conseguir archivos más pequeños. El color puede variar ligeramente, pero el canal alfa continúa siendo compatible.
- **Sin pérdida:** conserva exactamente los valores de los píxeles y desactiva el control de calidad. Puede producir archivos mayores.

La decisión automática se realiza independientemente para cada archivo del lote y el modo elegido se muestra durante la conversión. Las exportaciones mantienen la política existente de la aplicación: no copian perfiles ICC ni metadatos EXIF. El modo con pérdida suele ser apropiado para fotografías e ilustraciones complejas; el modo sin pérdida, para iconos, gráficos planos y recursos que exigen fidelidad exacta.
## Presets de imagen

Los presets aplican formato, modo WebP y calidad de una sola vez. Después se puede modificar cualquier ajuste; la selección cambia a **Personalizado** para no presentar una configuración modificada como si siguiera intacta. El último preset se guarda localmente en las preferencias del usuario.

| Preset | Salida | Modo | Calidad | Uso previsto |
| --- | --- | --- | ---: | --- |
| Ilustración de alta calidad | WebP | Con pérdida | 90 | Ilustraciones detalladas |
| Recurso móvil general | WebP | Automático | 88 | Recursos de uso general |
| Fondo grande | WebP | Con pérdida | 82 | Fondos extensos |
| Recurso de interfaz transparente | WebP | Sin pérdida | No aplica | Iconos y elementos con alfa exacto |
| Miniatura | WebP | Con pérdida | 78 | Imágenes compactas; todavía sin redimensionado |
| Archivo sin pérdida | PNG | Sin pérdida | No aplica | Conservación y archivo |

Todos los presets mantienen las dimensiones originales. El modelo reserva opciones de redimensionado y de audio/vídeo para ampliaciones posteriores, pero no aplica silenciosamente funciones todavía no disponibles.
## Redimensionado de imágenes

El redimensionado se realiza después de corregir la orientación EXIF y antes de codificar el formato final. Utiliza LANCZOS, conserva la transparencia y nunca recorta ni deforma.

- **Conservar dimensiones:** no remuestrea la imagen.
- **Anchura máxima:** limita la anchura y calcula proporcionalmente la altura.
- **Altura máxima:** limita la altura y calcula proporcionalmente la anchura.
- **Ajustar dentro de dimensiones:** encaja la imagen en una caja de anchura × altura.
- **Escalar por porcentaje:** aplica un porcentaje proporcional. Con **Nunca ampliar imágenes pequeñas** activo, el máximo efectivo es 100%; al desactivarlo se permite una ampliación explícita y limitada.

Para un archivo individual se muestra una estimación basada en sus dimensiones después de orientar. En lotes, cada archivo se calcula individualmente. Las animaciones GIF/WebP redimensionan todos los fotogramas al mismo tamaño objetivo. No se aplican recorte, deformación ni ampliación mediante IA.
## Resumen y comparación de tamaño

Al finalizar se abre un resumen seleccionable con archivos descubiertos y procesados, conversiones correctas, omisiones, fallos, tamaños originales y finales, ahorro o aumento, porcentaje y tiempo transcurrido. **Copiar resumen** envía el contenido al portapapeles y los detalles de fallos se limitan inicialmente para mantener ágil la ventana en lotes grandes.

Los cálculos usan bytes reales y un reloj monotónico. El porcentaje compara únicamente las entradas convertidas correctamente con sus nuevas salidas; los archivos fallidos u omitidos nunca se presentan como ahorro. Los archivos de salida anteriores tampoco se incluyen. Una cancelación muestra estadísticas parciales válidas de lo procesado hasta ese momento.
