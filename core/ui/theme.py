import tkinter as tk
from tkinter import ttk


COLORS = {
    "bg": "#eef3f8",
    "panel": "#ffffff",
    "panel_alt": "#f7f9fc",
    "sidebar": "#102033",
    "sidebar_hover": "#1a3552",
    "sidebar_active": "#246bfe",
    "text": "#172033",
    "muted": "#607086",
    "border": "#dbe4ef",
    "primary": "#246bfe",
    "primary_dark": "#1451c8",
    "danger": "#df3b3b",
    "success": "#1a9b6c",
    "warning": "#b7791f",
    "console_bg": "#0f1724",
    "console_fg": "#dbeafe",
    "console_muted": "#9fb4d0",
}


FONT_BODY = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 17, "bold")
FONT_SECTION = ("Microsoft YaHei UI", 11, "bold")
FONT_MONO = ("Consolas", 10)


def apply_theme(root: tk.Tk) -> None:
    root.configure(bg=COLORS["bg"])

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", font=FONT_BODY)
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("Panel.TFrame", background=COLORS["panel"])
    style.configure("Alt.TFrame", background=COLORS["panel_alt"])
    style.configure("TLabel", background=COLORS["panel"], foreground=COLORS["text"])
    style.configure("Muted.TLabel", background=COLORS["panel"], foreground=COLORS["muted"], font=FONT_SMALL)
    style.configure("Title.TLabel", background=COLORS["panel"], foreground=COLORS["text"], font=FONT_TITLE)
    style.configure("Section.TLabel", background=COLORS["panel"], foreground=COLORS["text"], font=FONT_SECTION)

    style.configure(
        "TEntry",
        fieldbackground="#ffffff",
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["border"],
        darkcolor=COLORS["border"],
        padding=7,
    )
    style.configure(
        "TCombobox",
        fieldbackground="#ffffff",
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        arrowcolor=COLORS["muted"],
        padding=6,
    )

    style.configure(
        "Primary.TButton",
        background=COLORS["primary"],
        foreground="#ffffff",
        borderwidth=0,
        focusthickness=0,
        padding=(14, 8),
    )
    style.map("Primary.TButton", background=[("active", COLORS["primary_dark"]), ("disabled", "#9bb7f5")])

    style.configure(
        "Secondary.TButton",
        background="#e7eef8",
        foreground=COLORS["text"],
        borderwidth=0,
        padding=(14, 8),
    )
    style.map("Secondary.TButton", background=[("active", "#d6e2f3")])

    style.configure(
        "Danger.TButton",
        background=COLORS["danger"],
        foreground="#ffffff",
        borderwidth=0,
        padding=(14, 8),
    )
    style.map("Danger.TButton", background=[("active", "#bd2929")])


def build_app_icon(size: int = 64) -> tk.PhotoImage:
    image = tk.PhotoImage(width=size, height=size)
    image.put(COLORS["sidebar"], to=(0, 0, size, size))
    image.put(COLORS["primary"], to=(8, 8, size - 8, size - 8))
    image.put("#5eead4", to=(16, 20, 27, 31))
    image.put("#ffffff", to=(37, 20, 48, 31))
    image.put("#ffffff", to=(16, 38, 27, 49))
    image.put("#5eead4", to=(37, 38, 48, 49))
    image.put("#ffffff", to=(24, 25, 41, 29))
    image.put("#ffffff", to=(24, 42, 41, 46))
    image.put("#ffffff", to=(21, 28, 25, 42))
    image.put("#ffffff", to=(39, 28, 43, 42))
    return image
