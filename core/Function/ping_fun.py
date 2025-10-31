import tkinter as tk
from tkinter import scrolledtext, messagebox
import subprocess
import concurrent.futures
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

    # ================= 批量 Ping =================
    def start_batch_ping(self, net_prefix, start, end, local_ip=None, callback=None):
        """
        批量 Ping 多个 IP 地址。
        例如：net_prefix='192.168.1.'  start=1  end=254
        """
        self.callback = callback
        self.stop_flag = False
        self.result_box.delete('1.0', tk.END)
        self.result_box.insert(tk.END, f"开始并发 Ping：{net_prefix}{start} - {net_prefix}{end}\n\n")

        # ---- 启动线程池执行 ----
        self.batch_thread = threading.Thread(
            target=self._concurrent_batch_ping, args=(net_prefix, start, end, local_ip), daemon=True)
        self.batch_thread.start()

    def _ping_one_ip(self, ip, local_ip=None):
        """Ping 单个 IP 地址并返回结果"""
        if self.stop_flag:
            return None

        command = ['ping', ip, '-n', '1', '-w', '1000']
        if local_ip:
            command += ['-S', local_ip]
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, timeout=2)
            if "TTL=" in result.stdout.upper():
                return f"{ip} ✅ 通\n"
            else:
                return f"{ip} ❌ 不通\n"
        except subprocess.TimeoutExpired:
            return f"{ip} ⚠️ 超时\n"
        except Exception as e:
            return f"{ip} 错误: {e}\n"

    def _concurrent_batch_ping(self, net_prefix, start, end, local_ip=None):
        """并发执行批量 Ping"""
        ip_list = [f"{net_prefix}{i}" for i in range(start, end + 1)]

        # 限制最大并发数，防止系统资源耗尽
        max_workers = min(50, len(ip_list))

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ip = {executor.submit(self._ping_one_ip, ip, local_ip): ip for ip in ip_list}

            for future in concurrent.futures.as_completed(future_to_ip):
                if self.stop_flag:
                    break
                result = future.result()
                if result:
                    self.result_box.insert(tk.END, result)
                    self.result_box.see(tk.END)

        if not self.stop_flag:
            self.result_box.insert(tk.END, "\n并发批量 Ping 完成。\n")
        else:
            self.result_box.insert(tk.END, "\n批量 Ping 已停止。\n")
        self.result_box.see(tk.END)
        if self.callback:
            self.callback()

    def stop_batch_ping(self):
        """停止并发批量 ping"""
        if not self.batch_thread or not self.batch_thread.is_alive():
            messagebox.showinfo("提示", "当前没有正在运行的批量 Ping。")
            return
        self.stop_flag = True
        self.result_box.insert(tk.END, "\n正在尝试停止批量 Ping...\n")
        self.result_box.see(tk.END)