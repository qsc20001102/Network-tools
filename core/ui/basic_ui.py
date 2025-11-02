import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import logging
logger = logging.getLogger(__name__)

class BasicUI:

    def add_input(
            self, parent, label_text, 
            row, col=0, inivar="", 
            label_width=8, entry_width=20, colspan=1, sticky='w'
        ):
        """
        添加一个带文本标签和输入框的组合控件，并返回 (StringVar, Frame) 以便后续控制。
        - parent: 父容器
        - label: 标签文字
        - row, col: 放置在父容器的 grid 行列
        - inivar: 初始值
        - entry_width: 输入框宽度
        - colspan: 该组控件在父容器上跨越的列数
        - sticky: 对齐方式（默认左对齐）
        """
        group_frame = ttk.Frame(parent)
        group_frame.grid(row=row, column=col, columnspan=colspan, sticky=sticky, padx=5, pady=3)

        # 标签
        label = ttk.Label(group_frame, text=label_text + "：", width=label_width, anchor='w').grid(row=0, column=0, sticky='w', padx=(0, 5))

        # 输入框
        var = tk.StringVar(value=inivar)
        entry = ttk.Entry(group_frame, textvariable=var, width=entry_width)
        entry.grid(row=0, column=1, sticky='w')

        return {
            "frame": group_frame,
            "label": label,
            "entry": entry,
            "var": var
        }

    def add_combobox(
        self, parent, label_text, row, col=0,
        listbox=[], inivar=0, width=17, colspan=1,
        sticky='w', label_width=8, state="readonly"
    ):
        """
        创建一组 [标签 + 下拉框] 控件。
        返回 dict，方便外部单独或统一控制。

        - values: 下拉选项列表
        - default: 初始值（可选）
        - state: "readonly" 表示只能从列表选，"normal" 可手动输入
        """
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=col, columnspan=colspan, sticky=sticky, padx=5, pady=3)

        # 标签
        label = ttk.Label(
            frame,
            text=label_text + "：",
            width=label_width,
            anchor='w'
        )
        label.grid(row=0, column=0, sticky='w', padx=(0, 5))

        # 变量 + 下拉框
        var = tk.StringVar()
        combobox = ttk.Combobox(
            frame,
            textvariable=var,
            values=listbox,
            width=width,
            state=state
        )
        combobox.grid(row=0, column=1, sticky='w')
        if inivar>=0:
            var.set(listbox[inivar])

        return {
            "frame": frame,
            "label": label,
            "combobox": combobox,
            "var": var
        }

    def add_button(
                self, parent, button_text, 
                row, col=0, command="", 
                width=5, colspan=1, sticky='w'
            ):
            """
            添加一个按钮，并返回 (StringVar, Frame) 以便后续控制。
            - parent: 父容器
            - button_text: 按钮文本
            - row, col: 放置在父容器的 grid 行列
            - command: 调用的函数
            - width: 按钮宽度
            - colspan: 该组控件在父容器上跨越的列数
            - sticky: 对齐方式（默认左对齐）
            """
            group_frame = ttk.Frame(parent)
            group_frame.grid(row=row, column=col, columnspan=colspan, sticky=sticky, padx=5, pady=3)

            btn = ttk.Button(group_frame, text=button_text, command=command, width=width)
            btn.grid(row=0, column=0, sticky='w')
            return {
                "frame": group_frame,
                "btn": btn,
            }
        