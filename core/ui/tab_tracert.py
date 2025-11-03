import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from core.ui.basic_ui import BasicUI
from core.Function.tracert_fun import TracertFun    

import logging
logger = logging.getLogger(__name__)

class TracertTab(ttk.Frame, BasicUI):
    def __init__(self, parent):
        super().__init__(parent)   
        self.tracert_ui()
        self.tracert_fun = TracertFun(self.result_box)

    def tracert_ui(self):
        """tracert界面布局"""
        self.create_targetadd_section()

        self.create_output_section()
# --------------------------------------UI界面布局函数--------------------------------------
    def create_targetadd_section(self):
        # 区域标签
        frame = ttk.LabelFrame(self, text="追踪目标地址")
        frame.pack(side='top', fill='x', padx=10, pady=5)

        self.entry_tracert_add = self.add_input(frame, "目标地址", row=0, col=0, entry_width=40, inivar="202.89.233.100") 
        self.but_tracert_start = self.add_button(frame, "开始追踪", row=0, col=1, width=8, command=self.tracert_start_callback)
        self.but_tracert_stop = self.add_button(frame, "停止追踪", row=0, col=2, width=8, command=self.tracert_stop_callback)

    def create_output_section(self):
        # 区域标签
        frame = ttk.LabelFrame(self, text="结果输出")
        frame.pack(side='top', fill='x', padx=10, pady=5)

        self.result_box = scrolledtext.ScrolledText(frame, width=100, height=25)
        self.result_box.pack(pady=10)
# --------------------------------------按钮回调函数--------------------------------------
    def tracert_start_callback(self):
        """开始追踪按钮回调"""
        target = self.entry_tracert_add['var'].get()
        if not target:
            messagebox.showwarning("输入错误", "请输入目标地址！")
            return
        self.tracert_fun.start_tracert(target)

    def tracert_stop_callback(self):
        """停止追踪按钮回调"""
        self.tracert_fun.stop_tracert()





   
        