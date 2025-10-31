import sys
import os
import tkinter as tk

from core.logger_config import setup_logger
from core.ui.ui_main import MainUI

if __name__ == "__main__":
    # 进行日志配置
    setup_logger()
    # 判断是否是打包后的环境
    if getattr(sys, 'frozen', False):
        # 打包后的路径（exe所在的目录）
        base_dir = os.path.dirname(sys.executable)
    else:
        # 普通Python运行时
        base_dir = os.path.dirname(os.path.abspath(__file__))
    # 启动主界面
    root = tk.Tk()
    app = MainUI(root)
    root.mainloop()
