# Release process

1. Choose a Semantic Versioning number and update `APP_VERSION` in `version.py`.
2. Move relevant entries from Unreleased into a dated section in `CHANGELOG.md`.
3. Run `python -m ruff format --check .`, `python -m ruff check .`, and `python -m unittest discover -s tests -q`.
4. Set `MEDIA_BATCH_BUILD_WITHOUT_FFMPEG=1` for the public Windows ZIP and run `build_windows.bat`. Set `MEDIA_BATCH_DIST_PATH` and `MEDIA_BATCH_WORK_PATH` to build in separate directories when retaining previous builds.
5. Smoke-test launch, diagnostics, image transparency, recursive conversion, cancellation, and clean shutdown. Test audio and video with a separate FFmpeg executable, using the same setup described in the README.
6. Create `MediaBatchConverter-<version>-windows-x64.zip` containing the complete one-folder distribution, the project license and applicable dependency notices. Confirm that the archive has no FFmpeg binary.
7. Generate SHA-256 with `Get-FileHash -Algorithm SHA256 <zip>`.
8. Commit the release metadata and create an annotated `v<version>` tag.
9. Push the commit and tag.
10. Create a GitHub Release titled `Media Batch Converter <version>`, using the changelog as release notes.
11. Upload the ZIP and a matching `.sha256` text file, verify the assets, then publish.

Do not commit generated distributions, converted media, logs, reports, or checksums for local test artifacts. Confirm third-party notices before redistributing FFmpeg.
