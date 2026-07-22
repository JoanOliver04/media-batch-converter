# Third-party notices

Media Batch Converter source code is licensed under MIT. Third-party components retain their own licenses.

## Pillow

Pillow is installed from PyPI and used for image decoding and encoding. The pinned Pillow 12.2.0 package declares the MIT-CMU license. See https://github.com/python-pillow/Pillow/blob/main/LICENSE and the installed package metadata.

## imageio-ffmpeg

`imageio-ffmpeg` is installed from PyPI and used to locate a packaged FFmpeg executable. The Python package is distributed under a BSD-2-Clause license. See https://github.com/imageio/imageio-ffmpeg.

## FFmpeg

Windows distributions produced by this repository bundle the FFmpeg executable supplied by the pinned `imageio-ffmpeg` package at build time. No FFmpeg binary is committed to this repository.

The pinned Windows binary is FFmpeg 7.1 essentials from gyan.dev and reports `--enable-gpl --enable-version3`; redistribution must therefore be treated as GPLv3-or-later rather than LGPL-only. A release must retain the applicable notices, identify the exact source at https://www.gyan.dev/ffmpeg/builds/, and satisfy the corresponding-source obligations. Codec patents and other obligations can vary by jurisdiction. See https://ffmpeg.org/legal.html.

## PyInstaller and Ruff

PyInstaller is a GPLv2-or-later project with an exception that permits distributing bundled applications under other licenses. Ruff is used only during development and is MIT-licensed. Consult each installed distribution for authoritative terms.

This notice is informational and is not legal advice or a legal guarantee.
