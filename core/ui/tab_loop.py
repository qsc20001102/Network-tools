import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.Function.loop_fun import ALL_ADAPTERS, LoopDetector
from core.ui.components import Page, action_bar, button, combo, field


class LoopTab(Page):
    def __init__(self, parent, console):
        super().__init__(parent, "环网检测", "基于本机证据判断疑似二层环路、广播风暴和网关抖动风险。")
        self.console = console
        self.body.rowconfigure(2, weight=1)

        status = self.section("实时状态", 0, columns=6)
        self.state = field(status, "状态", 1, 0, "等待", 10)
        self.adapter_total = field(status, "网卡数", 1, 1, "0", 8)
        self.current_adapter = field(status, "当前网卡", 1, 2, "-", 24)
        self.risk_level = field(status, "风险等级", 1, 3, "正常", 10)
        self.max_score = field(status, "最高分", 1, 4, "0", 8)
        self.elapsed = field(status, "耗时", 1, 5, "0.0s", 10)
        for item in (self.state, self.adapter_total, self.current_adapter, self.risk_level, self.max_score, self.elapsed):
            item["entry"].configure(state="disabled")

        params = self.section("检测参数", 1, columns=5)
        self.adapter = combo(params, "检测网卡", 1, 0, [ALL_ADAPTERS], ALL_ADAPTERS, 34, colspan=2)
        self.duration = field(params, "检测时长 s", 1, 2, "15", 10)
        self.interval = field(params, "采样间隔 s", 1, 3, "1", 10)
        self.ping_timeout = field(params, "网关 Ping 超时 ms", 1, 4, "800", 12)
        actions = action_bar(params, 2, 5)
        self.start_btn = button(actions, "开始检测", self.start_detection, "Primary.TButton")
        self.stop_btn = button(actions, "停止", self.stop_detection, "Danger.TButton")
        self.refresh_btn = button(actions, "刷新网卡", self.load_adapters, "Secondary.TButton")
        self.copy_btn = button(actions, "复制摘要", self.copy_summary, "Secondary.TButton")
        self.export_btn = button(actions, "导出 CSV", self.export_results, "Secondary.TButton")

        results = self.section("检测结果", 2, columns=1)
        results.rowconfigure(1, weight=1)
        results.columnconfigure(0, weight=1)
        self.results_tree = ttk.Treeview(
            results,
            columns=("adapter", "ipv4", "gateway", "non_unicast", "ratio", "loss", "jitter", "arp", "score", "level", "verdict"),
            show="headings",
            height=9,
        )
        headings = {
            "adapter": "网卡",
            "ipv4": "IPv4",
            "gateway": "网关",
            "non_unicast": "非单播/s",
            "ratio": "非单播占比",
            "loss": "网关丢包",
            "jitter": "网关抖动",
            "arp": "ARP 异常",
            "score": "分数",
            "level": "等级",
            "verdict": "判断",
        }
        widths = {
            "adapter": 110,
            "ipv4": 96,
            "gateway": 96,
            "non_unicast": 72,
            "ratio": 78,
            "loss": 70,
            "jitter": 72,
            "arp": 58,
            "score": 50,
            "level": 62,
            "verdict": 150,
        }
        for column, title in headings.items():
            self.results_tree.heading(column, text=title)
            self.results_tree.column(column, width=widths[column], anchor="w")
        self.results_tree.tag_configure("正常", foreground="#15803d")
        self.results_tree.tag_configure("可疑", foreground="#b7791f")
        self.results_tree.tag_configure("高风险", foreground="#dc2626")
        self.results_tree.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        result_scroll = ttk.Scrollbar(results, orient="vertical", command=self.results_tree.yview)
        result_scroll.grid(row=1, column=1, sticky="ns", pady=(0, 18))
        x_scroll = ttk.Scrollbar(results, orient="horizontal", command=self.results_tree.xview)
        x_scroll.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))
        self.results_tree.configure(yscrollcommand=result_scroll.set, xscrollcommand=x_scroll.set)

        self.detector = LoopDetector(self.write, self.on_task_done, self.update_status, self.add_result)
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
                "current_adapter": "-",
                "risk_level": "正常",
                "max_score": 0,
                "elapsed": 0,
            }
        )

    def load_adapters(self):
        def worker():
            try:
                values = self.detector.get_adapter_choices()
            except Exception as exc:
                values = [ALL_ADAPTERS]
                self.write(f"读取检测网卡失败: {exc}\n", "warning")
            self.after(0, lambda: self.apply_adapters(values))

        threading.Thread(target=worker, daemon=True).start()

    def apply_adapters(self, values):
        values = values or [ALL_ADAPTERS]
        values = list(dict.fromkeys(values))
        self.adapter["combobox"]["values"] = values
        if self.adapter["var"].get() not in values:
            self.adapter["var"].set(values[0])

    def start_detection(self):
        try:
            self.clear()
            self.start_btn.configure(state="disabled")
            self.detector.start_detection(
                self.adapter["var"].get(),
                {
                    "duration_sec": self.duration["var"].get(),
                    "interval_sec": self.interval["var"].get(),
                    "ping_timeout_ms": self.ping_timeout["var"].get(),
                },
            )
        except Exception as exc:
            self.start_btn.configure(state="normal")
            messagebox.showwarning("无法开始环网检测", str(exc))

    def stop_detection(self):
        try:
            self.detector.stop_detection()
        except Exception as exc:
            messagebox.showinfo("提示", str(exc))

    def export_results(self):
        path = filedialog.asksaveasfilename(
            title="导出环网检测结果",
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
            current = stats.get("current_adapter") or "-"
            values = [
                (self.state, stats.get("state", "等待")),
                (self.adapter_total, str(stats.get("total_adapters", 0))),
                (self.current_adapter, current),
                (self.risk_level, stats.get("risk_level", "正常")),
                (self.max_score, str(stats.get("max_score", 0))),
                (self.elapsed, f"{stats.get('elapsed', 0):.1f}s"),
            ]
            for item, value in values:
                item["entry"].configure(state="normal")
                item["var"].set(value)
                item["entry"].configure(state="disabled")

        self.after(0, apply)

    def add_result(self, row):
        def apply():
            arp_score = int(row.get("gateway_mac_changes", 0)) + int(row.get("ip_mac_changes", 0))
            self.results_tree.insert(
                "",
                "end",
                values=(
                    row.get("adapter", ""),
                    row.get("ipv4", ""),
                    row.get("gateway", ""),
                    f"{row.get('non_unicast_pps', 0):.1f}",
                    f"{row.get('non_unicast_ratio', 0):.1f}%",
                    f"{row.get('gateway_ping_loss', 0):.1f}%",
                    f"{row.get('gateway_jitter_ms', 0):.1f} ms",
                    str(arp_score),
                    row.get("risk_score", 0),
                    row.get("risk_level", ""),
                    row.get("verdict", ""),
                ),
                tags=(row.get("risk_level", ""),),
            )

        self.after(0, apply)

    def on_task_done(self):
        self.after(0, lambda: self.start_btn.configure(state="normal"))
