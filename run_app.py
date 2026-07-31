"""Dependency-aware application entry point."""

from __future__ import annotations

import sys
from tkinter import Tk, messagebox

from app_logging import configure_logging
from i18n import t
from runtime_environment import INSTALL_COMMAND, missing_python_dependencies


def show_dependency_error(missing: list[str]) -> None:
    root = Tk()
    root.withdraw()
    messagebox.showerror(
        t("launcher.missing_title"),
        t(
            "launcher.missing_body",
            missing=", ".join(missing),
            command=INSTALL_COMMAND,
        ),
    )
    root.destroy()


def main() -> int:
    configure_logging()
    missing = missing_python_dependencies()
    required = [name for name in missing if name == "Pillow"]
    if required:
        show_dependency_error(required)
        return 1
    from ui import main as application_main

    application_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
