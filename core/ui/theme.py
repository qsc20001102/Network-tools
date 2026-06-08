import tkinter as tk
from tkinter import ttk


COLORS = {
    "bg": "#f4f7fb",
    "panel": "#ffffff",
    "panel_alt": "#f8fafc",
    "topbar": "#071424",
    "sidebar": "#0b1b2f",
    "sidebar_hover": "#132943",
    "sidebar_active": "#2f6df6",
    "text": "#0f1f35",
    "muted": "#5f7088",
    "border": "#dce5f0",
    "border_dark": "#cbd8e6",
    "primary": "#2f6df6",
    "primary_dark": "#1f56d8",
    "primary_soft": "#edf4ff",
    "danger": "#ef4444",
    "danger_soft": "#fff1f2",
    "success": "#16a36a",
    "success_soft": "#dcfce7",
    "warning": "#b7791f",
    "console_bg": "#07111f",
    "console_fg": "#dbeafe",
    "console_muted": "#93a8c5",
    "console_accent": "#22d3ee",
}


FONT_BODY = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 18, "bold")
FONT_SECTION = ("Microsoft YaHei UI", 12, "bold")
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
    style.configure("Page.TFrame", background=COLORS["bg"])
    style.configure("TLabel", background=COLORS["panel"], foreground=COLORS["text"])
    style.configure("Muted.TLabel", background=COLORS["panel"], foreground=COLORS["muted"], font=FONT_SMALL)
    style.configure("PageMuted.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=FONT_SMALL)
    style.configure("Title.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=FONT_TITLE)
    style.configure("Section.TLabel", background=COLORS["panel"], foreground=COLORS["text"], font=FONT_SECTION)

    style.configure(
        "TEntry",
        fieldbackground="#ffffff",
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["border"],
        darkcolor=COLORS["border"],
        relief="solid",
        padding=(10, 8),
    )
    style.map("TEntry", bordercolor=[("focus", COLORS["primary"]), ("disabled", COLORS["border"])])
    style.configure(
        "TCombobox",
        fieldbackground="#ffffff",
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        arrowcolor=COLORS["muted"],
        relief="solid",
        padding=(10, 7),
    )
    style.map("TCombobox", bordercolor=[("focus", COLORS["primary"])], fieldbackground=[("readonly", "#ffffff")])

    style.configure(
        "Primary.TButton",
        background=COLORS["primary"],
        foreground="#ffffff",
        borderwidth=1,
        bordercolor=COLORS["primary"],
        focusthickness=0,
        padding=(16, 9),
    )
    style.map(
        "Primary.TButton",
        background=[("active", COLORS["primary_dark"]), ("disabled", "#a9c0f4")],
        bordercolor=[("active", COLORS["primary_dark"]), ("disabled", "#a9c0f4")],
        foreground=[("disabled", "#eef4ff")],
    )

    style.configure(
        "Secondary.TButton",
        background="#ffffff",
        foreground=COLORS["primary"],
        borderwidth=1,
        bordercolor="#bcd0ff",
        lightcolor="#bcd0ff",
        darkcolor="#bcd0ff",
        focusthickness=0,
        padding=(16, 9),
    )
    style.map(
        "Secondary.TButton",
        background=[("active", COLORS["primary_soft"]), ("disabled", "#f1f5f9")],
        foreground=[("disabled", "#9aa8ba")],
        bordercolor=[("active", COLORS["primary"]), ("disabled", COLORS["border"])],
    )

    style.configure(
        "Danger.TButton",
        background="#ffffff",
        foreground=COLORS["danger"],
        borderwidth=1,
        bordercolor="#fca5a5",
        lightcolor="#fca5a5",
        darkcolor="#fca5a5",
        focusthickness=0,
        padding=(16, 9),
    )
    style.map("Danger.TButton", background=[("active", COLORS["danger_soft"])], bordercolor=[("active", COLORS["danger"])])

    style.configure(
        "Treeview",
        background="#ffffff",
        fieldbackground="#ffffff",
        foreground=COLORS["text"],
        rowheight=30,
        bordercolor=COLORS["border"],
        borderwidth=1,
    )
    style.configure(
        "Treeview.Heading",
        background=COLORS["panel_alt"],
        foreground=COLORS["muted"],
        font=("Microsoft YaHei UI", 9, "bold"),
        relief="flat",
        padding=(8, 7),
    )
    style.map("Treeview", background=[("selected", COLORS["primary_soft"])], foreground=[("selected", COLORS["text"])])

    style.configure("TNotebook", background=COLORS["panel"], borderwidth=0)
    style.configure("TNotebook.Tab", padding=(18, 8), background=COLORS["panel_alt"], foreground=COLORS["muted"])
    style.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", COLORS["primary"])])

    style.configure(
        "Modern.Vertical.TScrollbar",
        gripcount=0,
        background="#d7e0ec",
        darkcolor="#d7e0ec",
        lightcolor="#d7e0ec",
        troughcolor=COLORS["bg"],
        bordercolor=COLORS["bg"],
        arrowcolor=COLORS["muted"],
        relief="flat",
        width=10,
    )
    style.map("Modern.Vertical.TScrollbar", background=[("active", "#bfccdc")])


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
