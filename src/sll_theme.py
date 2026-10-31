"""Southland Labs desktop colors and readable Windows input controls."""
from tkinter import ttk


# Colors from southlandlabs.dev; keep the desktop and setup on one palette.
PAGE = "#141716"
SURFACE = "#1b201e"
RAISED = "#242b26"
FIELD = "#111512"
INK = "#eeede6"
MUTED = "#a5ada7"
ACCENT = "#d5b98c"
ACCENT_HOVER = "#e4cda7"
BORDER = "#343c36"
INPUT_BORDER = "#4c574d"
SELECTION = "#5c533e"
ACCENT_INK = "#191c17"
SUCCESS = "#8dc6a3"
WARNING = "#e1c58b"
ERROR = "#edaaa4"


def configure_text(widget, *, background=None, foreground=None):
    """Theme classic Tk text, including its caret and keyboard selection."""
    widget.configure(background=background or FIELD, foreground=foreground or INK,
        insertbackground=foreground or INK, insertwidth=2,
        selectbackground=SELECTION, selectforeground=INK,
        highlightbackground=BORDER, highlightcolor=ACCENT,
        relief="flat", borderwidth=0, cursor="xterm")


def configure_theme(window):
    """Apply the shared app/setup theme before creating any input controls."""
    style = ttk.Style(window)
    if "clam" in style.theme_names() and style.theme_use() != "clam":
        style.theme_use("clam")
    window.configure(background=PAGE)

    # Classic Text/Listbox widgets do not inherit ttk styles. Set their resource
    # defaults too, so History, Details, and dialogs opened first stay readable.
    for name, value in {
        "*Text.background": FIELD, "*Text.foreground": INK,
        "*Text.insertBackground": INK, "*Text.insertWidth": 2,
        "*Text.selectBackground": SELECTION, "*Text.selectForeground": INK,
        "*Text.highlightBackground": BORDER, "*Text.highlightColor": ACCENT,
        "*Text.cursor": "xterm", "*Listbox.background": FIELD,
        "*Listbox.foreground": INK, "*Listbox.selectBackground": SELECTION,
        "*Listbox.selectForeground": INK, "*Listbox.highlightBackground": BORDER,
        "*Listbox.highlightColor": ACCENT, "*TEntry.cursor": "xterm",
        "*TCombobox.cursor": "xterm", "*TSpinbox.cursor": "xterm",
    }.items():
        window.option_add(name, value)

    style.configure(".", background=PAGE, foreground=INK, font=("Segoe UI", 10))
    for name, background in {
        "TFrame": PAGE, "Page.TFrame": PAGE, "Surface.TFrame": PAGE,
        "Card.TFrame": SURFACE, "Panel.TFrame": SURFACE,
        "Header.TFrame": SURFACE, "Inset.TFrame": RAISED,
        "StatusBar.TFrame": SURFACE,
    }.items():
        style.configure(name, background=background)
    style.configure("Card.TFrame", borderwidth=1, relief="solid", bordercolor=BORDER)
    for name, background, foreground, font in (
        ("Header.TLabel", SURFACE, INK, ("Segoe UI Semibold", 16)),
        ("HeaderHint.TLabel", SURFACE, MUTED, ("Segoe UI", 9)),
        ("Version.TLabel", SURFACE, MUTED, ("Segoe UI", 9)),
        ("BadgeOn.TLabel", SURFACE, SUCCESS, ("Segoe UI Semibold", 9)),
        ("BadgeOff.TLabel", SURFACE, MUTED, ("Segoe UI", 9)),
        ("Section.TLabel", SURFACE, INK, ("Segoe UI Semibold", 11)),
        ("Field.TLabel", RAISED, INK, ("Segoe UI", 9)),
        ("Hint.TLabel", SURFACE, MUTED, ("Segoe UI", 9)),
        ("InsetHint.TLabel", RAISED, MUTED, ("Segoe UI", 9)),
        ("Status.TLabel", SURFACE, MUTED, ("Segoe UI", 9)),
        ("RedWarning.TLabel", RAISED, ERROR, ("Segoe UI Semibold", 9)),
        ("YellowWarning.TLabel", RAISED, WARNING, ("Segoe UI Semibold", 9)),
    ):
        style.configure(name, background=background, foreground=foreground, font=font)
    style.configure("Logo.TLabel", background=SURFACE)
    for name, background in (("TCheckbutton", PAGE), ("Card.TCheckbutton", SURFACE),
                             ("Inset.TCheckbutton", RAISED)):
        style.configure(name, background=background, foreground=INK, padding=(0, 3))
        style.map(name, background=[("active", background)], foreground=[("disabled", MUTED)])

    for name in ("TEntry", "TCombobox", "TSpinbox"):
        # Clam otherwise leaves the black insertion caret on our dark field.
        style.configure(name, fieldbackground=FIELD, foreground=INK,
            insertcolor=INK, insertwidth=2, selectbackground=SELECTION,
            selectforeground=INK, arrowcolor=MUTED, bordercolor=INPUT_BORDER,
            lightcolor=INPUT_BORDER, darkcolor=INPUT_BORDER, padding=(8, 6))
        style.map(name, fieldbackground=[("disabled", RAISED), ("readonly", FIELD)],
            foreground=[("disabled", MUTED), ("readonly", INK)],
            bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
            darkcolor=[("focus", ACCENT)],
            selectbackground=[("readonly", SELECTION)],
            selectforeground=[("readonly", INK)])

    style.configure("TButton", background=RAISED, foreground=INK,
        padding=(12, 7), font=("Segoe UI", 9), bordercolor=BORDER)
    style.map("TButton", background=[("pressed", SURFACE), ("active", BORDER)],
        foreground=[("disabled", MUTED)], bordercolor=[("focus", ACCENT)])
    style.configure("Accent.TButton", background=ACCENT, foreground=ACCENT_INK,
        padding=(14, 7), font=("Segoe UI Semibold", 9), bordercolor=ACCENT)
    style.map("Accent.TButton", background=[("pressed", ACCENT), ("active", ACCENT_HOVER)],
        foreground=[("disabled", "#53564b")], bordercolor=[("focus", INK)])
    style.configure("Endpoint.TButton", background=RAISED, foreground=INK, padding=(14, 7))
    style.configure("EndpointSelected.TButton", background=SELECTION,
        foreground=INK, bordercolor=ACCENT, padding=(14, 7))
    style.map("EndpointSelected.TButton", background=[("active", "#6d6147")])
    style.configure("Horizontal.TProgressbar", background=ACCENT,
        troughcolor=RAISED, borderwidth=0)
    style.configure("Vertical.TScrollbar", background=RAISED,
        troughcolor=PAGE, arrowcolor=MUTED, bordercolor=BORDER)
    style.configure("Horizontal.TScrollbar", background=RAISED,
        troughcolor=PAGE, arrowcolor=MUTED, bordercolor=BORDER)
    style.configure("Treeview", fieldbackground=FIELD, background=FIELD,
        foreground=INK, bordercolor=BORDER)
    style.map("Treeview", background=[("selected", SELECTION)], foreground=[("selected", INK)])
    style.configure("Treeview.Heading", background=SURFACE, foreground=INK)
    return style
