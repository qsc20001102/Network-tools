import tkinter as tk
from tkinter import scrolledtext, messagebox
import subprocess
import platform
import threading
import re

class PingFun:
    def __init__(self, result_box: scrolledtext.ScrolledText):
        self.result_box = result_box

        # Ping 状态和统计
        self.process = None # 子进程对象
        self.stop_flag = False # 停止标志
        self.sent = 0   # 发送的包数
        self.received = 0   # 接收的包数
        self.rtts = []  # 存储延迟值

    def strat_ping(self, host, local_ip=None, callback=None):
        """开始 ping"""
        self.callback = callback

        # 清空显示框和统计数据
        self.result_box.delete('1.0', tk.END)
        self.sent = 0
        self.received = 0
        self.rtts.clear()
        self.stop_flag = False

        command = ['ping', host, '-t']
        if local_ip:
            command += ['-S', local_ip]

        threading.Thread(target=self.ping, args=(command,), daemon=True).start()

    def stop_ping(self):
        """手动停止 ping"""
        if self.process:
            self.process.terminate()  # 立即终止子进程
            self.result_box.insert(tk.END, "\nPing 已手动停止。\n")
            self.result_box.see(tk.END)
            self.process = None
            self.show_statistics()
        
    def ping(self, command):
        """执行 ping 命令并处理输出"""
        rtt_pattern = re.compile(r'时间[=<](\d+)ms', re.IGNORECASE)
        try:
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            for line in iter(self.process.stdout.readline, ''):
                if self.stop_flag:
                    break
                if line:
                    self.result_box.insert(tk.END, line)
                    self.result_box.see(tk.END)
                    self.sent += 1
                    # 解析延迟
                    match = rtt_pattern.search(line)
                    if match:
                        self.received += 1
                        self.rtts.append(float(match.group(1)))
        except Exception as e:
            self.result_box.insert(tk.END, f"Ping 失败: {e}\n")
        finally:
            # 清理进程对象
            self.process = None
            if self.callback:
                self.callback()

    def show_statistics(self):
        """显示统计信息"""
        if self.sent == 0:
            return
        loss = (self.sent - self.received) / self.sent * 100
        stats = f"\n==== Ping 统计 ====\n" \
                f"发送: {self.sent}，接收: {self.received}，丢包率: {loss:.2f}%\n"
        if self.rtts:
            stats += f"最小延迟: {min(self.rtts)} ms，最大延迟: {max(self.rtts)} ms，平均延迟: {sum(self.rtts)/len(self.rtts):.2f} ms\n"
        self.result_box.insert(tk.END, stats)
        self.result_box.see(tk.END)

