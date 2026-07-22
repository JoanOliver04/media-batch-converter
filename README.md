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

La opción **Si el destino existe** se aplica por igual a imágenes, audio y vídeo, y recuerda la última elección:

- **Omitir (predeterminada):** conserva el archivo existente sin convertirlo.
- **Sobrescribir de forma segura:** genera primero un archivo temporal en la misma carpeta y solo entonces reemplaza el destino de forma atómica. Si la codificación, los permisos o la sustitución fallan, se conserva el archivo anterior y se elimina el temporal.
- **Crear un nombre único:** conserva ambos archivos con sufijos deterministas `_2`, `_3`…; las rutas se reservan entre conversiones simultáneas y las colisiones se comparan sin distinguir mayúsculas.
- **Convertir si el origen es más reciente:** sobrescribe de forma segura únicamente cuando la marca temporal del origen es posterior a la del destino.

La comparación temporal depende de la precisión del sistema de archivos y considera actualizado un destino con fecha igual o posterior. El resumen separa conversiones, sobrescrituras, renombrados, omisiones por existencia, omisiones por fecha y fallos. Un archivo dañado no detiene el resto del lote. Las animaciones GIF/WebP se conservan cuando el formato de salida también admite animación.

## Normalización opcional de nombres

**Normalizar nombres de salida** está desactivado de forma predeterminada y se aplica únicamente a los archivos generados; nunca renombra los archivos de origen ni las carpetas. Para un archivo individual, la interfaz muestra una vista previa del nombre resultante.

El algoritmo toma el nombre sin extensión, aplica Unicode NFKD, elimina marcas diacríticas cuando es posible, convierte a minúsculas ASCII y transforma separadores o puntuación en guiones bajos. Después colapsa separadores repetidos, retira los situados en los extremos y conserva solo `a-z`, `0-9` y `_`. Los nombres que empiezan por un número o están reservados en Windows (`CON`, `PRN`, `AUX`, `NUL`, `COM1`…`COM9`, `LPT1`…`LPT9`) reciben el prefijo `asset_`; un resultado vacío se convierte en `asset`. El nombre base se limita a **100 caracteres** y siempre conserva la extensión de salida elegida.

Antes de procesar se detectan, sin distinguir mayúsculas, las rutas que convergen en el mismo nombre normalizado. Las carpetas relativas se mantienen, por lo que nombres iguales en subcarpetas diferentes no colisionan. Dentro de una misma carpeta, los elementos se procesan de forma determinista y se aplica la política de archivos existentes: omitir, sobrescribir explícitamente, crear sufijos `_2`, `_3`… o comparar fechas. Toda colisión se contabiliza y detalla en el resumen, incluso si la política seleccionada permite completar la conversión.

## GIF y otras imágenes animadas

Cuando se selecciona un archivo animado —o una carpeta que puede contenerlos— aparece **Tratamiento de animaciones**. La opción es global para el lote, se recuerda localmente y no se muestra para un archivo estático:

- **Conservar animación (predeterminada):** mantiene orden, número de fotogramas, duraciones, bucle, transparencia y, para GIF/APNG, la disposición (`disposal`) en la medida que Pillow lo permite. El redimensionado usa el mismo tamaño objetivo en todos los fotogramas. Antes de aceptar un formato, la aplicación escribe y reabre una animación mínima en memoria para comprobar capacidad, fotogramas, bucle y —salvo la limitación WebP descrita abajo— duraciones. En la compilación habitual son compatibles GIF, WebP y APNG, pero el resultado real depende de Pillow y sus códecs.
- **Extraer fotogramas:** crea una carpeta nueva `nombre_frames`, o `nombre_frames_2` si ya existe, sin reutilizar ni sobrescribir carpetas ajenas. Genera `frame_0001`, `frame_0002`… en el formato estático elegido, aplica calidad, modo WebP y redimensionado, y registra duración, tamaño y SHA-256 por fotograma en el informe JSON. La estructura relativa del lote se conserva.
- **Solo primer fotograma:** convierte explícitamente el fotograma 0 y registra `ANIMATION_INTENTIONALLY_DISCARDED`; nunca presenta esa salida como animación conservada.

Si **Conservar animación** se combina con un destino no compatible, el archivo afectado falla con `ANIMATED_DESTINATION_UNSUPPORTED`; no se elige un fallback silencioso. En un archivo individual la interfaz avisa antes de iniciar. En lote se agregan resultados conservados, extraídos y reducidos al primer fotograma sin abrir un diálogo por elemento.

