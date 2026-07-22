# Release process

1. Choose a Semantic Versioning number and update `APP_VERSION` in `version.py`.
2. Move relevant entries from Unreleased into a dated section in `CHANGELOG.md`.
3. Run `python -m ruff format --check .`, `python -m ruff check .`, and `python -m unittest discover -s tests -q`.
4. Run `build_windows.bat`.
5. Smoke-test launch, diagnostics, image transparency, audio, video, recursive conversion, cancellation, and clean shutdown.
6. Create `MediaBatchConverter-<version>-windows-x64.zip` containing the complete one-folder distribution.
7. Generate SHA-256 with `Get-FileHash -Algorithm SHA256 <zip>`.
8. Commit the release metadata and create an annotated `v<version>` tag.
9. Push the commit and tag.
10. Create a GitHub Release titled `Media Batch Converter <version>`, using the changelog as release notes.
11. Upload the ZIP and a matching `.sha256` text file, verify the assets, then publish.

Do not commit generated distributions, converted media, logs, reports, or checksums for local test artifacts. Confirm third-party notices before redistributing FFmpeg.
