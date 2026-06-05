import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import Callable, Optional

from core.ui.theme import COLORS, FONT_MONO, FONT_SECTION, FONT_SMALL


class Console:
    def __init__(self, parent, height: int = 16):
        self.widget = scrolledtext.ScrolledText(
            parent,
            height=height,
            wrap="word",
            bg=COLORS["console_bg"],
            fg=COLORS["console_fg"],
            insertbackground=COLORS["console_fg"],
            selectbackground="#2b4a6f",
            relief="flat",
            borderwidth=0,
            font=FONT_MONO,
            padx=14,
            pady=12,
        )
        self.widget.tag_config("muted", foreground=COLORS["console_muted"])
        self.widget.tag_config("success", foreground="#86efac")
        self.widget.tag_config("warning", foreground="#fde68a")
        self.widget.tag_config("error", foreground="#fca5a5")

    def grid(self, **kwargs):
        self.widget.grid(**kwargs)

    def pack(self, **kwargs):
        self.widget.pack(**kwargs)

    def clear(self) -> None:
        self.widget.delete("1.0", tk.END)

    def write(self, text: str, tag: Optional[str] = None) -> None:
        def append():
            self.widget.insert(tk.END, text, tag)
            self.widget.see(tk.END)

        self.widget.after(0, append)


class Page(ttk.Frame):
    def __init__(self, parent, title: str, subtitle: str):
        super().__init__(parent, style="Panel.TFrame")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text=title, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=subtitle, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

        body_shell = ttk.Frame(self, style="Panel.TFrame")
        body_shell.grid(row=1, column=0, sticky="nsew", padx=28, pady=(4, 20))
        body_shell.columnconfigure(0, weight=1)
        body_shell.rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(body_shell, bg=COLORS["panel"], highlightthickness=0, bd=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(body_shell, orient="vertical", command=self._canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self.body = ttk.Frame(self._canvas, style="Panel.TFrame")
        self.body.columnconfigure(0, weight=1)
        self._body_window = self._canvas.create_window((0, 0), window=self.body, anchor="nw")

        self.body.bind("<Configure>", self._update_scroll_region)
        self._canvas.bind("<Configure>", self._resize_body)
        self._bind_mousewheel(self._canvas)

    def section(self, title: str, row: int, columns: int = 4):
        frame = tk.Frame(self.body, bg=COLORS["panel"], highlightbackground=COLORS["border"], highlightthickness=1)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 14))
        for col in range(columns):
            frame.columnconfigure(col, weight=1)

        ttk.Label(frame, text=title, style="Section.TLabel").grid(
            row=0, column=0, columnspan=columns, sticky="w", padx=18, pady=(14, 8)
        )
        return frame

    def _update_scroll_region(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _resize_body(self, event) -> None:
        self._canvas.itemconfigure(self._body_window, width=event.width)

    def _bind_mousewheel(self, widget) -> None:
        widget.bind("<Enter>", lambda _event: widget.bind_all("<MouseWheel>", self._on_mousewheel))
        widget.bind("<Leave>", lambda _event: widget.unbind_all("<MouseWheel>"))

    def _on_mousewheel(self, event) -> None:
        if not self.winfo_ismapped():
            return
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


def field(parent, label: str, row: int, column: int, value: str = "", width: int = 24, colspan: int = 1):
    frame = ttk.Frame(parent, style="Panel.TFrame")
    frame.grid(row=row, column=column, columnspan=colspan, sticky="ew", padx=18, pady=(4, 14))
    frame.columnconfigure(0, weight=1)

    ttk.Label(frame, text=label, style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 5))
    var = tk.StringVar(value=value)
    entry = ttk.Entry(frame, textvariable=var, width=width)
    entry.grid(row=1, column=0, sticky="ew")
    return {"frame": frame, "var": var, "entry": entry}


def combo(parent, label: str, row: int, column: int, values=None, value: str = "", width: int = 24, colspan: int = 1):
    values = values or []
    frame = ttk.Frame(parent, style="Panel.TFrame")
    frame.grid(row=row, column=column, columnspan=colspan, sticky="ew", padx=18, pady=(4, 14))
    frame.columnconfigure(0, weight=1)

    ttk.Label(frame, text=label, style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 5))
    var = tk.StringVar(value=value)
    control = ttk.Combobox(frame, textvariable=var, values=values, width=width, state="readonly")
    control.grid(row=1, column=0, sticky="ew")
    return {"frame": frame, "var": var, "combobox": control}


def action_bar(parent, row: int, columnspan: int = 4):
    frame = ttk.Frame(parent, style="Panel.TFrame")
    frame.grid(row=row, column=0, columnspan=columnspan, sticky="ew", padx=18, pady=(0, 16))
    return frame


def button(parent, text: str, command: Callable, style: str = "Secondary.TButton"):
    btn = ttk.Button(parent, text=text, command=command, style=style)
    btn.pack(side="left", padx=(0, 10))
    return btn


def set_entry_state(item, enabled: bool) -> None:
    item["entry"].configure(state="normal" if enabled else "disabled")
