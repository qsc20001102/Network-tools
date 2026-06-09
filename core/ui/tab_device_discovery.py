import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.Function.device_discovery_fun import ALL_ADAPTERS, DeviceDiscovery
from core.ui.components import Page, action_bar, button, combo, field


class DeviceDiscoveryTab(Page):
    def __init__(self, parent, console):
        super().__init__(parent, "设备发现", "发现局域网在线与 ARP 可见设备，整理 IP、MAC、厂商与来源网卡。")
        self.console = console
        self.body.rowconfigure(2, weight=1)

        status = self.section("实时状态", 0, columns=7)
        self.state = field(status, "状态", 1, 0, "等待", 10)
        self.current = field(status, "当前网卡", 1, 1, "-", 18)
        self.scan_scope = field(status, "扫描范围", 1, 2, "-", 22, colspan=2)
        self.progress = field(status, "进度", 1, 4, "0/0", 10)
        self.found = field(status, "发现设备", 1, 5, "0", 8)
        self.elapsed = field(status, "耗时", 1, 6, "0.0s", 10)
        for item in (self.state, self.current, self.scan_scope, self.progress, self.found, self.elapsed):
            item["entry"].configure(state="disabled")

        params = self.section("发现参数", 1, columns=6)
        self.adapter = combo(params, "检测网卡", 1, 0, [ALL_ADAPTERS], ALL_ADAPTERS, 22)
        self.adapter["combobox"].bind("<<ComboboxSelected>>", lambda _event: self.fill_default_range(silent=True))
        self.scan_range = field(params, "扫描范围", 1, 1, "", 42, colspan=3)
        self.workers = field(params, "并发数", 1, 4, "24", 10)
        self.timeout = field(params, "超时 ms", 1, 5, "500", 10)
        self.max_hosts = field(params, "最大地址数", 2, 0, "254", 10)
        primary_actions = action_bar(params, 3, 6)
        self.start_btn = button(primary_actions, "开始发现", self.start_discovery, "Primary.TButton")
        self.stop_btn = button(primary_actions, "停止", self.stop_discovery, "Danger.TButton")
        self.refresh_btn = button(primary_actions, "刷新网卡", self.load_adapters, "Secondary.TButton")
        self.auto_range_btn = button(primary_actions, "自动范围", self.fill_default_range, "Secondary.TButton")
        self.stop_btn.configure(state="disabled")
        secondary_actions = action_bar(params, 4, 6)
        self.copy_btn = button(secondary_actions, "复制清单", self.copy_inventory, "Secondary.TButton")
        self.export_btn = button(secondary_actions, "导出CSV", self.export_results, "Secondary.TButton")

        results = self.section("发现结果", 2, columns=1)
        results.rowconfigure(1, weight=1)
        results.columnconfigure(0, weight=1)
        self.results_tree = ttk.Treeview(
            results,
            columns=("ip", "mac", "vendor", "adapter", "latency", "method", "note"),
            show="headings",
            height=10,
        )
        headings = {
            "ip": "IP",
            "mac": "MAC",
            "vendor": "厂商",
            "adapter": "来源网卡",
            "latency": "延迟",
            "method": "发现方式",
            "note": "备注",
        }
        widths = {
            "ip": 105,
            "mac": 170,
            "vendor": 270,
            "adapter": 80,
            "latency": 65,
            "method": 80,
            "note": 100,
        }
        for column, title in headings.items():
            self.results_tree.heading(column, text=title)
            self.results_tree.column(column, width=widths[column], minwidth=widths[column], anchor="w", stretch=False)
        self.results_tree.tag_configure("在线", foreground="#15803d")
        self.results_tree.tag_configure("ARP 可见", foreground="#b7791f")
        self.results_tree.tag_configure("本机", foreground="#246bfe")
        self.results_tree.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        result_scroll = ttk.Scrollbar(
            results,
            orient="vertical",
            command=self.results_tree.yview,
            style="Modern.Vertical.TScrollbar",
        )
        result_scroll.grid(row=1, column=1, sticky="ns", pady=(0, 18), padx=(0, 18))
        self.results_tree.configure(yscrollcommand=result_scroll.set)

        self.discovery = DeviceDiscovery(self.write, self.on_task_done, self.update_status, self.add_result)
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
                "current": "-",
                "scan_range": "-",
                "total": 0,
                "scanned": 0,
                "found": 0,
                "elapsed": 0,
            }
        )

    def load_adapters(self):
        def worker():
            try:
                values, default_range, default_adapter = self.discovery.get_adapter_choices_and_default_range()
            except Exception as exc:
                values = [ALL_ADAPTERS]
                default_range = ""
                default_adapter = ""
                self.write(f"读取网卡失败: {exc}\n", "warning")
            self.after(0, lambda: self.apply_adapters(values, default_range, default_adapter))

        threading.Thread(target=worker, daemon=True).start()

    def apply_adapters(self, values, default_range, default_adapter=""):
        values = values or [ALL_ADAPTERS]
        values = list(dict.fromkeys(values))
        self.adapter["combobox"]["values"] = values
        if self.adapter["var"].get() not in values or self.adapter["var"].get() == ALL_ADAPTERS:
            self.adapter["var"].set(default_adapter if default_adapter in values else values[1] if len(values) > 1 else values[0])
        if not self.scan_range["var"].get() and default_range:
            self.scan_range["var"].set(default_range)

    def fill_default_range(self, silent=False):
        try:
            value = self.discovery.default_scan_range(self.adapter["var"].get())
            if not value:
                if not silent:
                    messagebox.showinfo("提示", "未能根据当前网卡生成扫描范围")
                return
            self.scan_range["var"].set(value)
            if not silent:
                self.write(f"已生成安全扫描范围: {value}\n", "success")
        except Exception as exc:
            if not silent:
                messagebox.showwarning("生成失败", str(exc))

    def start_discovery(self):
        try:
            self.clear()
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            self.refresh_btn.configure(state="disabled")
            self.auto_range_btn.configure(state="disabled")
            self.discovery.start_discovery(self.adapter["var"].get(), self.options())
        except Exception as exc:
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self.refresh_btn.configure(state="normal")
            self.auto_range_btn.configure(state="normal")
            messagebox.showwarning("无法开始设备发现", str(exc))

    def stop_discovery(self):
        try:
            self.discovery.stop_discovery()
            self.stop_btn.configure(state="disabled")
        except Exception as exc:
            messagebox.showinfo("提示", str(exc))

    def options(self):
        return {
            "scan_range": self.scan_range["var"].get(),
            "workers": self.workers["var"].get(),
            "timeout_ms": self.timeout["var"].get(),
            "max_hosts": self.max_hosts["var"].get(),
        }

    def export_results(self):
        path = filedialog.asksaveasfilename(
            title="导出设备发现结果",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
        )
        if not path:
            return
        try:
            self.discovery.export_results(path)
            self.write(f"已导出结果: {path}\n", "success")
        except Exception as exc:
            messagebox.showwarning("导出失败", str(exc))

    def copy_inventory(self):
        text = self.discovery.copy_summary()
        if not text:
            messagebox.showinfo("提示", "还没有可复制的设备清单")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.write("已复制设备清单到剪贴板\n", "success")

    def update_status(self, stats):
        def apply():
            total = stats.get("total", 0)
            scanned = stats.get("scanned", 0)
            values = [
                (self.state, stats.get("state", "等待")),
                (self.current, stats.get("current") or "-"),
                (self.scan_scope, stats.get("scan_range") or "-"),
                (self.progress, f"{scanned}/{total}" if total else "0/0"),
                (self.found, str(stats.get("found", 0))),
                (self.elapsed, f"{stats.get('elapsed', 0):.1f}s"),
            ]
            for item, value in values:
                item["entry"].configure(state="normal")
                item["var"].set(value)
                item["entry"].configure(state="disabled")

        self.after(0, apply)

    def add_result(self, row):
        def apply():
            method = row.get("method", "")
            note = row.get("note", "")
            tag = "本机" if "本机" in note else method
            latency = row.get("latency_ms", 0)
            try:
                latency_text = f"{float(latency):.1f} ms" if float(latency) > 0 else ""
            except (TypeError, ValueError):
                latency_text = ""
            self.results_tree.insert(
                "",
                "end",
                values=(
                    row.get("ip", ""),
                    row.get("mac", ""),
                    row.get("vendor", ""),
                    row.get("adapter", ""),
                    latency_text,
                    method,
                    note,
                ),
                tags=(tag,),
            )

        self.after(0, apply)

    def on_task_done(self):
        self.after(
            0,
            lambda: (
                self.start_btn.configure(state="normal"),
                self.stop_btn.configure(state="disabled"),
                self.refresh_btn.configure(state="normal"),
                self.auto_range_btn.configure(state="normal"),
            ),
        )
