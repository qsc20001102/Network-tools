from tkinter import messagebox

from core.Function.tracert_fun import TracertFun
from core.ui.components import Console, Page, action_bar, button, field


class TracertTab(Page):
    def __init__(self, parent):
        super().__init__(parent, "路由追踪", "查看从本机到目标地址的网络跳点和响应时间。")
        self.body.rowconfigure(1, weight=1)

        target = self.section("追踪参数", 0, columns=4)
        self.target = field(target, "目标 IP / 域名", 1, 0, "8.8.8.8", 28)
        self.max_hops = field(target, "最大跳数", 1, 1, "20", 12)
        self.timeout_ms = field(target, "单跳超时（ms）", 1, 2, "800", 14)
        actions = action_bar(target, 2, 4)
        self.start_btn = button(actions, "↗ 开始追踪", self.start_trace, "Primary.TButton")
        self.stop_btn = button(actions, "■ 停止", self.stop_trace, "Danger.TButton")

        output = self.section("输出控制台", 1, columns=1)
        output.rowconfigure(1, weight=1)
        output.columnconfigure(0, weight=1)
        self.console = Console(output, height=22)
        self.console.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))

        self.tracert_fun = TracertFun(self.write, self.on_task_done)

    def write(self, text, tag=None):
        self.console.write(text, tag)

    def start_trace(self):
        try:
            self.console.clear()
            self.tracert_fun.start_tracert(
                self.target["var"].get(),
                int(self.max_hops["var"].get()),
                int(self.timeout_ms["var"].get()),
            )
            self.start_btn.configure(state="disabled")
        except Exception as exc:
            messagebox.showwarning("无法开始路由追踪", str(exc))

    def stop_trace(self):
        try:
            self.tracert_fun.stop_tracert()
        except Exception as exc:
            messagebox.showinfo("提示", str(exc))

    def on_task_done(self):
        self.after(0, lambda: self.start_btn.configure(state="normal"))
