# Changelog

All notable changes are documented here. This project follows [Semantic Versioning](https://semver.org/) and the structure from [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

## 0.4.0 - 2026-11-24

- Review a batch before converting. Search relative paths, include or exclude files across pages, and see the selected input size.
- Search completed results by filename or folder with Ctrl+F, combine the search with the status filter, and compare measured savings per file.
- The diagnostics report loads when its tab first opens.
- Video size limits now apply to the complete encode. Oversized videos leave any previous output intact.

## 0.3.0 - 2026-11-21

### Added

- Multi-file selection, a configurable output parent and a shortcut to the output folder in the summary.
- Responsive conversion controls with a persistent action bar, progress within both audio and video files, and keyboard focus that scrolls into view.
- Configurable FFmpeg executable for source and packaged runs.
- Latest batch results can be reopened on each tab, with paginated file details, status filters and safe retries for failed files.
- Save only if smaller works across the four conversion tabs, including animation exports and document companions.
- Presets for AVIF backgrounds, AAC/Opus/Vorbis music, lossless FLAC and HEVC cinematics.
- The Windows executable and app window have a dedicated icon.

### Fixed

- Image, audio and video status now follows the selected language during conversion.
- Same-stem batches (`Photo.png` + `Photo.jpg`) keep both outputs instead of skipping or overwriting one.
- Windows reserved device names (`CON`, `NUL`, …) are sanitized even when filename normalization is off.
- Directory junctions are no longer walked during recursive discovery.
- Closing the window while a batch runs asks for confirmation and cancels the encoder.
- Cancel terminates the active FFmpeg process, then kills it if it ignores the first signal.
- LibreOffice conversions kill the `soffice.bin` tree, keep HTML sidecar files, and prefer the output whose stem matches the source.
- Embedded decompression bombs are skipped instead of aborting the whole document.
- Multi-table documents with a title no longer crash when writing XLSX.
- PPTX pictures are read and written by the built-in engine.
- Video fit, fill and stretch use even dimensions for `yuv420p`, and AVI uses the MPEG-4 quality scale.
- Empty input no longer selects the working directory. Language switching preserves the active source and destination.
- New outputs and reports preserve files written in parallel. Frame exports finish staging before replacing an earlier export.
- Cleanup only removes empty directories created during the batch.
- Raw MPEG-4 `.m4v` files now use an allowed FFmpeg demuxer.
- The built-in PPTX reader keeps slide tables, and the writer splits long tables across slides.
- The LibreOffice converter checks which application can export each format pair and uses UTF-8 for text and CSV exports.
- LibreOffice converts HTML to DOCX and RTF through an intermediate ODT file.

### Changed

- The video Max MiB field is verified against the actual encoded size before publishing.
- Audio and video progress use one FFmpeg invocation per file, and batch output names are indexed per directory.
- Upgraded Pillow, pypdf and ReportLab, restricted decoding to supported formats, and capped memory for preserved animations.
- The converter compares eligible image encodings at the requested quality and attempts lossless PDF and Office package recompression. MP3 and Vorbis use quality-based VBR when the bitrate field is blank.
- Resize targets are limited to 16 384 px per side.
- Animations with more than 500 frames must use First frame only.
- The built-in spreadsheet writers neutralize formula-like text they write.
- The public Windows ZIP uses a separately installed FFmpeg executable for audio and video.

## 0.2.1 - 2026-08-14

### Fixed

- DOCX to PDF no longer leaves an empty `convertidos_pdf` folder when LibreOffice crashes on Windows. Automatic conversion falls back to the built-in engine, and the headless call uses `soffice.exe` instead of `soffice.com`.

## 0.2.0 - 2026-08-14

### Added

- Files tab for documents and spreadsheets: PDF, DOCX, ODT, RTF, TXT, Markdown, HTML, XLSX, CSV and PPTX, plus LibreOffice-only binary Office when that install is present.
- A document conversion package with an intermediate model, built-in readers and writers, optional LibreOffice, and security checks for size, type sniffing and zip bombs.
- Built-in Word `.docx` conversion that keeps embedded images plus header and footer text when producing PDF, DOCX or HTML.
- File presets for PDF archives, editable DOCX, plain text, Markdown, CSV, HTML and PPTX.
- `tools/screenshot.py`, which regenerates the README screenshots reproducibly and without touching the developer's settings.
- Dark instrument-style interface with a single amber accent, monospaced numeric readouts and a themed summary window and diagnostics console, all defined in `ui/theme.py`.
- Language selector for Spanish and English, applied immediately without restarting and persisted with the local settings.
- Message catalogues under `locales/`, with tests that fail when a catalogue is missing a key or a format placeholder.

### Changed

- The language selector now reads "Language: [value]" instead of showing the label after the dropdown.
- The output-name example matches the tab's media type instead of always showing an image example.
- Split the monolithic `png_a_webp.py` presentation layer into a `ui/` package with one module per tab plus shared bases.
- Audio and video panels now share a common `FFmpegPanel` base instead of video inheriting from audio.
- Split the oversized image and FFmpeg batch loops into per-file steps separated from orchestration.
- Renamed internal identifiers from Spanish to English; user-facing text moved out of the modules into the catalogues.
- Preset names and descriptions are resolved from the active language instead of being stored on the preset.
- The FFmpeg provider is recorded as a stable code (`bundled`, `system`, `imageio-ffmpeg`) and translated only for display.
- Test temporary directories are created in the system temp location instead of the repository root.

### Removed

- Unused `completar` result dialog, superseded by the batch summary.

## 0.1.0 - 2026-07-22

### Added

- Tkinter desktop interface for individual and recursive batch conversion.
- Image conversion with transparency, WebP modes, resizing, validation, and animated-image policies.
- Audio and video conversion through FFmpeg with presets and manual controls.
- Safe collision policies, filename normalization, cancellation, summaries, JSON reports, and SHA-256.
- Reproducible one-folder Windows build with bundled FFmpeg and runtime diagnostics.
- Automated unit, integration, packaging-resource, and interface-scaling tests.
