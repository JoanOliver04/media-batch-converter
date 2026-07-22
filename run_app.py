"""Dependency-aware application entry point."""

from __future__ import annotations

import sys
from tkinter import Tk, messagebox

from app_logging import configure_logging
from runtime_environment import INSTALL_COMMAND, missing_python_dependencies


def show_dependency_error(missing: list[str]) -> None:
    root = Tk()
    root.withdraw()
    messagebox.showerror(
        "Faltan dependencias",
        "No se puede iniciar porque faltan: "
        + ", ".join(missing)
        + ".\n\nInstálalas de forma explícita con:\n"
        + INSTALL_COMMAND
        + "\n\nLa aplicación nunca ejecuta pip automáticamente.",
    )
    root.destroy()


def main() -> int:
    configure_logging()
    missing = missing_python_dependencies()
    required = [name for name in missing if name == "Pillow"]
    if required:
        show_dependency_error(required)
        return 1
    from png_a_webp import main as application_main

    application_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
