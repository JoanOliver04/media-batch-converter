# Changelog

All notable changes are documented here. This project follows [Semantic Versioning](https://semver.org/) and the structure from [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Added

- Language selector for Spanish and English, applied immediately without restarting and persisted with the local settings.
- Message catalogues under `locales/`, with tests that fail when a catalogue is missing a key or a format placeholder.

### Changed

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
