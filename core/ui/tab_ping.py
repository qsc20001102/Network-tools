import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.Function.network_fun import NetworkManager
from core.Function.ping_fun import PingFun
from core.ui.components import Page, action_bar, button, combo, field


DEFAULT_SOURCE = "默认路由"
IP_PATTERN = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")


class PingTab(Page):
    def __init__(self, parent, console):
        super().__init__(parent, "Ping 探测", "单点 Ping、批量探活、参数化诊断与结果导出。")
        self.console = console
        self.body.rowconfigure(1, weight=1)

        status = self.section("实时状态", 0, columns=7)
        self.state = field(status, "状态", 1, 0, "等待", 12)
        self.sent = field(status, "发送", 1, 1, "0", 8)
        self.received = field(status, "接收", 1, 2, "0", 8)
        self.loss = field(status, "丢包率", 1, 3, "0.0%", 10)
        self.avg = field(status, "平均延迟", 1, 4, "0.0 ms", 12)
        self.jitter = field(status, "抖动", 1, 5, "0.0 ms", 12)
        self.quality = field(status, "质量", 1, 6, "等待", 10)
        for item in (self.state, self.sent, self.received, self.loss, self.avg, self.jitter, self.quality):
            item["entry"].configure(state="disabled")

        modes = self.section("探测模式", 1, columns=1)
        modes.rowconfigure(1, weight=1)
        modes.columnconfigure(0, weight=1)
        self.tabs = ttk.Notebook(modes)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self.single_tab = ttk.Frame(self.tabs, style="Panel.TFrame")
        self.batch_tab = ttk.Frame(self.tabs, style="Panel.TFrame")
        self.tabs.add(self.single_tab, text="单点探测")
        self.tabs.add(self.batch_tab, text="批量探活")
        self.build_single_tab()
        self.build_batch_tab()

        self.ping_fun = PingFun(self.write, self.on_task_done, self.update_status)
        self.source_loader = NetworkManager(lambda _text, _tag=None: None)
        self.after(350, self.load_source_ips)

    def build_single_tab(self):
        for col in range(6):
            self.single_tab.columnconfigure(col, weight=1)

        self.local_ip = combo(self.single_tab, "本地源 IP", 0, 0, [], "", 28)
        self.target = field(self.single_tab, "目标 IP / 域名", 0, 1, "127.0.0.1", 36, colspan=2)
        self.single_mode = combo(self.single_tab, "模式", 0, 3, ["持续", "指定次数"], "持续", 12)
        self.count = field(self.single_tab, "次数", 0, 4, "4", 8)
        self.interval = field(self.single_tab, "间隔 ms", 0, 5, "1000", 10)
        self.timeout = field(self.single_tab, "超时 ms", 1, 0, "1200", 10)

        self.size = field(self.single_tab, "包大小 bytes", 1, 1, "32", 12)
        self.ttl = field(self.single_tab, "TTL（0=默认）", 1, 2, "0", 12)
        self.df_var = tk.BooleanVar(value=False)
        df_frame = ttk.Frame(self.single_tab, style="Panel.TFrame")
        df_frame.grid(row=1, column=3, sticky="ew", padx=18, pady=(22, 14))
        ttk.Checkbutton(df_frame, text="禁止分片", variable=self.df_var).pack(anchor="w")

        actions = action_bar(self.single_tab, 2, 6)
        self.start_btn = button(actions, "开始 Ping", self.start_ping, "Primary.TButton")
        self.stop_btn = button(actions, "停止", self.stop_ping, "Danger.TButton")
        self.reload_sources_btn = button(actions, "刷新源 IP", self.load_source_ips, "Secondary.TButton")

    def build_batch_tab(self):
        for col in range(6):
            self.batch_tab.columnconfigure(col, weight=1)

        self.batch_local_ip = combo(self.batch_tab, "本地源 IP", 0, 0, [], "", 28)
        self.targets = field(self.batch_tab, "目标范围 / 列表", 0, 1, "192.168.1.0/24", 52, colspan=3)
        self.batch_timeout = field(self.batch_tab, "超时 ms", 0, 4, "1200", 10)
        self.batch_size = field(self.batch_tab, "包大小 bytes", 0, 5, "32", 12)
        self.workers = field(self.batch_tab, "并发数", 1, 0, "64", 10)

        self.batch_ttl = field(self.batch_tab, "TTL（0=默认）", 1, 1, "0", 12)
        self.batch_df_var = tk.BooleanVar(value=False)
        df_frame = ttk.Frame(self.batch_tab, style="Panel.TFrame")
        df_frame.grid(row=1, column=2, sticky="ew", padx=18, pady=(22, 14))
        ttk.Checkbutton(df_frame, text="禁止分片", variable=self.batch_df_var).pack(anchor="w")

        actions = action_bar(self.batch_tab, 2, 6)
        self.batch_start_btn = button(actions, "批量 Ping", self.start_batch_ping, "Primary.TButton")
        self.batch_stop_btn = button(actions, "停止批量", self.stop_batch_ping, "Danger.TButton")
        self.import_btn = button(actions, "导入目标", self.import_targets, "Secondary.TButton")
        self.export_btn = button(actions, "导出 CSV", self.export_results, "Secondary.TButton")
        self.reload_batch_sources_btn = button(actions, "刷新源 IP", self.load_source_ips, "Secondary.TButton")

    def write(self, text, tag=None):
        self.console.write(text, tag)

    def clear(self):
        self.console.clear()
        self.update_status({"state": "等待", "sent": 0, "received": 0, "lost": 0, "loss_rate": 0, "avg_rtt": 0, "jitter": 0, "quality": "等待"})

    def start_ping(self):
        try:
            self.clear()
            self.ping_fun.start_ping(self.target["var"].get(), self.selected_source_ip(self.local_ip), self.single_options())
            self._set_start_buttons("disabled")
        except Exception as exc:
            messagebox.showwarning("无法开始 Ping", str(exc))

    def stop_ping(self):
        self.ping_fun.stop_ping()

    def start_batch_ping(self):
        try:
            self.clear()
            self.ping_fun.start_batch_ping(self.targets["var"].get(), self.selected_source_ip(self.batch_local_ip), self.batch_options())
            self._set_start_buttons("disabled")
        except Exception as exc:
            messagebox.showwarning("无法开始批量 Ping", str(exc))

    def stop_batch_ping(self):
        self.ping_fun.stop_batch_ping()

    def single_options(self):
        return {
            "mode": self.single_mode["var"].get(),
            "count": self.count["var"].get(),
            "interval_ms": self.interval["var"].get(),
            "timeout_ms": self.timeout["var"].get(),
            "size": self.size["var"].get(),
            "ttl": self.ttl["var"].get(),
            "dont_fragment": self.df_var.get(),
        }

    def batch_options(self):
        return {
            "mode": "指定次数",
            "count": 1,
            "interval_ms": 1000,
            "timeout_ms": self.batch_timeout["var"].get(),
            "size": self.batch_size["var"].get(),
            "ttl": self.batch_ttl["var"].get(),
            "dont_fragment": self.batch_df_var.get(),
            "workers": self.workers["var"].get(),
        }

    def update_status(self, stats):
        def apply():
            values = [
                (self.state, stats.get("state", "等待")),
                (self.sent, str(stats.get("sent", 0))),
                (self.received, str(stats.get("received", 0))),
                (self.loss, f"{stats.get('loss_rate', 0):.1f}%"),
                (self.avg, f"{stats.get('avg_rtt', 0):.1f} ms"),
                (self.jitter, f"{stats.get('jitter', 0):.1f} ms"),
                (self.quality, stats.get("quality", "等待")),
            ]
            for item, value in values:
                item["entry"].configure(state="normal")
                item["var"].set(value)
                item["entry"].configure(state="disabled")

        self.after(0, apply)

    def load_source_ips(self):
        def worker():
            values = [DEFAULT_SOURCE]
            try:
                for adapter in self.source_loader.get_network_info():
                    ip = adapter.get("ipv4", "")
                    if ip:
                        name = adapter.get("name", "").strip()
                        values.append(f"{name} - {ip}" if name else ip)
            except Exception as exc:
                self.write(f"读取本地源 IP 失败: {exc}\n", "warning")
            self.after(0, lambda: self.apply_source_ips(values))

        threading.Thread(target=worker, daemon=True).start()

    def apply_source_ips(self, values):
        values = list(dict.fromkeys(values))
        self.local_ip["combobox"]["values"] = values
        self.batch_local_ip["combobox"]["values"] = values
        if self.local_ip["var"].get() not in values:
            self.local_ip["var"].set(values[0])
        if self.batch_local_ip["var"].get() not in values:
            self.batch_local_ip["var"].set(values[0])

    def selected_source_ip(self, item):
        value = item["var"].get().strip()
        if not value or value == DEFAULT_SOURCE:
            return ""
        match = IP_PATTERN.search(value)
        return match.group(0) if match else value

    def import_targets(self):
        path = filedialog.askopenfilename(
            title="导入 Ping 目标",
            filetypes=[("文本文件", "*.txt *.csv"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as file:
                items = []
                for line in file:
                    items.extend(part.strip() for part in line.replace("，", ",").split(",") if part.strip())
            self.targets["var"].set(",".join(items))
            self.write(f"已导入 {len(items)} 个目标/表达式\n", "success")
        except Exception as exc:
            messagebox.showwarning("导入失败", str(exc))

    def export_results(self):
        path = filedialog.asksaveasfilename(
            title="导出批量 Ping 结果",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
        )
        if not path:
            return
        try:
            self.ping_fun.export_batch_results(path)
            self.write(f"已导出结果: {path}\n", "success")
        except Exception as exc:
            messagebox.showwarning("导出失败", str(exc))

    def on_task_done(self):
        self.after(0, lambda: self._set_start_buttons("normal"))

    def _set_start_buttons(self, state):
        self.start_btn.configure(state=state)
        self.batch_start_btn.configure(state=state)
