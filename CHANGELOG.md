# Changelog

All notable changes are documented here. This project follows [Semantic Versioning](https://semver.org/) and the structure from [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

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
