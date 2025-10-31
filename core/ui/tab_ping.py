import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from core.ui.basic_ui import BasicUI
from core.Function.ping_fun import PingFun

import logging
logger = logging.getLogger(__name__)

class PingTab(ttk.Frame, BasicUI):
    def __init__(self, parent):
        super().__init__(parent)   
        self.ping_ui()
        self.ping_fun = PingFun(self.result_box)

    def ping_ui(self):
        """ping界面布局"""
        self.create_allIP_section()
        self.create_assignIP_section()
        self.create_outputping_section()
# --------------------------------------UI界面布局函数--------------------------------------
    def create_allIP_section(self):
        # 区域标签
        frame = ttk.LabelFrame(self, text="PING 目标IP")
        frame.pack(side='top', fill='x', padx=10, pady=5)

        self.entry_allIP = self.add_input(frame, "目标IP", row=0, col=0) 
        self.allIP_startPing = self.add_button(frame, "开始ping", row=0, col=1, command=self.btn_allIP_startPing)
        self.allIP_stopPing = self.add_button(frame, "停止ping", row=0, col=2, command=self.btn_allIP_stopPing)

    def create_assignIP_section(self):
        # 区域标签
        frame = ttk.LabelFrame(self, text="指定IP PING 目标IP")
        frame.pack(side='top', fill='x', padx=10, pady=5)

        self.entry_assignIP_A = self.add_input(frame, "本地IP", row=0, col=0) 
        self.entry_assignIP_B = self.add_input(frame, "目标IP", row=0, col=1) 
        self.assignIP_startPing = self.add_button(frame, "开始ping", row=0, col=2, command=self.btn_assignIP_startPing)
        self.assignIP_stopPing = self.add_button(frame, "停止ping", row=0, col=3, command=self.btn_assignIP_stopPing)

    def create_outputping_section(self):
        # 区域标签
        frame = ttk.LabelFrame(self, text="PING 结果输出")
        frame.pack(side='top', fill='x', padx=10, pady=5)

        self.result_box = scrolledtext.ScrolledText(frame, width=100, height=20)
        self.result_box.pack(pady=10)
# --------------------------------------按钮回调函数--------------------------------------
    def btn_allIP_startPing(self):   
        if not self.entry_allIP['var'].get():
            messagebox.showwarning("输入错误", "请输入IP或域名！")
            return   
        logger.info(f"开始Ping {self.entry_allIP['var'].get()}")
        self.ping_fun.strat_ping(self.entry_allIP['var'].get(), callback=self.allIP_ping_callback)
        self.allIP_startPing['btn'].config(state='disabled')

    def btn_allIP_stopPing(self):   
        logger.info(f"停止Ping {self.entry_allIP['var'].get()}")
        self.ping_fun.stop_ping()
        self.allIP_startPing['btn'].config(state='normal')

    def allIP_ping_callback(self):
        self.allIP_startPing['btn'].config(state='normal')

    def btn_assignIP_startPing(self):         
        if not self.entry_assignIP_B['var'].get():
            messagebox.showwarning("输入错误", "请输入IP或域名！")
            return   
        logger.info(f"开始由{self.entry_assignIP_A['var'].get()} Ping {self.entry_assignIP_B['var'].get()}")
        self.ping_fun.strat_ping(self.entry_assignIP_B['var'].get(),local_ip=self.entry_assignIP_A['var'].get(), 
                                 callback=self.assignIP_ping_callback)
        self.assignIP_startPing['btn'].config(state='disabled')

    def btn_assignIP_stopPing(self):   
        logger.info(f"停止由{self.entry_assignIP_A['var'].get()} Ping {self.entry_assignIP_B['var'].get()}")
        self.ping_fun.stop_ping()
        self.assignIP_startPing['btn'].config(state='normal')

    def assignIP_ping_callback(self):
        self.assignIP_startPing['btn'].config(state='normal')






   
        