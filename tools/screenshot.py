"""Capture application screenshots for the README and other material.

The window is captured with `PrintWindow`, which asks it to draw itself into an
offscreen bitmap. Unlike grabbing a screen region, that captures only this
application: nothing else on the desktop can end up in the image, and the
window does not need to be in the foreground.

The application is built in-process so the tab, language and preset are chosen
directly instead of by simulating clicks, which makes every run reproducible.
Settings are redirected to a temporary directory so capturing never disturbs
the preferences of whoever runs this.

Examples::

    python tools/screenshot.py --all
    python tools/screenshot.py --tab video --language es --output shot.png
    python tools/screenshot.py --tab video --scaling 2 --width 1900 --height 1000

The image is exactly the window's pixels, so its resolution is capped by the
display: a window cannot be requested larger than the screen it lives on.
`--scaling` enlarges the interface rather than the image, which is useful to
check how the layout holds up at 150% or 200%.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import ctypes.wintypes as wintypes
import os
import sys
import tempfile
import tkinter as tk
from collections.abc import Iterator
from pathlib import Path
from tkinter import ttk

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from PIL import Image  # noqa: E402

from i18n import Language, set_language  # noqa: E402
from ui.app import ConverterApp  # noqa: E402

TABS = {"images": 0, "audio": 1, "video": 2, "files": 3, "diagnostics": 4}

#: Preset applied per tab so the screenshots show a populated panel instead of
#: the empty "Custom" state. Each panel exposes its own apply method.
PRESET_METHOD = {
    0: "apply_preset_id",
    1: "apply_audio_preset_id",
    2: "apply_video_preset_id",
    3: "apply_document_preset_id",
}

#: The images referenced by the README.
README_SHOTS = (
    ("images", "images-tab.png", "thumbnail"),
    ("audio", "audio-tab.png", "voice_dialogue"),
    ("video", "video-tab.png", "vertical_social"),
    ("files", "files-tab.png", "document_pdf_archive"),
)


class BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


@contextlib.contextmanager
def isolated_settings() -> Iterator[None]:
    """Point the settings directory at a temporary folder.

    Building a panel persists its preset and output policy, so without this a
    capture would rewrite the real preferences of whoever runs the tool.
    """
    with tempfile.TemporaryDirectory() as temporary:
        previous = {
            name: os.environ.get(name) for name in ("APPDATA", "XDG_CONFIG_HOME")
        }
        os.environ.update(dict.fromkeys(previous, temporary))
        try:
            yield
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def find_notebook(widget: tk.Misc) -> ttk.Notebook | None:
    for child in widget.winfo_children():
        if isinstance(child, ttk.Notebook):
            return child
        found = find_notebook(child)
        if found is not None:
            return found
    return None


def capture(root: tk.Tk, output: Path) -> tuple[int, int]:
    """Save the window's own pixels to `output`."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    handle = int(root.frame(), 16)
    rect = wintypes.RECT()
    user32.GetClientRect(handle, ctypes.byref(rect))
    width, height = rect.right, rect.bottom

    window_dc = user32.GetDC(handle)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    gdi32.SelectObject(memory_dc, bitmap)
    # 3 = PW_CLIENTONLY | PW_RENDERFULLCONTENT
    user32.PrintWindow(handle, memory_dc, 3)

    header = BitmapInfoHeader()
    header.biSize = ctypes.sizeof(BitmapInfoHeader)
    header.biWidth, header.biHeight = width, -height  # negative: top-down
    header.biPlanes, header.biBitCount = 1, 32
    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)

    output.parent.mkdir(parents=True, exist_ok=True)
    Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert(
        "RGB"
    ).save(output)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(handle, window_dc)
    return width, height


def take(
    tab: str,
    output: Path,
    language: str,
    preset: str | None,
    scaling: float,
    size: tuple[int, int] | None,
) -> tuple[int, int]:
    root = tk.Tk()
    try:
        if scaling != 1.0:
            root.tk.call("tk", "scaling", scaling)
        application = ConverterApp(root)
        set_language(Language(language))
        application._rebuild()
        if size:
            root.geometry(f"{size[0]}x{size[1]}")

        index = TABS[tab]
        notebook = find_notebook(root)
        if notebook is None:
            raise SystemExit("the notebook could not be found")
        # Audio and video are disabled when FFmpeg is missing; enable them so
        # the tab can still be shown.
        notebook.tab(index, state="normal")
        notebook.select(index)

        if preset and index in PRESET_METHOD:
            getattr(application.panels[index], PRESET_METHOD[index])(preset)

        root.update()
        root.update_idletasks()
        # Give the toolkit a beat to finish drawing before the bitmap is taken.
        root.after(1200, root.quit)
        root.mainloop()
        return capture(root, output)
    finally:
        root.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tab", choices=sorted(TABS), default="images")
    parser.add_argument(
        "--language", choices=[item.value for item in Language], default="en"
    )
    parser.add_argument("--preset", help="preset id to apply before capturing")
    parser.add_argument("--output", type=Path, help="destination PNG")
    parser.add_argument(
        "--all",
        action="store_true",
        help="regenerate the README screenshots",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT / "docs" / "screenshots",
        help="destination folder for --all",
    )
    parser.add_argument(
        "--scaling",
        type=float,
        default=1.0,
        help=(
            "Tk scaling factor. Shows the interface as a high-DPI user sees it: "
            "it enlarges the contents, it does not add resolution."
        ),
    )
    parser.add_argument(
        "--width", type=int, help="window width; the display size is the ceiling"
    )
    parser.add_argument(
        "--height", type=int, help="window height; the display size is the ceiling"
    )
    arguments = parser.parse_args(argv)

    size = (
        (arguments.width, arguments.height)
        if arguments.width and arguments.height
        else None
    )

    if sys.platform != "win32":
        parser.error("PrintWindow capture is only available on Windows")
    if not arguments.all and arguments.output is None:
        parser.error("--output is required unless --all is used")

    with isolated_settings():
        if arguments.all:
            for tab, filename, preset in README_SHOTS:
                destination = arguments.output_dir / filename
                width, height = take(
                    tab,
                    destination,
                    arguments.language,
                    preset,
                    arguments.scaling,
                    size,
                )
                print(f"{destination}  {width}x{height}")
        else:
            width, height = take(
                arguments.tab,
                arguments.output,
                arguments.language,
                arguments.preset,
                arguments.scaling,
                size,
            )
            print(f"{arguments.output}  {width}x{height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
