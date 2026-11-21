# Third-party notices

Media Batch Converter source code is licensed under MIT. Third-party components retain their own licenses.

## Pillow

Pillow is installed from PyPI and used for image decoding and encoding. The pinned Pillow 13.0.0 package declares the MIT-CMU license. [Pillow license](https://github.com/python-pillow/Pillow/blob/main/LICENSE)

## imageio-ffmpeg

`imageio-ffmpeg` is installed from PyPI and used to locate a packaged FFmpeg executable. The Python package is distributed under a BSD-2-Clause license. See https://github.com/imageio/imageio-ffmpeg.

## FFmpeg

The public Windows ZIP uses a separately installed FFmpeg executable. Source runs can use the binary provided by `imageio-ffmpeg`. Local Windows builds can bundle that binary or use the executable selected via `MEDIA_BATCH_BUILD_FFMPEG`. Identify the actual binary and corresponding source for any distribution that includes FFmpeg.

The pinned Windows binary is FFmpeg 7.1 essentials from gyan.dev and reports `--enable-gpl --enable-version3`; redistribution must therefore be treated as GPLv3-or-later rather than LGPL-only. A release must retain the applicable notices, identify the exact source at https://www.gyan.dev/ffmpeg/builds/, and satisfy the corresponding-source obligations. Codec patents and other obligations can vary by jurisdiction. See https://ffmpeg.org/legal.html.

## Document libraries

The Files tab uses `python-docx`, `pypdf`, `reportlab`, `openpyxl` and `python-pptx` from PyPI. Each keeps its own license (MIT, BSD-style or Apache, as declared by the installed package). LibreOffice is never bundled; when the user has it installed it is invoked as an optional local engine.

## PyInstaller and Ruff

PyInstaller is a GPLv2-or-later project with an exception that permits distributing bundled applications under other licenses. Ruff is used only during development and is MIT-licensed. Consult each installed distribution for authoritative terms.

This notice is informational and is not legal advice or a legal guarantee.
