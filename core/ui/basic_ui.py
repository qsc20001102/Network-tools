import tkinter as tk
from tkinter import ttk


class BasicUI:
    """旧版页面的兼容辅助类。

    新界面主要使用 core.ui.components；保留这个类是为了兼容后续可能仍引用
    add_input/add_combobox/add_button 的小工具页。
    """

    def add_input(
        self,
        parent,
        label_text,
        row,
        col=0,
        inivar="",
        label_width=8,
        entry_width=20,
        colspan=1,
        sticky="w",
    ):
        group_frame = ttk.Frame(parent)
        group_frame.grid(row=row, column=col, columnspan=colspan, sticky=sticky, padx=5, pady=3)

        label = ttk.Label(group_frame, text=f"{label_text}:", width=label_width, anchor="w")
        label.grid(row=0, column=0, sticky="w", padx=(0, 5))

        var = tk.StringVar(value=inivar)
        entry = ttk.Entry(group_frame, textvariable=var, width=entry_width)
        entry.grid(row=0, column=1, sticky="w")

        return {"frame": group_frame, "label": label, "entry": entry, "var": var}

    def add_combobox(
        self,
        parent,
        label_text,
        row,
        col=0,
        listbox=None,
        inivar=0,
        width=17,
        colspan=1,
        sticky="w",
        label_width=8,
        state="readonly",
    ):
        values = listbox or []
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=col, columnspan=colspan, sticky=sticky, padx=5, pady=3)

        label = ttk.Label(frame, text=f"{label_text}:", width=label_width, anchor="w")
        label.grid(row=0, column=0, sticky="w", padx=(0, 5))

        var = tk.StringVar()
        combobox = ttk.Combobox(frame, textvariable=var, values=values, width=width, state=state)
        combobox.grid(row=0, column=1, sticky="w")
        if values and inivar >= 0:
            var.set(values[inivar])

        return {"frame": frame, "label": label, "combobox": combobox, "var": var}

    def add_button(self, parent, button_text, row, col=0, command=None, width=5, colspan=1, sticky="w"):
        group_frame = ttk.Frame(parent)
        group_frame.grid(row=row, column=col, columnspan=colspan, sticky=sticky, padx=5, pady=3)

        btn = ttk.Button(group_frame, text=button_text, command=command, width=width)
        btn.grid(row=0, column=0, sticky="w")
        return {"frame": group_frame, "btn": btn}
