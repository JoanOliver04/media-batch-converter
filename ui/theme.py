"""Identidad visual: consola de codificación.

La aplicación es un instrumento, no un formulario. La paleta parte de un
grafito frío (pantalla calibrada) con un único acento ámbar, el color de la
aguja de un vúmetro, reservado a la ruta activa: acción principal, pestaña
seleccionada, progreso y foco. Un teal apagado marca lo verificado.

Las cifras van en monoespaciada. En una herramienta de codificación los
números —calidad, tamaños, dimensiones— son datos que se comparan, y alinearlos
es lo que distingue un panel de control de una ventana de ajustes.
"""

from __future__ import annotations

from tkinter import Tk, ttk

# --- Paleta -----------------------------------------------------------------
SURFACE = "#171A21"  # fondo de ventana
PANEL = "#1F242D"  # superficies elevadas
RAISED = "#272E39"  # campos y controles
LINE = "#333C49"  # filetes y bordes
TEXT = "#E6E9EF"  # texto principal
MUTED = "#8A94A6"  # texto de apoyo
SIGNAL = "#E0A33E"  # acento: ruta activa
SIGNAL_DIM = "#B27F2C"  # acento pulsado
VERIFY = "#4FB3A0"  # verificado

# --- Tipografía -------------------------------------------------------------
FONT_TITLE = ("Segoe UI Semibold", 19)
FONT_WORDMARK = ("Segoe UI Semibold", 11)
FONT_BODY = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
#: Consolas para datos y para los rótulos técnicos de cada bloque.
FONT_DATA = ("Consolas", 10)
FONT_EYEBROW = ("Consolas", 9)


