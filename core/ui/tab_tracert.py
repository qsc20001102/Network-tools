import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.Function.tracert_fun import TracertFun
from core.ui.components import Page, action_bar, button, combo, field


class TracertTab(Page):
    def __init__(self, parent, console):
        super().__init__(parent, "路由追踪", "结构化查看跳点、延迟、超时、波动和诊断摘要。")
        self.console = console
        self.body.rowconfigure(2, weight=1)

        status = self.section("实时状态", 0, columns=7)
        self.state = field(status, "状态", 1, 0, "等待", 10)
        self.run_state = field(status, "轮次", 1, 1, "0/0", 8)
        self.current_hop = field(status, "当前跳", 1, 2, "0", 8)
        self.timeout_hops = field(status, "超时跳", 1, 3, "0", 8)
        self.high_hops = field(status, "高延迟", 1, 4, "0", 8)
        self.max_latency = field(status, "最大延迟", 1, 5, "0.0 ms", 12)
        self.elapsed = field(status, "耗时", 1, 6, "0.0s", 10)
        for item in (
            self.state,
            self.run_state,
            self.current_hop,
            self.timeout_hops,
            self.high_hops,
            self.max_latency,
            self.elapsed,
        ):
            item["entry"].configure(state="disabled")

        params = self.section("追踪参数", 1, columns=7)
        self.target = field(params, "目标 IP / 域名", 1, 0, "8.8.8.8", 36, colspan=2)
        self.address_family = combo(params, "地址族", 1, 2, ["自动", "IPv4", "IPv6"], "自动", 10)
        self.mode = combo(params, "模式", 1, 3, ["单次", "指定次数", "持续"], "单次", 12)
        self.repeat_count = field(params, "次数", 1, 4, "3", 8)
        self.interval_ms = field(params, "间隔 ms", 1, 5, "1000", 10)
        self.max_hops = field(params, "最大跳数", 1, 6, "20", 10)
        self.timeout_ms = field(params, "单跳超时 ms", 2, 0, "800", 12)
        self.high_latency_ms = field(params, "高延迟阈值 ms", 2, 1, "100", 12)
        self.resolve_names_var = tk.BooleanVar(value=False)
        self._check(params, "解析主机名", self.resolve_names_var, 2, 2)
        actions = action_bar(params, 3, 7)
        self.start_btn = button(actions, "开始追踪", self.start_trace, "Primary.TButton")
        self.stop_btn = button(actions, "停止", self.stop_trace, "Danger.TButton")
        self.copy_btn = button(actions, "复制摘要", self.copy_summary, "Secondary.TButton")
        self.export_btn = button(actions, "导出 CSV", self.export_results, "Secondary.TButton")

        results = self.section("跳点结果", 2, columns=1)
        results.rowconfigure(1, weight=1)
        results.columnconfigure(0, weight=1)
        self.results_tree = ttk.Treeview(
            results,
            columns=("run", "hop", "probe1", "probe2", "probe3", "avg", "jitter", "ip", "status"),
            show="headings",
            height=9,
        )
        headings = {
            "run": "轮次",
            "hop": "跳数",
            "probe1": "RTT 1",
            "probe2": "RTT 2",
            "probe3": "RTT 3",
            "avg": "平均",
            "jitter": "波动",
            "ip": "IP",
            "status": "判断",
        }
        widths = {
            "run": 60,
            "hop": 60,
            "probe1": 78,
            "probe2": 78,
            "probe3": 78,
            "avg": 88,
            "jitter": 88,
            "ip": 190,
            "status": 190,
        }
        for column, title in headings.items():
            self.results_tree.heading(column, text=title)
            self.results_tree.column(column, width=widths[column], minwidth=widths[column], anchor="w", stretch=False)
        self.results_tree.tag_configure("ok", foreground="#15803d")
        self.results_tree.tag_configure("timeout", foreground="#b7791f")
        self.results_tree.tag_configure("high_latency", foreground="#dc2626")
        self.results_tree.tag_configure("jitter", foreground="#b7791f")
        self.results_tree.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        result_scroll = ttk.Scrollbar(
            results,
            orient="vertical",
            command=self.results_tree.yview,
            style="Modern.Vertical.TScrollbar",
        )
        result_scroll.grid(row=1, column=1, sticky="ns", pady=(0, 18), padx=(0, 18))
        self.results_tree.configure(yscrollcommand=result_scroll.set)

        self.tracert_fun = TracertFun(self.write, self.on_task_done, self.update_status, self.add_result)

    def _check(self, parent, text, variable, row, column):
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.grid(row=row, column=column, sticky="ew", padx=18, pady=(22, 14))
        ttk.Checkbutton(frame, text=text, variable=variable).pack(anchor="w")

    def write(self, text, tag=None):
        self.console.write(text, tag)

    def clear(self):
        self.console.clear()
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        self.update_status(
            {
                "state": "等待",
                "current_run": 0,
                "total_runs": 0,
                "current_hop": 0,
                "timeout_hops": 0,
                "high_latency_hops": 0,
                "max_latency_ms": 0,
                "elapsed": 0,
            }
        )

    def start_trace(self):
        try:
            self.clear()
            self.tracert_fun.start_tracert(
                self.target["var"].get(),
                int(self.max_hops["var"].get()),
                int(self.timeout_ms["var"].get()),
                self.trace_options(),
            )
            self.start_btn.configure(state="disabled")
        except Exception as exc:
            self.start_btn.configure(state="normal")
            messagebox.showwarning("无法开始路由追踪", str(exc))

    def stop_trace(self):
        try:
            self.tracert_fun.stop_tracert()
        except Exception as exc:
            messagebox.showinfo("提示", str(exc))

    def trace_options(self):
        return {
            "address_family": self.address_family["var"].get(),
            "resolve_names": self.resolve_names_var.get(),
            "mode": self.mode["var"].get(),
            "repeat_count": self.repeat_count["var"].get(),
            "interval_ms": self.interval_ms["var"].get(),
            "high_latency_ms": self.high_latency_ms["var"].get(),
        }

    def export_results(self):
        path = filedialog.asksaveasfilename(
            title="导出路由追踪结果",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
        )
        if not path:
            return
        try:
            self.tracert_fun.export_results(path)
            self.write(f"已导出结果: {path}\n", "success")
        except Exception as exc:
            messagebox.showwarning("导出失败", str(exc))

    def copy_summary(self):
        text = self.tracert_fun.copy_summary()
        if not text:
            messagebox.showinfo("提示", "还没有可复制的诊断摘要")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.write("已复制诊断摘要到剪贴板\n", "success")

    def update_status(self, stats):
        def apply():
            total_runs = stats.get("total_runs", 0)
            run_text = f"{stats.get('current_run', 0)}/持续" if total_runs == 0 else f"{stats.get('current_run', 0)}/{total_runs}"
            values = [
                (self.state, stats.get("state", "等待")),
                (self.run_state, run_text),
                (self.current_hop, f"{stats.get('current_hop', 0)}/{stats.get('max_hops', 0)}"),
                (self.timeout_hops, str(stats.get("timeout_hops", 0))),
                (self.high_hops, str(stats.get("high_latency_hops", 0))),
                (self.max_latency, f"{stats.get('max_latency_ms', 0):.1f} ms"),
                (self.elapsed, f"{stats.get('elapsed', 0):.1f}s"),
            ]
            for item, value in values:
                item["entry"].configure(state="normal")
                item["var"].set(value)
                item["entry"].configure(state="disabled")

        self.after(0, apply)

    def add_result(self, row):
        def apply():
            avg = f"{row.get('avg_ms', 0):.1f} ms" if row.get("avg_ms") else "-"
            jitter = f"{row.get('jitter_ms', 0):.1f} ms" if row.get("jitter_ms") else "-"
            self.results_tree.insert(
                "",
                "end",
                values=(
                    row.get("run", ""),
                    row.get("hop", ""),
                    row.get("probe1", ""),
                    row.get("probe2", ""),
                    row.get("probe3", ""),
                    avg,
                    jitter,
                    row.get("ip", ""),
                    row.get("status_text", ""),
                ),
                tags=(row.get("status", ""),),
            )

        self.after(0, apply)

    def on_task_done(self):
        self.after(0, lambda: self.start_btn.configure(state="normal"))
