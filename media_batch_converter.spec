# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

import imageio_ffmpeg
from PyInstaller.utils.hooks import collect_submodules

project = Path(SPECPATH)
configured_ffmpeg = os.environ.get("MEDIA_BATCH_BUILD_FFMPEG")
ffmpeg = Path(configured_ffmpeg or imageio_ffmpeg.get_ffmpeg_exe()).resolve(strict=True)
ffmpeg_license = ffmpeg.with_name("LICENSE")

a = Analysis(
    [str(project / "run_app.py")],
    pathex=[str(project)],
    binaries=[(str(ffmpeg), "ffmpeg")],
    datas=[(str(ffmpeg_license), "ffmpeg")] if ffmpeg_license.is_file() else [],
    hiddenimports=collect_submodules("PIL")
    + collect_submodules("locales")
    + collect_submodules("ui")
    + collect_submodules("documents")
    + collect_submodules("docx")
    + collect_submodules("pypdf")
    + collect_submodules("reportlab")
    + collect_submodules("openpyxl")
    + collect_submodules("pptx"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest", "tests"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MediaBatchConverter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version=str(project / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MediaBatchConverter",
)
