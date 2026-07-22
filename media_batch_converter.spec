# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

import imageio_ffmpeg
from PyInstaller.utils.hooks import collect_submodules

project = Path(SPECPATH)
ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())

a = Analysis(
    [str(project / "run_app.py")],
    pathex=[str(project)],
    binaries=[(str(ffmpeg), "ffmpeg")],
    datas=[],
    hiddenimports=collect_submodules("PIL"),
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
