# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

import imageio_ffmpeg
from PyInstaller.utils.hooks import collect_submodules

project = Path(SPECPATH)
binaries = []
datas = [(str(project / "assets" / "app-icon.png"), "assets")]
exclude_ffmpeg = os.environ.get("MEDIA_BATCH_BUILD_WITHOUT_FFMPEG") == "1"
excludes = ["pytest", "unittest", "tests"]
if exclude_ffmpeg:
    excludes.append("imageio_ffmpeg")
if not exclude_ffmpeg:
    configured_ffmpeg = os.environ.get("MEDIA_BATCH_BUILD_FFMPEG")
    ffmpeg = Path(configured_ffmpeg or imageio_ffmpeg.get_ffmpeg_exe()).resolve(
        strict=True
    )
    binaries.append((str(ffmpeg), "ffmpeg"))
    ffmpeg_license = ffmpeg.with_name("LICENSE")
    if ffmpeg_license.is_file():
        datas.append((str(ffmpeg_license), "ffmpeg"))

a = Analysis(
    [str(project / "run_app.py")],
    pathex=[str(project)],
    binaries=binaries,
    datas=datas,
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
    excludes=excludes,
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
    icon=str(project / "assets" / "app-icon.ico"),
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
