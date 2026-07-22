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
