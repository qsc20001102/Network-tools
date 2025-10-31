import socket
import threading
import concurrent.futures
import tkinter as tk
from tkinter import scrolledtext, messagebox
from typing import Iterable, Optional, List


class PortScanner:
    """
    PortScanner: 在 Tkinter 的 ScrolledText 中显示端口检测结果的工具类。

    构造：
        scanner = PortScanner(result_box)

    方法：
        test_connect(ip, port, timeout=1.0)
            - 直接测试单个 ip:port 是否可连通（立即返回 bool，并在结果框显示一行结果）

        start_range_scan(ip, start_port, end_port, timeout=1.0, max_workers=100)
            - 并发扫描端口范围 [start_port, end_port]（包含端口边界）
            - 扫描结果会实时写入 result_box

        start_list_scan(ip, ports: Iterable[int], timeout=1.0, max_workers=100)
            - 并发扫描给定端口列表

        stop_scan()
            - 尝试中止正在进行的扫描（设置停止标志，后续任务检测到后会停止提交或返回）

    注意：
        - 使用 TCP 连接测试（socket.connect），适合服务端口检测。
        - GUI 写入通过 self._append_text(...) 调度到主线程，保证线程安全。
    """

    def __init__(self, result_box: scrolledtext.ScrolledText):
        self.result_box = result_box

        # 扫描控制状态
        self._stop_flag = False               # 外部调用 stop_scan() 会把此标志设为 True
        self._scan_thread: Optional[threading.Thread] = None
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

        # 用于统计（可选）
        self._total = 0
        self._done = 0
        self._open_ports: List[int] = []

    # -------------------------
    # 辅助方法：线程安全地向结果框写文本
    # -------------------------
    def _append_text(self, text: str):
        """
        把文本插入到 result_box。因为可能从子线程调用，所以用 after 调度到主线程执行。
        """
        try:
            # schedule on main thread immediately
            self.result_box.after(0, lambda: (self.result_box.insert(tk.END, text), self.result_box.see(tk.END)))
        except Exception:
            # 在极少数情况下（例如 result_box 已销毁），捕获异常避免崩溃
            pass

    # -------------------------
    # 单端口测试
    # -------------------------
    def test_connect(self, ip: str, port: int, timeout: float = 1.0) -> bool:
        """
        立即测试单个 ip:port 是否可以 TCP 连接。
        - 返回 True（可连通）或 False（不可连通）
        - 同时把结果写入 result_box（通过主线程调度）
        """
        addr = (ip, int(port))
        status = False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(addr)
            status = True
            sock.close()
        except Exception:
            status = False

        # 输出结果（在 GUI 中显示）
        self._append_text(f"{ip}:{port} {'✅ 开放' if status else '❌ 关闭/不可达'}\n")
        return status

    # -------------------------
    # 并发单端口任务（内部使用）
    # -------------------------
    def _scan_single_port(self, ip: str, port: int, timeout: float) -> str:
        """
        线程池中运行的单个端口检测任务，返回一行结果字符串。
        任务必须尽量短小（快速返回），并在开始前检查 stop_flag。
        """
        if self._stop_flag:
            return ""  # 为空表示不输出

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((ip, port))
            sock.close()
            result = f"{ip}:{port} ✅ 开放\n"
            # 记录到本地开放端口列表（线程安全地追加）
            self._open_ports.append(port)
        except Exception:
            result = f"{ip}:{port} ❌ 关闭/不可达\n"

        # 更新进度计数（最好在主线程更新显示，这里在子线程更新计数）
        self._done += 1
        return result

    # -------------------------
    # 并发扫描（范围或列表）
    # -------------------------
    def start_range_scan(self, ip: str, start_port: int, end_port: int, timeout: float = 0.8, max_workers: int = 200):
        """
        并发扫描端口范围 [start_port, end_port]（含两端）。
        结果实时写入 result_box。单次扫描在后台线程中运行（不会阻塞主线程）。
        """
        # 参数校验（基本）
        try:
            start_port = int(start_port); end_port = int(end_port)
        except Exception:
            messagebox.showwarning("输入错误", "起始端口和结束端口必须为整数")
            return
        if start_port < 1 or end_port > 65535 or start_port > end_port:
            messagebox.showwarning("输入错误", "端口范围不合法（1-65535 且 起始<=结束）")
            return

        ports = list(range(start_port, end_port + 1))
        self.start_list_scan(ip, ports, timeout=timeout, max_workers=max_workers)

    def start_list_scan(self, ip: str, ports: Iterable[int], timeout: float = 0.8, max_workers: int = 200):
        """
        并发扫描指定的端口列表。
        - ip: 目标 IP（字符串）
        - ports: 可迭代的端口集合（如 list、range 等）
        - timeout: 单端口连接超时（秒）
        - max_workers: 最大并发数（线程池大小）
        """
        # 防止重复启动
        if self._scan_thread and self._scan_thread.is_alive():
            messagebox.showinfo("提示", "已有扫描任务在运行，请先停止后再启动新的扫描。")
            return

        # 将 ports 转为列表并进行基本校验
        try:
            ports_list = [int(p) for p in ports]
        except Exception:
            messagebox.showwarning("输入错误", "端口列表包含非法值")
            return
        if not ports_list:
            messagebox.showwarning("输入错误", "端口列表为空")
            return
        for p in ports_list:
            if p < 1 or p > 65535:
                messagebox.showwarning("输入错误", f"端口 {p} 不在合法范围 1-65535")
                return

        # 重置状态
        self._stop_flag = False
        self._open_ports = []
        self._total = len(ports_list)
        self._done = 0

        # 清空 result_box 并输出起始信息（主线程调度）
        self._append_text(f"开始并发端口扫描：目标 {ip}，共 {self._total} 个端口\n")

        # 后台线程用于管理线程池与结果收集，确保 GUI 不阻塞
        def manager():
            # 根据任务数自适应限制并发数
            actual_workers = max(1, min(max_workers, self._total))
            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers)

            # 提交任务
            futures = {self._executor.submit(self._scan_single_port, ip, port, timeout): port for port in ports_list}

            try:
                # as_completed 会在每个 future 完成时迭代返回
                for fut in concurrent.futures.as_completed(futures):
                    if self._stop_flag:
                        # 如果外部发出停止信号，尽量取消未开始的 future（cancel 返回 True 表示取消成功）
                        # 线程池中的任务可能已在运行, cancel 只能取消未开始的任务
                        break

                    try:
                        line = fut.result()
                    except Exception as e:
                        line = f"{ip}:{futures.get(fut)} 错误: {e}\n"

                    if line:
                        # 把结果写回 GUI（通过 _append_text 安全调度）
                        self._append_text(line)

                    # 可选：显示进度（例如：done/total）
                    self._append_text(f"进度: {self._done}/{self._total}\n")

                # 如果 stop_flag 已设，尝试取消尚未开始的任务
                if self._stop_flag:
                    for f in futures:
                        f.cancel()

            finally:
                # 关闭线程池
                if self._executor:
                    self._executor.shutdown(wait=False)
                    self._executor = None

                # 最终输出总结信息（开放端口列表）
                if not self._stop_flag:
                    self._append_text("\n端口扫描完成。\n")
                else:
                    self._append_text("\n端口扫描已停止。\n")

                if self._open_ports:
                    self._append_text(f"开放端口: {sorted(self._open_ports)}\n")
                else:
                    self._append_text("未发现开放端口。\n")

        # 启动后台管理线程
        self._scan_thread = threading.Thread(target=manager, daemon=True)
        self._scan_thread.start()

    # -------------------------
    # 停止扫描
    # -------------------------
    def stop_scan(self):
        """
        请求停止正在进行的扫描：设置停止标志并尝试关闭线程池。
        - 已提交并正在运行的 socket.connect 调用无法被立即中断（但后续任务会被取消）
        - stop_scan 尽快返回，实际终止需要等待正在运行的任务完成或超时
        """
        if not (self._scan_thread and self._scan_thread.is_alive()):
            messagebox.showinfo("提示", "当前没有正在运行的扫描任务。")
            return

        self._append_text("\n正在停止扫描，请稍候...\n")
        self._stop_flag = True

        # 尝试立即关闭线程池（不等待正在运行任务）
        if self._executor:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass

    # -------------------------
    # 可选：返回当前扫描状态（供外部查询）
    # -------------------------
    def is_scanning(self) -> bool:
        return bool(self._scan_thread and self._scan_thread.is_alive())
