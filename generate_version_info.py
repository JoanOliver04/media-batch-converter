"""Generate PyInstaller Windows version metadata from version.py."""

from pathlib import Path

from version import APP_NAME, APP_VERSION


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in version.split(".")]
    if len(parts) != 3:
        raise ValueError("APP_VERSION must use major.minor.patch")
    return (*parts, 0)


def render_version_info() -> str:
    numeric = ", ".join(str(part) for part in version_tuple(APP_VERSION))
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({numeric}),
    prodvers=({numeric}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable("040904B0", [
        StringStruct("CompanyName", "{APP_NAME} contributors"),
        StringStruct("FileDescription", "{APP_NAME}"),
        StringStruct("FileVersion", "{APP_VERSION}"),
        StringStruct("InternalName", "MediaBatchConverter"),
        StringStruct("OriginalFilename", "MediaBatchConverter.exe"),
        StringStruct("ProductName", "{APP_NAME}"),
        StringStruct("ProductVersion", "{APP_VERSION}"),
      ])
    ]),
    VarFileInfo([VarStruct("Translation", [1033, 1200])]),
  ],
)
"""


if __name__ == "__main__":
    Path("version_info.txt").write_text(render_version_info(), encoding="utf-8")
