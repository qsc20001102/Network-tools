import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from core.ui.basic_ui import BasicUI
from core.ui.tab_ping import PingTab

import logging
logger = logging.getLogger(__name__)

class MainUI(BasicUI):
    def __init__(self, root):
        self.root = root
        self.root.title("Network tools")   # 窗口标题
        self.root.geometry("800x500")  # 窗口大小
        root.resizable(False, False)    # 禁止水平和垂直调整大小
        # 创建 Notebook 作为多标签页容器
        self.tab_control = ttk.Notebook(root)
        self.tab_control.pack(expand=1, fill="both")
        # 实例化各个功能页
        self.tabs = {
            "Ping测试": PingTab(self.tab_control),
        }
        # 添加到 Notebook
        for name, tab in self.tabs.items():
            self.tab_control.add(tab, text=name)