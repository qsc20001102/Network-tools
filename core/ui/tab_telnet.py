import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from core.ui.basic_ui import BasicUI
from core.Function.telnet_fun import PortScanner

import logging
logger = logging.getLogger(__name__)

class TelnetTab(ttk.Frame, BasicUI):
    def __init__(self, parent):
        super().__init__(parent)   
        self.telnet_ui()
        self.telnet_fun = PortScanner(self.result_box)

    def telnet_ui(self):
        """端口扫描界面布局"""
        self.create_assigntelnet_section()
        self.create_batchtelnet_section()
        self.create_outputping_section()
# --------------------------------------UI界面布局函数--------------------------------------
    def create_assigntelnet_section(self):
        # 区域标签
        frame = ttk.LabelFrame(self, text="指定端口连接测试")
        frame.pack(side='top', fill='x', padx=10, pady=5)

        #self.entry_assignIP_A = self.add_input(frame, "本地IP", row=0, col=0) 
        self.assignTelnet_IP = self.add_input(frame, "目标IP", row=0, col=0, inivar="202.89.233.100") 
        self.assignTelnet_port = self.add_input(frame, "目标端口", row=0, col=1, inivar="443", entry_width=10) 
        self.assignTelnet_test = self.add_button(frame, "测试", row=0, col=2, command=self.btn_assignTelnet_test)
    
    def create_batchtelnet_section(self):
        # 区域标签
        frame = ttk.LabelFrame(self, text="批量端口连接测试")
        frame.pack(side='top', fill='x', padx=10, pady=5)

        self.batchTelnet_IP = self.add_input(frame, "目标IP", row=0, col=0, inivar="202.89.233.100") 
        self.batchTelnet_port_begin = self.add_input(frame, "起始端口", row=0, col=1, inivar="100", entry_width=10) 
        self.batchTelnet_port_end = self.add_input(frame, "结束端口", row=0, col=2, inivar="1000", entry_width=10) 
        self.batchTelnet_start = self.add_button(frame, "开始", row=0, col=3, command=self.btn_batchTelnet_start)
        self.batchTelnet_stop = self.add_button(frame, "停止", row=0, col=4, command=self.btn_batchTelnet_stop)

    def create_outputping_section(self):
        # 区域标签
        frame = ttk.LabelFrame(self, text="端口扫描结果输出")
        frame.pack(side='top', fill='x', padx=10, pady=5)

        self.result_box = scrolledtext.ScrolledText(frame, width=100, height=20)
        self.result_box.pack(pady=10)
# --------------------------------------按钮回调函数--------------------------------------
    def btn_assignTelnet_test(self):  
        self.IP = self.assignTelnet_IP['var'].get()  
        self.port = self.assignTelnet_port['var'].get()   
        if not self.IP:
            messagebox.showwarning("输入错误", "请输入目标IP或域名！")
            return   
        if not self.port:
            messagebox.showwarning("输入错误", "请输入目标端口！")
            return
        try:
            port = int(self.port)
        except ValueError:
            messagebox.showwarning("输入错误", "端口必须是整数！")
            return
        if port < 1 or port > 65535:
            messagebox.showwarning("输入错误", "起始端口最小为1，结束端口最大为65535！")
            return
        logger.info(f"测试{self.IP} 的 {port} 端口连接情况")
        self.telnet_fun.test_connect(self.IP, port)

    def btn_batchTelnet_start(self):  
        self.IP = self.batchTelnet_IP['var'].get()  
        self.port_begin = self.batchTelnet_port_begin['var'].get()   
        self.port_end = self.batchTelnet_port_end['var'].get()
        if not self.IP:
            messagebox.showwarning("输入错误", "请输入目标IP或域名！")
            return   
        if not self.port_begin or not self.port_end:
            messagebox.showwarning("输入错误", "请输入目标端口！")
            return
        try:
            port_begin = int(self.port_begin)
            port_end = int(self.port_end)
        except ValueError:
            messagebox.showwarning("输入错误", "端口必须是整数！")
            return
        if port_begin < 1 or port_end > 65535:
            messagebox.showwarning("输入错误", "起始端口最小为1，结束端口最大为65535！")
            return
        logger.info(f"开始测试{self.IP} 的 {port_begin} 到 {port_end} 端口连接情况")
        self.batchTelnet_start['btn'].config(state='disabled')
        self.telnet_fun.start_range_scan(self.IP, port_begin, port_end)
        
    def btn_batchTelnet_stop(self):
        logger.info(f"停止测试{self.IP} 的端口连接情况")
        self.telnet_fun.stop_scan()
        self.batchTelnet_start['btn'].config(state='normal')

    def batchTelnet_callback(self):
        self.batchTelnet_start['btn'].config(state='normal')




   
        