def apply_theme(root: Tk) -> ttk.Style:
    """Aplica la identidad a toda la aplicación.

    Se parte de `clam` porque es el único tema de ttk que permite recolorear
    bordes y troughs; los temas nativos ignoran buena parte de estas opciones.
    """
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=SURFACE)

    # La lista desplegable de un Combobox es un Listbox de Tk, no un widget
    # ttk, así que solo se puede recolorear por la base de datos de opciones.
    root.option_add("*TCombobox*Listbox.background", RAISED)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SIGNAL)
    root.option_add("*TCombobox*Listbox.selectForeground", SURFACE)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    style.configure(".", background=PANEL, foreground=TEXT, font=FONT_BODY)
    style.configure("TFrame", background=PANEL)
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("Line.TFrame", background=LINE)

    style.configure("TLabel", background=PANEL, foreground=TEXT, font=FONT_BODY)
    style.configure("Title.TLabel", font=FONT_TITLE, foreground=TEXT)
    style.configure(
        "Wordmark.TLabel", font=FONT_WORDMARK, foreground=TEXT, background=SURFACE
    )
    style.configure(
        "Tagline.TLabel", font=FONT_SMALL, foreground=MUTED, background=SURFACE
    )
    style.configure(
        "HeaderLabel.TLabel", font=FONT_SMALL, foreground=MUTED, background=SURFACE
    )
    style.configure("Muted.TLabel", font=FONT_SMALL, foreground=MUTED)
    style.configure("Readout.TLabel", font=FONT_DATA, foreground=SIGNAL)
    style.configure("Verified.TLabel", font=FONT_SMALL, foreground=VERIFY)

    # --- Botones ---
    style.configure(
        "TButton",
        background=RAISED,
        foreground=TEXT,
        bordercolor=LINE,
        lightcolor=RAISED,
        darkcolor=RAISED,
        focusthickness=1,
        focuscolor=SIGNAL,
        borderwidth=1,
        padding=(14, 7),
        font=FONT_BODY,
    )
    style.map(
        "TButton",
        background=[("pressed", LINE), ("active", LINE), ("disabled", PANEL)],
        foreground=[("disabled", MUTED)],
        bordercolor=[("active", SIGNAL)],
    )
    # La acción principal es el único elemento relleno de ámbar de la ventana.
    style.configure(
        "Accent.TButton",
        background=SIGNAL,
        foreground=SURFACE,
        bordercolor=SIGNAL,
        lightcolor=SIGNAL,
        darkcolor=SIGNAL,
        focuscolor=SURFACE,
        font=("Segoe UI Semibold", 10),
        padding=(18, 7),
    )
    style.map(
        "Accent.TButton",
        background=[
            ("pressed", SIGNAL_DIM),
            ("active", SIGNAL_DIM),
            ("disabled", RAISED),
        ],
        foreground=[("disabled", MUTED)],
        bordercolor=[("disabled", LINE)],
    )

    # --- Campos ---
    for widget in ("TEntry", "TCombobox"):
        style.configure(
            widget,
            fieldbackground=RAISED,
            background=RAISED,
            foreground=TEXT,
            bordercolor=LINE,
            lightcolor=LINE,
            darkcolor=LINE,
            arrowcolor=MUTED,
            insertcolor=TEXT,
            borderwidth=1,
            padding=5,
        )
        # `lightcolor` es el bisel superior del campo: sin mapearlo, clam lo
        # deja blanco y el borde canta sobre el fondo oscuro.
        style.map(
            widget,
            fieldbackground=[("readonly", RAISED), ("disabled", PANEL)],
            foreground=[("disabled", MUTED)],
            bordercolor=[("focus", SIGNAL), ("readonly", LINE), ("disabled", LINE)],
            lightcolor=[("focus", SIGNAL), ("readonly", LINE), ("disabled", LINE)],
            darkcolor=[("focus", SIGNAL), ("readonly", LINE), ("disabled", LINE)],
            arrowcolor=[("disabled", LINE), ("active", SIGNAL)],
        )

    # El marco claro de las casillas lo dibujan upperbordercolor/lowerbordercolor;
    # sin recolorearlos, clam las deja con un bisel blanco sobre el grafito.
    style.configure(
        "TCheckbutton",
        background=PANEL,
        foreground=TEXT,
        indicatorbackground=RAISED,
        indicatorforeground=SURFACE,
        upperbordercolor=LINE,
        lowerbordercolor=LINE,
        indicatorsize=11,
        focusthickness=1,
        focuscolor=SIGNAL,
        padding=3,
    )
    style.map(
        "TCheckbutton",
        indicatorbackground=[("selected", SIGNAL), ("disabled", PANEL)],
        upperbordercolor=[("selected", SIGNAL), ("disabled", LINE)],
        lowerbordercolor=[("selected", SIGNAL), ("disabled", LINE)],
        foreground=[("disabled", MUTED)],
    )
    style.configure(
        "TRadiobutton",
        background=PANEL,
        foreground=TEXT,
        indicatorbackground=RAISED,
        indicatorforeground=SIGNAL,
        upperbordercolor=LINE,
        lowerbordercolor=LINE,
        indicatorsize=10,
        focusthickness=1,
        focuscolor=SIGNAL,
        padding=3,
    )
    style.map(
        "TRadiobutton",
        indicatorbackground=[("disabled", PANEL)],
        upperbordercolor=[("selected", SIGNAL), ("disabled", LINE)],
        lowerbordercolor=[("selected", SIGNAL), ("disabled", LINE)],
        foreground=[("disabled", MUTED)],
    )

    # --- Medidores: calidad y progreso comparten el mismo lenguaje ámbar ---
    meter = dict(
        background=SIGNAL,
        troughcolor=RAISED,
        bordercolor=LINE,
        lightcolor=SIGNAL,
        darkcolor=SIGNAL_DIM,
    )
    # `TScale` además de `Horizontal.TScale`: el trough del Scale resuelve el
    # color desde el estilo sin orientación, así que configurar solo el
    # horizontal deja el canal con el gris por defecto de clam.
    style.configure("TScale", **meter, gripcount=0, sliderlength=18)
    style.configure("Horizontal.TScale", **meter, gripcount=0, sliderlength=18)
    style.configure("Horizontal.TProgressbar", **meter, thickness=6)

    # --- Bloques ---
    style.configure(
        "TLabelframe",
        background=PANEL,
        bordercolor=LINE,
        lightcolor=LINE,
        darkcolor=LINE,
        borderwidth=1,
        relief="solid",
    )
    style.configure(
        "TLabelframe.Label", background=PANEL, foreground=SIGNAL, font=FONT_EYEBROW
    )

    # --- Pestañas: control segmentado, la activa se funde con el panel ---
    style.configure(
        "TNotebook",
        background=SURFACE,
        borderwidth=0,
        bordercolor=PANEL,
        lightcolor=PANEL,
        darkcolor=PANEL,
        tabmargins=(10, 8, 10, 0),
    )
    style.configure(
        "TNotebook.Tab",
        background=SURFACE,
        foreground=MUTED,
        bordercolor=SURFACE,
        lightcolor=SURFACE,
        darkcolor=SURFACE,
        borderwidth=0,
        padding=(18, 9),
        font=FONT_BODY,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", PANEL), ("active", PANEL)],
        lightcolor=[("selected", PANEL), ("active", PANEL)],
        darkcolor=[("selected", PANEL), ("active", PANEL)],
        bordercolor=[("selected", PANEL), ("active", PANEL)],
        foreground=[("selected", SIGNAL), ("active", TEXT), ("disabled", LINE)],
    )

    for name in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(
            name,
            background=RAISED,
            troughcolor=SURFACE,
            bordercolor=SURFACE,
            lightcolor=RAISED,
            darkcolor=RAISED,
            arrowcolor=MUTED,
            borderwidth=0,
            gripcount=0,
        )
        style.map(
            name,
            background=[("pressed", SIGNAL), ("active", LINE)],
            lightcolor=[("pressed", SIGNAL), ("active", LINE)],
            darkcolor=[("pressed", SIGNAL), ("active", LINE)],
            arrowcolor=[("active", TEXT)],
        )
    return style
