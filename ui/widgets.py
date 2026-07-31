"""Contenedores reutilizables de la interfaz."""

from __future__ import annotations

from tkinter import Canvas, Tk, ttk


class ScrollableTab(ttk.Frame):
    """Keyboard-accessible viewport that prevents clipping at high DPI."""

    def __init__(self, parent, panel_type, root: Tk) -> None:
        super().__init__(parent)
        self.canvas = Canvas(self, highlightthickness=0, takefocus=True)
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.panel = panel_type(self.canvas, root)
        self.window_item = self.canvas.create_window(
            (0, 0), window=self.panel, anchor="nw"
        )
        self.panel.bind("<Configure>", self._content_configured)
        self.canvas.bind("<Configure>", self._viewport_configured)
        self.canvas.bind("<MouseWheel>", self._mousewheel)
        self._bind_mousewheel(self.panel)
        self.canvas.bind("<Prior>", lambda _event: self._scroll_pages(-1))
        self.canvas.bind("<Next>", lambda _event: self._scroll_pages(1))
        self.canvas.bind("<Up>", lambda _event: self._scroll_units(-1))
        self.canvas.bind("<Down>", lambda _event: self._scroll_units(1))

    def _bind_mousewheel(self, widget) -> None:
        widget.bind("<MouseWheel>", self._mousewheel, add="+")
        for child in widget.winfo_children():
            self._bind_mousewheel(child)

    def _content_configured(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _viewport_configured(self, event) -> None:
        requested = self.panel.winfo_reqwidth()
        self.canvas.itemconfigure(self.window_item, width=max(event.width, requested))

    def _mousewheel(self, event) -> str:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _scroll_pages(self, amount: int) -> str:
        self.canvas.yview_scroll(amount, "pages")
        return "break"

    def _scroll_units(self, amount: int) -> str:
        self.canvas.yview_scroll(amount, "units")
        return "break"
