import subprocess
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox


class TracertFun:
    def __init__(self, result_box: scrolledtext.ScrolledText):
        self.result_box = result_box
        self.process = None
        self.stop_flag = False

    def _append_text(self, text: str):
        """线程安全地输出到文本框"""
        self.result_box.after(0, lambda: (
            self.result_box.insert(tk.END, text),
            self.result_box.see(tk.END)
        ))

    def start_tracert(self, target: str):
        """开始追踪"""
        if self.process:
            messagebox.showwarning("警告", "⚠️ 正在运行，请先停止再启动。")
            return

        if not target.strip():
            messagebox.showwarning("提示", "请输入目标地址！")
            return

        cmd = f'tracert -d -w 500 -h 20 {target}'
        self.stop_flag = False

        self._append_text(f"\n=== 开始追踪 {target} ===\n\n")

        thread = threading.Thread(target=self._run_tracert, args=(cmd,))
        thread.daemon = True
        thread.start()

    def _run_tracert(self, cmd: str):
        """执行 tracert 命令"""
        try:
            self.process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW  # 隐藏控制台窗口
            )

            for line in self.process.stdout:
                if self.stop_flag:
                    break
                self._append_text(line)

        except Exception as e:
            self._append_text(f"\n❌ 错误: {e}\n")

        finally:
            # 安全关闭进程
            if self.process:
                try:
                    self.process.terminate()
                except Exception:
                    pass
                self.process = None

            if self.stop_flag:
                self._append_text("\n=== 已停止追踪 ===\n")
            else:
                self._append_text("\n--- 追踪结束 ---\n")

    def stop_tracert(self):
        """停止追踪"""
        if self.process:
            self.stop_flag = True
            try:
                self.process.terminate()
            except Exception:
                pass
            self.process = None
            self._append_text("\n=== 已手动停止追踪 ===\n")
        else:
            messagebox.showinfo("提示", "当前没有正在运行的追踪任务。")
