import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.Function.dns_diag_fun import ALL_ADAPTERS, DEFAULT_DOMAINS, DEFAULT_RECORD_TYPES, DnsDiagnostic
from core.ui.components import Page, action_bar, button, combo, field


class DnsTab(Page):
    def __init__(self, parent, console):
        super().__init__(parent, "DNS 诊断", "对比本机 DNS 与常用 DNS 的解析结果、耗时和失败原因。")
        self.console = console
        self.body.rowconfigure(2, weight=1)

        status = self.section("实时状态", 0, columns=6)
        self.state = field(status, "状态", 1, 0, "等待", 10)
        self.current_dns = field(status, "当前 DNS", 1, 1, "-", 24, colspan=2)
        self.target_total = field(status, "目标数", 1, 3, "0", 8)
        self.progress = field(status, "进度", 1, 4, "0/0", 10)
        self.abnormal = field(status, "异常数", 1, 5, "0", 8)
        self.elapsed = field(status, "耗时", 2, 0, "0.0s", 10)
        for item in (self.state, self.current_dns, self.target_total, self.progress, self.abnormal, self.elapsed):
            item["entry"].configure(state="disabled")

        params = self.section("诊断参数", 1, columns=6)
        self.adapter = combo(params, "检测网卡", 1, 0, [ALL_ADAPTERS], ALL_ADAPTERS, 22)
        self.domains = field(params, "目标域名", 1, 1, DEFAULT_DOMAINS, 34, colspan=2)
        self.record_types = field(params, "记录类型", 1, 3, DEFAULT_RECORD_TYPES, 18)
        self.timeout = field(params, "超时 ms", 1, 4, "2000", 10)
        self.repeat_count = field(params, "重复次数", 1, 5, "1", 10)
        self.dns_servers = field(params, "DNS 服务器", 2, 0, "", 60, colspan=6)
        actions = action_bar(params, 3, 6)
        self.start_btn = button(actions, "开始诊断", self.start_diagnosis, "Primary.TButton")
        self.stop_btn = button(actions, "停止", self.stop_diagnosis, "Danger.TButton")
        self.refresh_btn = button(actions, "刷新网卡", self.load_adapters, "Secondary.TButton")
        self.auto_dns_btn = button(actions, "自动 DNS", self.fill_default_dns, "Secondary.TButton")
        self.repair_btn = button(actions, "修复异常", self.repair_dns, "Secondary.TButton")
        self.copy_btn = button(actions, "复制摘要", self.copy_summary, "Secondary.TButton")
        self.export_btn = button(actions, "导出 CSV", self.export_results, "Secondary.TButton")

        results = self.section("诊断结果", 2, columns=1)
        results.rowconfigure(1, weight=1)
        results.columnconfigure(0, weight=1)
        self.results_tree = ttk.Treeview(
            results,
            columns=("domain", "type", "server", "status", "elapsed", "values", "verdict"),
            show="headings",
            height=10,
        )
        headings = {
            "domain": "域名",
            "type": "类型",
            "server": "DNS 服务器",
            "status": "状态",
            "elapsed": "耗时",
            "values": "解析结果",
            "verdict": "错误 / 判断",
        }
        widths = {
            "domain": 130,
            "type": 56,
            "server": 116,
            "status": 64,
            "elapsed": 76,
            "values": 220,
            "verdict": 260,
        }
        for column, title in headings.items():
            self.results_tree.heading(column, text=title)
            self.results_tree.column(column, width=widths[column], anchor="w")
        self.results_tree.tag_configure("正常", foreground="#15803d")
        self.results_tree.tag_configure("无记录", foreground="#b7791f")
        self.results_tree.tag_configure("失败", foreground="#dc2626")
        self.results_tree.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        result_scroll = ttk.Scrollbar(results, orient="vertical", command=self.results_tree.yview)
        result_scroll.grid(row=1, column=1, sticky="ns", pady=(0, 18))
        x_scroll = ttk.Scrollbar(results, orient="horizontal", command=self.results_tree.xview)
        x_scroll.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))
        self.results_tree.configure(yscrollcommand=result_scroll.set, xscrollcommand=x_scroll.set)

        self.diagnostic = DnsDiagnostic(self.write, self.on_task_done, self.update_status, self.add_result)
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
                "current_dns": "-",
                "total": 0,
                "completed": 0,
                "abnormal": 0,
                "elapsed": 0,
            }
        )

    def load_adapters(self):
        def worker():
            try:
                values, default_dns = self.diagnostic.get_adapter_choices_and_default_dns()
            except Exception as exc:
                values = [ALL_ADAPTERS]
                default_dns = ""
                self.write(f"读取网卡 DNS 失败: {exc}\n", "warning")
            self.after(0, lambda: self.apply_adapters(values, default_dns))

        threading.Thread(target=worker, daemon=True).start()

    def apply_adapters(self, values, default_dns):
        values = values or [ALL_ADAPTERS]
        values = list(dict.fromkeys(values))
        self.adapter["combobox"]["values"] = values
        if self.adapter["var"].get() not in values:
            self.adapter["var"].set(ALL_ADAPTERS)
        if not self.dns_servers["var"].get() and default_dns:
            self.dns_servers["var"].set(default_dns)

    def fill_default_dns(self):
        try:
            value = self.diagnostic.default_dns_servers(self.adapter["var"].get())
            if not value:
                messagebox.showinfo("提示", "未读取到本机 DNS，已保留常用 DNS 对比服务器")
                value = "223.5.5.5,114.114.114.114,8.8.8.8"
            self.dns_servers["var"].set(value)
            self.write(f"已生成 DNS 对比列表: {value}\n", "success")
        except Exception as exc:
            messagebox.showwarning("生成失败", str(exc))

    def start_diagnosis(self):
        try:
            self.clear()
            self.start_btn.configure(state="disabled")
            self.repair_btn.configure(state="disabled")
            self.diagnostic.start_diagnosis(self.adapter["var"].get(), self.options())
        except Exception as exc:
            self.start_btn.configure(state="normal")
            self.repair_btn.configure(state="normal")
            messagebox.showwarning("无法开始 DNS 诊断", str(exc))

    def stop_diagnosis(self):
        try:
            self.diagnostic.stop_diagnosis()
        except Exception as exc:
            messagebox.showinfo("提示", str(exc))

    def options(self):
        return {
            "domains": self.domains["var"].get(),
            "record_types": self.record_types["var"].get(),
            "dns_servers": self.dns_servers["var"].get(),
            "timeout_ms": self.timeout["var"].get(),
            "repeat_count": self.repeat_count["var"].get(),
        }

    def export_results(self):
        path = filedialog.asksaveasfilename(
            title="导出 DNS 诊断结果",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
        )
        if not path:
            return
        try:
            self.diagnostic.export_results(path)
            self.write(f"已导出结果: {path}\n", "success")
        except Exception as exc:
            messagebox.showwarning("导出失败", str(exc))

    def repair_dns(self):
        adapter = self.adapter["var"].get() or ALL_ADAPTERS
        if not messagebox.askyesno(
            "确认修复 DNS",
            f"将把“{adapter}”的 DNS 设置为 223.5.5.5 和 114.114.114.114，并刷新 DNS 缓存。\n\n此操作需要管理员权限，确定继续吗？",
        ):
            return

        self.repair_btn.configure(state="disabled")
        self.start_btn.configure(state="disabled")
        self.write("\n开始修复 DNS 异常...\n", "warning")

        def worker():
            try:
                result = self.diagnostic.repair_abnormal_dns(adapter)
                self.after(0, lambda: self.on_repair_success(result))
            except Exception as exc:
                self.after(0, lambda: self.on_repair_failed(exc))

        threading.Thread(target=worker, daemon=True).start()

    def on_repair_success(self, result):
        names = "、".join(result.get("adapters", []))
        servers = ",".join(result.get("servers", []))
        self.write(f"DNS 修复完成: {names} -> {servers}\n", "success")
        self.dns_servers["var"].set(servers)
        self.load_adapters()
        self.start_btn.configure(state="normal")
        self.repair_btn.configure(state="normal")

    def on_repair_failed(self, exc):
        self.write(f"DNS 修复失败: {exc}\n", "error")
        self.start_btn.configure(state="normal")
        self.repair_btn.configure(state="normal")
        messagebox.showerror("DNS 修复失败", f"{exc}\n\n请确认程序已用管理员权限运行。")

    def copy_summary(self):
        text = self.diagnostic.copy_summary()
        if not text:
            messagebox.showinfo("提示", "还没有可复制的 DNS 诊断摘要")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.write("已复制 DNS 诊断摘要到剪贴板\n", "success")

    def update_status(self, stats):
        def apply():
            total = stats.get("total", 0)
            completed = stats.get("completed", 0)
            values = [
                (self.state, stats.get("state", "等待")),
                (self.current_dns, stats.get("current_dns") or "-"),
                (self.target_total, str(total)),
                (self.progress, f"{completed}/{total}" if total else "0/0"),
                (self.abnormal, str(stats.get("abnormal", 0))),
                (self.elapsed, f"{stats.get('elapsed', 0):.1f}s"),
            ]
            for item, value in values:
                item["entry"].configure(state="normal")
                item["var"].set(value)
                item["entry"].configure(state="disabled")

        self.after(0, apply)

    def add_result(self, row):
        def apply():
            elapsed = row.get("elapsed_ms", 0)
            try:
                elapsed_text = f"{float(elapsed):.1f} ms" if float(elapsed) > 0 else ""
            except (TypeError, ValueError):
                elapsed_text = ""
            detail = row.get("error") or row.get("verdict", "")
            self.results_tree.insert(
                "",
                "end",
                values=(
                    row.get("domain", ""),
                    row.get("record_type", ""),
                    row.get("dns_server", ""),
                    row.get("status", ""),
                    elapsed_text,
                    row.get("values", ""),
                    detail,
                ),
                tags=(row.get("status", ""),),
            )

        self.after(0, apply)

    def on_task_done(self):
        self.after(0, lambda: (self.start_btn.configure(state="normal"), self.repair_btn.configure(state="normal")))