Pillow compone los cambios parciales de fotogramas durante la iteración; la fidelidad de paletas, cuantización, transparencia y disposal queda limitada por cada códec. Pillow escribe las duraciones WebP, pero actualmente no las expone de nuevo al leer; la aplicación recupera los valores estándar de los bloques `ANMF`, mientras que la sonda WebP verifica escritura, número de fotogramas y bucle. La cancelación durante extracción elimina únicamente la carpeta parcial creada por esa operación.

## Validación y avisos de imagen

Antes de codificar cada imagen se ejecuta una validación no destructiva. Los avisos de nivel `information` y `warning` permiten continuar; `blocking_error` impide únicamente ese archivo y el resto del lote sigue. No se abre un diálogo por aviso: el resumen final agrega el total y ofrece el detalle con código, severidad y mensaje. Si se habilita el informe JSON, cada aviso incluye además sus detalles estructurados.

La presencia de un canal alfa no implica transparencia: se inspecciona su valor mínimo y solo se considera significativa si algún píxel tiene opacidad inferior a 255. Las dimensiones se consideran extremas desde 16.000 píxeles en un eje y se advierte de presión de memoria desde 80.000.000 de píxeles. Se mantienen activos los límites de seguridad de Pillow; `DecompressionBombWarning` se registra y `DecompressionBombError` bloquea el archivo afectado.

| Código | Severidad | Significado |
| --- | --- | --- |
| `ALPHA_CHANNEL_PRESENT` | information | Existe canal alfa, aunque puede ser totalmente opaco. |
| `MEANINGFUL_TRANSPARENCY` | information | Hay píxeles realmente transparentes. |
| `ALPHA_WILL_BE_FLATTENED` | warning | JPEG o BMP eliminará la transparencia. |
| `SOURCE_DIMENSIONS_EXTREME` | warning | Algún eje alcanza el límite de dimensión extrema. |
| `SOURCE_PIXEL_COUNT_EXCESSIVE` | warning | El total de píxeles puede ejercer presión de memoria. |
| `CORRUPTED_IMAGE` | blocking_error | Pillow detectó datos dañados, truncados o no identificables. |
| `EXTENSION_FORMAT_MISMATCH` | warning | La extensión no coincide con el formato detectado. |
| `UNUSUAL_COLOR_MODE` | warning | El modo de color no pertenece al conjunto habitual compatible. |
| `ICC_PROFILE_INVALID` | warning | El perfil ICC no se pudo interpretar. |
| `ICC_PROFILE_DROPPED` | information | El perfil ICC no se copia a la salida. |
| `ANIMATION_MAY_BE_LOST` | warning | Una animación se dirige a un formato tratado como estático. |
| `ANIMATION_INTENTIONALLY_DISCARDED` | warning | La política elegida conserva únicamente el fotograma 0. |
| `ANIMATED_DESTINATION_UNSUPPORTED` | blocking_error | El destino no supera la sonda de conservación y exige otro modo. |
| `FRAMES_EXTRACTED` | information | Los fotogramas se guardaron por separado con sus duraciones. |
| `OUTPUT_SIZE_REDUCTION_EXTREME` | warning | La salida es más de un 90 % menor; se recomienda revisión visual sin afirmar pérdida. |
| `OUTPUT_SIZE_INCREASED` | information | La salida ocupa más que la fuente. |
| `METADATA_DROPPED` | information | EXIF, comentarios o XMP detectados no se copian. |
| `CMYK_CONVERTED_TO_RGB` | warning | Una fuente CMYK se transforma a RGB. |
| `INVALID_DIMENSIONS` | blocking_error | La anchura o altura no es válida. |
| `DECOMPRESSION_BOMB_WARNING` | warning | Pillow considera sospechoso el número de píxeles. |
| `DECOMPRESSION_BOMB_ERROR` | blocking_error | Pillow bloqueó la imagen por riesgo de bomba de descompresión. |

La validación no realiza comparación visual automática, puntuación perceptual ni afirma degradación sin evidencia objetiva. Los archivos fuente nunca se modifican.

## Informe JSON y SHA-256

