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
        self.create_assignIP_section()
        self.create_batchIP_section()
        self.create_outputping_section()
# --------------------------------------UI界面布局函数--------------------------------------
    def create_assignIP_section(self):
        # 区域标签
        frame = ttk.LabelFrame(self, text="指定地址 Ping 目标地址")
        frame.pack(side='top', fill='x', padx=10, pady=5)

        self.entry_assignIP_A = self.add_input(frame, "本地IP", row=0, col=0) 
        self.entry_assignIP_B = self.add_input(frame, "目标IP", row=0, col=1, inivar="127.0.0.1") 
        self.assignIP_startPing = self.add_button(frame, "开始", row=0, col=2, command=self.btn_assignIP_startPing)
        self.assignIP_stopPing = self.add_button(frame, "停止", row=0, col=3, command=self.btn_assignIP_stopPing)

    def create_batchIP_section(self):
        # 区域标签
        frame = ttk.LabelFrame(self, text="指定地址 Ping 批量地址")
        frame.pack(side='top', fill='x', padx=10, pady=5)

        self.entry_batchIP_A = self.add_input(frame, "本地IP", row=0, col=0) 
        self.entry_batchIP_B = self.add_input(frame, "C类网段", row=0, col=1, inivar="192.168.1.", entry_width=15) 
        self.entry_batchIP_B_begin = self.add_input(frame, "起始地址", row=0, col=2, inivar="1", entry_width=5) 
        self.entry_batchIP_B_end = self.add_input(frame, "结束地址", row=0, col=3, inivar="255", entry_width=5) 
        self.batchIP_startPing = self.add_button(frame, "开始", row=0, col=4, command=self.btn_batchIP_startPing)
        self.batchIP_stopPing = self.add_button(frame, "停止", row=0, col=5, command=self.btn_batchIP_stopPing)

    def create_outputping_section(self):
        # 区域标签
        frame = ttk.LabelFrame(self, text="PING 结果输出")
        frame.pack(side='top', fill='x', padx=10, pady=5)

        self.result_box = scrolledtext.ScrolledText(frame, width=100, height=20)
        self.result_box.pack(pady=10)
# --------------------------------------按钮回调函数--------------------------------------
    def btn_assignIP_startPing(self):         
        if not self.entry_assignIP_B['var'].get():
            messagebox.showwarning("输入错误", "请输入目标IP或域名！")
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

    def btn_batchIP_startPing(self):
        net_prefix = self.entry_batchIP_B['var'].get()
        start = self.entry_batchIP_B_begin['var'].get()
        end = self.entry_batchIP_B_end['var'].get()
        local_ip = self.entry_batchIP_A['var'].get()
        # ========= 输入参数检查 =========
        if not net_prefix or start is None or end is None:
            messagebox.showwarning("输入错误", "请输入完整的网段、起始地址和结束地址！")
            return
        try:
            start = int(start)
            end = int(end)
        except ValueError:
            messagebox.showwarning("输入错误", "起始地址和结束地址必须是整数！")
            return
        if start < 1 or end > 255:
            messagebox.showwarning("输入错误", "起始地址最小为1，结束地址最大为255！")
            return
        if start > end:
            messagebox.showwarning("输入错误", "起始地址不能大于结束地址！")
            return
        if not net_prefix.endswith('.'):
            messagebox.showwarning("输入错误", "网段必须以 '.' 结尾，例如：192.168.1.")
            return
        if local_ip == "":
            logger.info(f"开始批量 Ping {net_prefix}{start} - {net_prefix}{end}")
        else:
            logger.info(f"开始由{local_ip} 批量 Ping {net_prefix}{start} - {net_prefix}{end}")
        
        self.ping_fun.start_batch_ping(net_prefix, start, end, local_ip=local_ip, callback=self.batchIP_ping_callback)
        self.batchIP_startPing['btn'].config(state='disabled')

    def btn_batchIP_stopPing(self):   
        net_prefix = self.entry_batchIP_B['var'].get()
        start = self.entry_batchIP_B_begin['var'].get()
        end = self.entry_batchIP_B_end['var'].get()
        local_ip = self.entry_batchIP_A['var'].get()
        if local_ip == "":
            logger.info(f"停止批量 Ping {net_prefix}{start} - {net_prefix}{end}")
        else:
            logger.info(f"停止由{local_ip} 批量 Ping {net_prefix}{start} - {net_prefix}{end}")
        self.ping_fun.stop_batch_ping()
        self.batchIP_startPing['btn'].config(state='normal')

    def batchIP_ping_callback(self):
        self.batchIP_startPing['btn'].config(state='normal')






   
        