"""Contenedores reutilizables de la interfaz."""

from __future__ import annotations

from tkinter import Canvas, Tk, ttk

from ui.theme import PANEL, SIGNAL


class ScrollableTab(ttk.Frame):
    """Keyboard-accessible viewport that prevents clipping at high DPI."""

    def __init__(self, parent, panel_type, root: Tk) -> None:
        super().__init__(parent)
        self.canvas = Canvas(
            self,
            width=1,
            height=1,
            highlightthickness=1,
            highlightbackground=PANEL,
            highlightcolor=SIGNAL,
            takefocus=True,
            background=PANEL,
        )
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=lambda first, last: self._horizontal_scroll(
                horizontal, first, last
            ),
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.panel = panel_type(self.canvas, root, footer_parent=self)
        self.window_item = self.canvas.create_window(
            (0, 0), window=self.panel, anchor="nw"
        )
        self.panel.bind("<Configure>", self._content_configured)
        self.canvas.bind("<Configure>", self._viewport_configured)
        self.canvas.bind("<MouseWheel>", self._mousewheel)
        self._bind_child_navigation(self.panel)
        self.wide_width = round(root.winfo_fpixels("1i") * 10.5)
        self.canvas.bind("<Prior>", lambda _event: self._scroll_pages(-1))
        self.canvas.bind("<Next>", lambda _event: self._scroll_pages(1))
        self.canvas.bind("<Up>", lambda _event: self._scroll_units(-1))
        self.canvas.bind("<Down>", lambda _event: self._scroll_units(1))

    def _bind_child_navigation(self, widget) -> None:
        widget.bind("<MouseWheel>", self._mousewheel, add="+")
        widget.bind("<FocusIn>", self._reveal_focus, add="+")
        for child in widget.winfo_children():
            self._bind_child_navigation(child)

    def _content_configured(self, _event=None) -> None:
        width = max(self.canvas.winfo_width() - 2, self.panel.winfo_reqwidth())
        if float(self.canvas.itemcget(self.window_item, "width")) != width:
            self.canvas.itemconfigure(self.window_item, width=width)
        self.canvas.configure(scrollregion=self.canvas.bbox(self.window_item))

    def _viewport_configured(self, event) -> None:
        self.panel.reflow(event.width < self.wide_width)
        self._content_configured()

    @staticmethod
    def _horizontal_scroll(scrollbar, first: str, last: str) -> None:
        scrollbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            scrollbar.grid_remove()
        else:
            scrollbar.grid()

    def _reveal_focus(self, event) -> None:
        bounds = self.canvas.bbox(self.window_item)
        if not bounds:
            return
        widget = event.widget
        for position, start, size, viewport, extent, view in (
            (
                widget.winfo_rootx(),
                self.canvas.winfo_rootx(),
                widget.winfo_width(),
                self.canvas.winfo_width(),
                bounds[2],
                self.canvas.xview,
            ),
            (
                widget.winfo_rooty(),
                self.canvas.winfo_rooty(),
                widget.winfo_height(),
                self.canvas.winfo_height(),
                bounds[3],
                self.canvas.yview,
            ),
        ):
            offset = position - start
            scroll = (
                min(0, offset - 8)
                if offset < 8
                else max(0, offset + size + 8 - viewport)
            )
            if scroll and extent > viewport:
                view("moveto", view()[0] + scroll / extent)

    def _mousewheel(self, event) -> str:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _scroll_pages(self, amount: int) -> str:
        self.canvas.yview_scroll(amount, "pages")
        return "break"

    def _scroll_units(self, amount: int) -> str:
        self.canvas.yview_scroll(amount, "units")
        return "break"