La opción **Generar informe JSON con SHA-256** está desactivada de forma predeterminada. Cuando se activa, el cálculo se realiza por bloques de 1 MiB en el hilo de trabajo, admite cancelación y nunca carga un archivo multimedia completo en memoria. El hash representa los bytes finales ya publicados; se comparan tamaño y fecha antes y después del cálculo y se añade un aviso si el archivo cambia durante ese intervalo.

El informe se guarda como `conversion_report.json` en la raíz de salida. Si ya existe, se usa un nombre UTC determinista como `conversion_report_2026-07-22_154530.json` y, si también colisiona, sufijos `_2`, `_3`… La escritura usa UTF-8, un temporal completamente sincronizado y publicación atómica sin sobrescritura. Un fallo del informe se muestra como aviso y no invalida las conversiones completadas.

Las rutas son **relativas de forma predeterminada**: las fuentes se expresan respecto a la raíz de origen y las salidas respecto a la raíz de resultados. Si una ruta no puede relativizarse, solo se conserva su nombre. Las rutas absolutas deben habilitarse explícitamente; el informe no recopila variables de entorno, credenciales ni metadatos ajenos.

El esquema comienza en `schemaVersion: 1`, independiente de `applicationVersion`. Un cambio incompatible incrementará `schemaVersion`; los campos compatibles pueden ampliarse conservando la versión. `files` mantiene el orden determinista de procesamiento. Los campos de dimensiones se incluyen en imágenes y los no aplicables a audio o vídeo se omiten.

Ejemplo abreviado:

```json
{
  "schemaVersion": 1,
  "applicationVersion": "1.0.0",
  "startedAt": "2026-07-22T15:45:20+00:00",
  "completedAt": "2026-07-22T15:45:30+00:00",
  "elapsedMilliseconds": 10000,
  "mediaType": "image",
  "outputFormat": "webp",
  "settings": {"quality": 90, "report_absolute_paths": false},
  "summary": {"discovered": 1, "processed": 1, "converted": 1},
  "files": [
    {
      "source": "characters/hero.png",
      "output": "characters/hero.webp",
      "status": "converted",
      "originalBytes": 5241880,
      "outputBytes": 643201,
      "width": 2048,
      "height": 3072,
      "outputWidth": 1024,
      "outputHeight": 1536,
      "quality": 90,
      "encodingMode": "lossy",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "warnings": [],
      "error": null
    }
  ]
}
```

Campos principales: las fechas usan ISO-8601 UTC; `elapsedMilliseconds` mide la operación; `settings` contiene solo opciones públicas; `summary` agrega estados y tamaños. Cada elemento de `files` incluye ruta segura, estado, bytes, avisos y error, además de dimensiones, calidad, modo y SHA-256 cuando sean aplicables. Los omitidos y fallidos no se hashean.

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

Todos los presets de imagen mantienen las dimensiones originales. El redimensionado se controla por separado y cualquier cambio manual deja el preset en estado **Personalizado**.

## Presets de audio

Los presets de producción configuran de forma conjunta contenedor, códec, frecuencia, canales y bitrate. FFmpeg recibe siempre una lista de argumentos —incluidas rutas con espacios o caracteres Unicode— y la aplicación comprueba que el codificador necesario esté disponible antes de iniciar el lote. No se recorta la duración ni se normaliza la sonoridad de forma implícita.

| Preset | Salida y códec | Frecuencia | Canales | Bitrate | Uso previsto |
| --- | --- | ---: | --- | ---: | --- |
| Música de ejecución | M4A, AAC-LC | 48 kHz | Estéreo | 192 kbps | Música final para reproducción |
| Ambiente de ejecución | M4A, AAC-LC | 48 kHz | Estéreo | 160 kbps | Ambientes de uso final |
| Efecto de sonido | M4A, AAC-LC | 48 kHz | Mono | 128 kbps | Efectos compactos; admite cambio manual a estéreo |
| Máster WAV | WAV, PCM firmado de 24 bits | 48 kHz | Conservar origen | Sin pérdida | Máster editable y archivo |
| Voz o diálogo | M4A, AAC-LC | 48 kHz | Mono | 96 kbps | Locución y diálogo |

El selector recuerda el último preset de audio. Frecuencia, canales y bitrate siguen siendo editables; al cambiarlos, el estado pasa a **Personalizado** para reflejar con precisión la configuración que se exportará. WAV y FLAC ignoran el bitrate porque son salidas sin pérdida. El máster WAV conserva el número de canales de la fuente y usa `pcm_s24le`; los presets M4A declaran explícitamente el perfil AAC-LC.

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
