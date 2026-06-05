import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.Function.ip_conflict_fun import ALL_ADAPTERS, MODE_BOTH, MODE_LOCAL, MODE_SUBNET, IpConflictDetector
from core.ui.components import Console, Page, action_bar, button, combo, field


class IpConflictTab(Page):
    def __init__(self, parent):
        super().__init__(parent, "IP 冲突", "检测本机 IP 是否被占用，并安全扫描网段内 IP/MAC 异常。")
        self.body.rowconfigure(3, weight=1)

        status = self.section("实时状态", 0, columns=6)
        self.state = field(status, "状态", 1, 0, "等待", 10)
        self.adapter_total = field(status, "网卡数", 1, 1, "0", 8)
        self.current = field(status, "当前对象", 1, 2, "-", 18)
        self.max_risk = field(status, "最高风险", 1, 3, "正常", 10)
        self.progress = field(status, "进度", 1, 4, "0/0", 10)
        self.elapsed = field(status, "耗时", 1, 5, "0.0s", 10)
        for item in (self.state, self.adapter_total, self.current, self.max_risk, self.progress, self.elapsed):
            item["entry"].configure(state="disabled")

        params = self.section("检测参数", 1, columns=6)
        self.adapter = combo(params, "检测网卡", 1, 0, [ALL_ADAPTERS], ALL_ADAPTERS, 22)
        self.mode = combo(params, "检测模式", 1, 1, [MODE_BOTH, MODE_LOCAL, MODE_SUBNET], MODE_BOTH, 14)
        self.scan_range = field(params, "扫描范围", 1, 2, "", 30, colspan=2)
        self.workers = field(params, "并发数", 1, 4, "64", 10)
        self.timeout = field(params, "超时 ms", 1, 5, "500", 10)
        self.max_hosts = field(params, "最大地址数", 2, 0, "254", 10)
        actions = action_bar(params, 3, 6)
        self.start_btn = button(actions, "开始检测", self.start_detection, "Primary.TButton")
        self.stop_btn = button(actions, "停止", self.stop_detection, "Danger.TButton")
        self.refresh_btn = button(actions, "刷新网卡", self.load_adapters, "Secondary.TButton")
        self.auto_range_btn = button(actions, "自动范围", self.fill_default_range, "Secondary.TButton")
        self.copy_btn = button(actions, "复制摘要", self.copy_summary, "Secondary.TButton")
        self.export_btn = button(actions, "导出 CSV", self.export_results, "Secondary.TButton")

        results = self.section("检测结果", 2, columns=1)
        results.rowconfigure(1, weight=1)
        results.columnconfigure(0, weight=1)
        self.results_tree = ttk.Treeview(
            results,
            columns=("adapter", "ip", "mac", "conflict", "type", "level", "verdict"),
            show="headings",
            height=9,
        )
        headings = {
            "adapter": "网卡",
            "ip": "IP",
            "mac": "本机/观察 MAC",
            "conflict": "冲突 MAC",
            "type": "证据类型",
            "level": "风险",
            "verdict": "判断",
        }
        widths = {
            "adapter": 130,
            "ip": 150,
            "mac": 150,
            "conflict": 180,
            "type": 110,
            "level": 90,
            "verdict": 420,
        }
        for column, title in headings.items():
            self.results_tree.heading(column, text=title)
            self.results_tree.column(column, width=widths[column], anchor="w")
        self.results_tree.tag_configure("正常", foreground="#15803d")
        self.results_tree.tag_configure("可疑", foreground="#b7791f")
        self.results_tree.tag_configure("冲突风险", foreground="#dc2626")
        self.results_tree.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        result_scroll = ttk.Scrollbar(results, orient="vertical", command=self.results_tree.yview)
        result_scroll.grid(row=1, column=1, sticky="ns", pady=(0, 18))
        self.results_tree.configure(yscrollcommand=result_scroll.set)

        output = self.section("诊断控制台", 3, columns=1)
        output.rowconfigure(1, weight=1)
        output.columnconfigure(0, weight=1)
        self.console = Console(output, height=12)
        self.console.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))

        self.detector = IpConflictDetector(self.write, self.on_task_done, self.update_status, self.add_result)
        self.after(350, self.load_adapters)

    def write(self, text, tag=None):
        self.console.write(text, tag)

    def clear(self):
        self.console.clear()
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        self.update_status(
            {
                "state": "等待",
                "total_adapters": 0,
                "current": "-",
                "max_risk": "正常",
                "total_targets": 0,
                "completed": 0,
                "elapsed": 0,
            }
        )

    def load_adapters(self):
        def worker():
            try:
                values = self.detector.get_adapter_choices()
                default_range = self.detector.default_scan_range(values[0] if len(values) == 1 else ALL_ADAPTERS)
            except Exception as exc:
                values = [ALL_ADAPTERS]
                default_range = ""
                self.write(f"读取检测网卡失败: {exc}\n", "warning")
            self.after(0, lambda: self.apply_adapters(values, default_range))

        threading.Thread(target=worker, daemon=True).start()

    def apply_adapters(self, values, default_range):
        values = values or [ALL_ADAPTERS]
        values = list(dict.fromkeys(values))
        self.adapter["combobox"]["values"] = values
        if self.adapter["var"].get() not in values:
            self.adapter["var"].set(values[0])
        if not self.scan_range["var"].get() and default_range:
            self.scan_range["var"].set(default_range)

    def fill_default_range(self):
        try:
            value = self.detector.default_scan_range(self.adapter["var"].get())
            if not value:
                messagebox.showinfo("提示", "未能根据当前网卡生成扫描范围")
                return
            self.scan_range["var"].set(value)
            self.write(f"已生成安全扫描范围: {value}\n", "success")
        except Exception as exc:
            messagebox.showwarning("生成失败", str(exc))

    def start_detection(self):
        try:
            self.clear()
            self.start_btn.configure(state="disabled")
            self.detector.start_detection(self.adapter["var"].get(), self.options())
        except Exception as exc:
            self.start_btn.configure(state="normal")
            messagebox.showwarning("无法开始 IP 冲突检测", str(exc))

    def stop_detection(self):
        try:
            self.detector.stop_detection()
        except Exception as exc:
            messagebox.showinfo("提示", str(exc))

    def options(self):
        return {
            "mode": self.mode["var"].get(),
            "scan_range": self.scan_range["var"].get(),
            "workers": self.workers["var"].get(),
            "timeout_ms": self.timeout["var"].get(),
            "max_hosts": self.max_hosts["var"].get(),
        }

    def export_results(self):
        path = filedialog.asksaveasfilename(
            title="导出 IP 冲突检测结果",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
        )
        if not path:
            return
        try:
            self.detector.export_results(path)
            self.write(f"已导出结果: {path}\n", "success")
        except Exception as exc:
            messagebox.showwarning("导出失败", str(exc))

    def copy_summary(self):
        text = self.detector.copy_summary()
        if not text:
            messagebox.showinfo("提示", "还没有可复制的诊断摘要")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.write("已复制诊断摘要到剪贴板\n", "success")

    def update_status(self, stats):
        def apply():
            total = stats.get("total_targets", 0)
            done = stats.get("completed", 0)
            values = [
                (self.state, stats.get("state", "等待")),
                (self.adapter_total, str(stats.get("total_adapters", 0))),
                (self.current, stats.get("current") or "-"),
                (self.max_risk, stats.get("max_risk", "正常")),
                (self.progress, f"{done}/{total}" if total else str(done)),
                (self.elapsed, f"{stats.get('elapsed', 0):.1f}s"),
            ]
            for item, value in values:
                item["entry"].configure(state="normal")
                item["var"].set(value)
                item["entry"].configure(state="disabled")

        self.after(0, apply)

    def add_result(self, row):
        def apply():
            self.results_tree.insert(
                "",
                "end",
                values=(
                    row.get("adapter", ""),
                    row.get("ip", ""),
                    row.get("mac", ""),
                    row.get("conflict_macs", ""),
                    row.get("evidence_type", ""),
                    row.get("risk_level", ""),
                    row.get("verdict", ""),
                ),
                tags=(row.get("risk_level", ""),),
            )

        self.after(0, apply)

    def on_task_done(self):
        self.after(0, lambda: self.start_btn.configure(state="normal"))
