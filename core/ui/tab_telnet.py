import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.Function.telnet_fun import PortScanner
from core.ui.components import Page, action_bar, button, combo, field


PORT_PRESETS = {
    "常用端口": "21,22,23,25,53,80,110,139,143,443,445,1433,3306,3389,5432,6379,8080,8443,9200",
    "Web 服务": "80,443,8000-8010,8080,8081,8443,8888,9000",
    "数据库": "1433,1521,3306,5432,6379,9200,27017",
    "远程管理": "22,23,3389,5900,5985,5986",
    "邮件服务": "25,110,143,465,587,993,995",
    "全端口": "1-65535",
}


class TelnetTab(Page):
    def __init__(self, parent, console):
        super().__init__(parent, "端口扫描", "单端口测试、端口扫描、批量主机巡检、服务识别与结果导出。")
        self.console = console
        self.body.rowconfigure(2, weight=1)

        status = self.section("实时状态", 0, columns=7)
        self.state = field(status, "状态", 1, 0, "等待", 10)
        self.total = field(status, "总数", 1, 1, "0", 8)
        self.scanned = field(status, "已扫", 1, 2, "0", 8)
        self.open_count = field(status, "开放", 1, 3, "0", 8)
        self.closed_count = field(status, "关闭", 1, 4, "0", 8)
        self.timeout_count = field(status, "超时", 1, 5, "0", 8)
        self.progress = field(status, "进度 / 耗时", 1, 6, "0.0% / 0.0s", 16)
        for item in (self.state, self.total, self.scanned, self.open_count, self.closed_count, self.timeout_count, self.progress):
            item["entry"].configure(state="disabled")

        modes = self.section("扫描模式", 1, columns=1)
        modes.rowconfigure(1, weight=1)
        modes.columnconfigure(0, weight=1)
        self.tabs = ttk.Notebook(modes)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self.single_tab = ttk.Frame(self.tabs, style="Panel.TFrame")
        self.scan_tab = ttk.Frame(self.tabs, style="Panel.TFrame")
        self.batch_tab = ttk.Frame(self.tabs, style="Panel.TFrame")
        self.tabs.add(self.single_tab, text="单端口测试")
        self.tabs.add(self.scan_tab, text="端口扫描")
        self.tabs.add(self.batch_tab, text="批量主机扫描")
        self.build_single_tab()
        self.build_scan_tab()
        self.build_batch_tab()

        results = self.section("结果列表", 2, columns=1)
        results.rowconfigure(1, weight=1)
        results.columnconfigure(0, weight=1)
        self.results_tree = ttk.Treeview(
            results,
            columns=("host", "resolved_ip", "port", "service", "status", "latency", "banner"),
            show="headings",
            height=8,
        )
        headings = {
            "host": "目标",
            "resolved_ip": "解析 IP",
            "port": "端口",
            "service": "服务",
            "status": "状态",
            "latency": "延迟",
            "banner": "Banner / 错误",
        }
        widths = {
            "host": 185,
            "resolved_ip": 145,
            "port": 70,
            "service": 125,
            "status": 80,
            "latency": 85,
            "banner": 120,
        }
        for column, title in headings.items():
            self.results_tree.heading(column, text=title)
            self.results_tree.column(column, width=widths[column], minwidth=widths[column], anchor="w", stretch=False)
        self.results_tree.tag_configure("open", foreground="#15803d")
        self.results_tree.tag_configure("timeout", foreground="#b7791f")
        self.results_tree.tag_configure("unreachable", foreground="#b7791f")
        self.results_tree.tag_configure("dns_error", foreground="#dc2626")
        self.results_tree.tag_configure("error", foreground="#dc2626")
        self.results_tree.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        result_scroll = ttk.Scrollbar(
            results,
            orient="vertical",
            command=self.results_tree.yview,
            style="Modern.Vertical.TScrollbar",
        )
        result_scroll.grid(row=1, column=1, sticky="ns", pady=(0, 18), padx=(0, 18))
        self.results_tree.configure(yscrollcommand=result_scroll.set)

        self.scanner = PortScanner(self.write, self.on_task_done, self.update_status, self.add_result)

    def build_single_tab(self):
        for col in range(5):
            self.single_tab.columnconfigure(col, weight=1)

        self.single_host = field(self.single_tab, "目标 IP / 域名", 0, 0, "127.0.0.1", 36, colspan=2)
        self.single_port = field(self.single_tab, "目标端口", 0, 2, "443", 12)
        self.single_timeout = field(self.single_tab, "超时 ms", 0, 3, "1000", 10)
        self.single_banner_var = tk.BooleanVar(value=False)
        self._check(self.single_tab, "Banner 探测", self.single_banner_var, 0, 4)
        actions = action_bar(self.single_tab, 1, 5)
        self.single_btn = button(actions, "测试连接", self.test_single, "Primary.TButton")
        self.single_export_btn = button(actions, "导出 CSV", self.export_results, "Secondary.TButton")

    def build_scan_tab(self):
        for col in range(6):
            self.scan_tab.columnconfigure(col, weight=1)

        self.scan_host = field(self.scan_tab, "目标 IP / 域名", 0, 0, "127.0.0.1", 30)
        self.scan_ports = field(self.scan_tab, "端口列表 / 范围", 0, 1, PORT_PRESETS["常用端口"], 58, colspan=3)
        self.scan_preset = combo(self.scan_tab, "预设", 0, 4, list(PORT_PRESETS), "常用端口", 16)
        self.scan_timeout = field(self.scan_tab, "超时 ms", 0, 5, "800", 10)
        self.scan_workers = field(self.scan_tab, "并发数", 1, 0, "128", 10)
        self.scan_show_closed_var = tk.BooleanVar(value=False)
        self.scan_banner_var = tk.BooleanVar(value=False)
        self._check(self.scan_tab, "显示关闭端口", self.scan_show_closed_var, 1, 1)
        self._check(self.scan_tab, "Banner 探测", self.scan_banner_var, 1, 2)
        self.scan_preset["combobox"].bind("<<ComboboxSelected>>", lambda _event: self.apply_preset(self.scan_preset, self.scan_ports))

        actions = action_bar(self.scan_tab, 2, 6)
        self.scan_start_btn = button(actions, "开始扫描", self.scan_ports_action, "Primary.TButton")
        self.scan_stop_btn = button(actions, "停止", self.stop_scan, "Danger.TButton")
        self.scan_copy_btn = button(actions, "复制开放端口", self.copy_open_ports, "Secondary.TButton")
        self.scan_export_btn = button(actions, "导出 CSV", self.export_results, "Secondary.TButton")

    def build_batch_tab(self):
        for col in range(6):
            self.batch_tab.columnconfigure(col, weight=1)

        self.batch_hosts = field(self.batch_tab, "目标列表 / CIDR / IP 段", 0, 0, "192.168.1.1-254", 46, colspan=2)
        self.batch_ports = field(self.batch_tab, "端口列表 / 范围", 0, 2, "22,80,443,3389", 42, colspan=2)
        self.batch_preset = combo(self.batch_tab, "预设", 0, 4, list(PORT_PRESETS), "远程管理", 16)
        self.batch_timeout = field(self.batch_tab, "超时 ms", 0, 5, "800", 10)
        self.batch_workers = field(self.batch_tab, "并发数", 1, 0, "128", 10)
        self.batch_show_closed_var = tk.BooleanVar(value=False)
        self.batch_banner_var = tk.BooleanVar(value=False)
        self._check(self.batch_tab, "显示关闭端口", self.batch_show_closed_var, 1, 1)
        self._check(self.batch_tab, "Banner 探测", self.batch_banner_var, 1, 2)
        self.batch_preset["combobox"].bind("<<ComboboxSelected>>", lambda _event: self.apply_preset(self.batch_preset, self.batch_ports))

        actions = action_bar(self.batch_tab, 2, 6)
        self.batch_start_btn = button(actions, "批量扫描", self.batch_scan_action, "Primary.TButton")
        self.batch_stop_btn = button(actions, "停止", self.stop_scan, "Danger.TButton")
        self.import_hosts_btn = button(actions, "导入目标", self.import_hosts, "Secondary.TButton")
        self.batch_copy_btn = button(actions, "复制开放端口", self.copy_open_ports, "Secondary.TButton")
        self.batch_export_btn = button(actions, "导出 CSV", self.export_results, "Secondary.TButton")

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
                "total": 0,
                "scanned": 0,
                "open": 0,
                "closed": 0,
                "timeout": 0,
                "progress": 0,
                "elapsed": 0,
            }
        )

    def test_single(self):
        try:
            self.clear()
            self.single_btn.configure(state="disabled")
            self.scanner.test_connect(
                self.single_host["var"].get(),
                int(self.single_port["var"].get()),
                options={
                    "timeout_ms": self.single_timeout["var"].get(),
                    "workers": 1,
                    "show_closed": True,
                    "banner_probe": self.single_banner_var.get(),
                },
            )
        except Exception as exc:
            self.single_btn.configure(state="normal")
            messagebox.showwarning("无法测试端口", str(exc))

    def scan_ports_action(self):
        try:
            self.clear()
            self._set_scan_buttons("disabled")
            self.scanner.start_scan(self.scan_host["var"].get(), self.scan_ports["var"].get(), self.scan_options())
        except Exception as exc:
            self._set_scan_buttons("normal")
            messagebox.showwarning("无法扫描端口", str(exc))

    def batch_scan_action(self):
        try:
            self.clear()
            self._set_scan_buttons("disabled")
            self.scanner.start_batch_scan(self.batch_hosts["var"].get(), self.batch_ports["var"].get(), self.batch_options())
        except Exception as exc:
            self._set_scan_buttons("normal")
            messagebox.showwarning("无法批量扫描", str(exc))

    def stop_scan(self):
        try:
            self.scanner.stop_scan()
        except Exception as exc:
            messagebox.showinfo("提示", str(exc))

    def scan_options(self):
        return {
            "timeout_ms": self.scan_timeout["var"].get(),
            "workers": self.scan_workers["var"].get(),
            "show_closed": self.scan_show_closed_var.get(),
            "banner_probe": self.scan_banner_var.get(),
        }

    def batch_options(self):
        return {
            "timeout_ms": self.batch_timeout["var"].get(),
            "workers": self.batch_workers["var"].get(),
            "show_closed": self.batch_show_closed_var.get(),
            "banner_probe": self.batch_banner_var.get(),
        }

    def apply_preset(self, preset_item, ports_item):
        ports_item["var"].set(PORT_PRESETS.get(preset_item["var"].get(), PORT_PRESETS["常用端口"]))

    def import_hosts(self):
        path = filedialog.askopenfilename(
            title="导入扫描目标",
            filetypes=[("文本文件", "*.txt *.csv"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as file:
                items = []
                for line in file:
                    items.extend(part.strip() for part in line.replace("，", ",").split(",") if part.strip())
            self.batch_hosts["var"].set(",".join(items))
            self.write(f"已导入 {len(items)} 个目标/表达式\n", "success")
        except Exception as exc:
            messagebox.showwarning("导入失败", str(exc))

    def export_results(self):
        path = filedialog.asksaveasfilename(
            title="导出端口扫描结果",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
        )
        if not path:
            return
        try:
            self.scanner.export_results(path)
            self.write(f"已导出结果: {path}\n", "success")
        except Exception as exc:
            messagebox.showwarning("导出失败", str(exc))

    def copy_open_ports(self):
        text = self.scanner.open_ports_summary()
        if not text:
            messagebox.showinfo("提示", "没有可复制的开放端口")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.write("已复制开放端口汇总到剪贴板\n", "success")

    def update_status(self, stats):
        def apply():
            values = [
                (self.state, stats.get("state", "等待")),
                (self.total, str(stats.get("total", 0))),
                (self.scanned, str(stats.get("scanned", 0))),
                (self.open_count, str(stats.get("open", 0))),
                (self.closed_count, str(stats.get("closed", 0))),
                (self.timeout_count, str(stats.get("timeout", 0))),
                (self.progress, f"{stats.get('progress', 0):.1f}% / {stats.get('elapsed', 0):.1f}s"),
            ]
            for item, value in values:
                item["entry"].configure(state="normal")
                item["var"].set(value)
                item["entry"].configure(state="disabled")

        self.after(0, apply)

    def add_result(self, row):
        def apply():
            port = row.get("port") or "-"
            latency = f"{row.get('latency_ms', 0):.1f} ms" if row.get("latency_ms") else "-"
            detail = row.get("banner") or row.get("error") or ""
            self.results_tree.insert(
                "",
                "end",
                values=(
                    row.get("host", ""),
                    row.get("resolved_ip", ""),
                    port,
                    row.get("service", ""),
                    row.get("status_text", ""),
                    latency,
                    detail,
                ),
                tags=(row.get("status", ""),),
            )

        self.after(0, apply)

    def _set_scan_buttons(self, state):
        self.scan_start_btn.configure(state=state)
        self.batch_start_btn.configure(state=state)

    def on_task_done(self):
        self.after(
            0,
            lambda: (
                self.single_btn.configure(state="normal"),
                self._set_scan_buttons("normal"),
            ),
        )
