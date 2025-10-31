import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import logging

from core.ui.basic_ui import BasicUI
from core.Function.network_fun import NetworkManager  

logger = logging.getLogger(__name__)

class NetworkTab(ttk.Frame, BasicUI):
    """网卡配置 Tab（兼容最新 NetworkManager）"""

    def __init__(self, parent):
        super().__init__(parent)
        self.netmgr = NetworkManager()
        self._build_ui()
        threading.Thread(target=self.refresh_interfaces, daemon=True).start()

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        self.create_iface_section()
        self.create_config_section()
        self.create_action_section()
        self.create_output_section()
        self._set_button_state(enabled=True)

    def create_iface_section(self):
        frame = ttk.LabelFrame(self, text="网卡选择", padding=8)
        frame.pack(side='top', fill='x', padx=10, pady=6)

        self.iface_var = tk.StringVar()
        ttk.Label(frame, text="选择网卡：").grid(row=0, column=0, sticky='w')
        self.iface_cb = ttk.Combobox(frame, textvariable=self.iface_var, state='readonly', width=40)
        self.iface_cb.grid(row=0, column=1, padx=6, pady=2)
        self.iface_cb.bind("<<ComboboxSelected>>", self.on_iface_selected)

        self.refresh_btn = ttk.Button(frame, text="刷新", width=10, command=self.on_refresh_clicked)
        self.refresh_btn.grid(row=0, column=2, padx=6)

    def create_config_section(self):
        frame = ttk.LabelFrame(self, text="IP 配置（编辑后点击应用）", padding=8)
        frame.pack(side='top', fill='x', padx=10, pady=6)

        self.ip_entry = self.add_input(frame, "IPv4 地址", row=0, col=0, inivar="", entry_width=25)
        self.mask_entry = self.add_input(frame, "子网掩码", row=0, col=1, inivar="", entry_width=20)
        self.gw_entry = self.add_input(frame, "默认网关", row=1, col=0, inivar="", entry_width=25)
        self.dns1_entry = self.add_input(frame, "主 DNS", row=1, col=1, inivar="", entry_width=25)
        self.dns2_entry = self.add_input(frame, "备选 DNS", row=1, col=2, inivar="", entry_width=25)

        self.dhcp_var = tk.BooleanVar(value=False)
        self.dhcp_chk = ttk.Checkbutton(frame, text="使用 DHCP（自动获取 IP）", variable=self.dhcp_var,
                                        command=self.on_dhcp_toggled)
        self.dhcp_chk.grid(row=2, column=0, columnspan=2, sticky='w', pady=6)

    def create_action_section(self):
        frame = ttk.Frame(self)
        frame.pack(side='top', fill='x', padx=10, pady=6)
        self.apply_btn = self.add_button(frame, "应用修改", row=0, col=0, command=self.on_apply_clicked)
        self.dhcp_btn = self.add_button(frame, "切换为 DHCP", row=0, col=1, command=self.on_set_dhcp)
        self.refresh_info_btn = self.add_button(frame, "刷新当前信息", row=0, col=2, command=self.on_refresh_info)

    def create_output_section(self):
        frame = ttk.LabelFrame(self, text="操作日志", padding=6)
        frame.pack(side='top', fill='both', expand=True, padx=10, pady=6)
        self.result_box = scrolledtext.ScrolledText(frame, width=100, height=12)
        self.result_box.pack(fill='both', expand=True, padx=4, pady=4)

    def _set_button_state(self, enabled: bool):
        state = 'normal' if enabled else 'disabled'
        for btn in [self.apply_btn, self.dhcp_btn, self.refresh_info_btn, self.refresh_btn]:
            try:
                btn.config(state=state)
            except Exception:
                pass

    # ---------------- 事件回调 ----------------
    def on_refresh_clicked(self):
        self._append_log("刷新网卡列表中...\n")
        threading.Thread(target=self.refresh_interfaces, daemon=True).start()

    def refresh_interfaces(self):
        try:
            adapters = self.netmgr.get_all_adapters()
        except Exception as e:
            self._append_log(f"获取网卡失败: {e}\n")
            return

        names = [a.get("name") or a.get("desc") or str(i) for i, a in enumerate(adapters)]

        def update_ui():
            self._adapters = adapters
            self.iface_cb['values'] = names
            if names:
                self.iface_var.set(names[0])
                self.load_selected_adapter_info(names[0])
        self.after(0, update_ui)
        self._append_log("网卡列表刷新完成。\n")

    def on_iface_selected(self, event=None):
        name = self.iface_var.get()
        self.load_selected_adapter_info(name)

    def load_selected_adapter_info(self, name):
        adapter = next((a for a in getattr(self, "_adapters", []) if a.get("name")==name or a.get("desc")==name), None)
        if not adapter:
            self._append_log(f"未找到网卡信息：{name}\n")
            return

        try:
            self.ip_entry['var'].set(adapter.get("ip", ""))
            self.mask_entry['var'].set(adapter.get("mask", ""))
            self.gw_entry['var'].set(adapter.get("gateway", ""))
            self.dns1_entry['var'].set(adapter.get("dns1", ""))
            self.dns2_entry['var'].set(adapter.get("dns2", ""))
        except Exception:
            pass

        self.dhcp_var.set(True if str(adapter.get("dhcp", "")).lower() in ("yes","true","是") else False)
        self._append_log(f"已加载网卡：{name}  IP={adapter.get('ip')} 掩码={adapter.get('mask')} 网关={adapter.get('gateway')} DHCP={adapter.get('dhcp')} MAC={adapter.get('mac')}\n")

    def on_dhcp_toggled(self):
        use_dhcp = self.dhcp_var.get()
        state = 'disabled' if use_dhcp else 'normal'
        for entry in [self.ip_entry, self.mask_entry, self.gw_entry]:
            try:
                entry['entry'].config(state=state)
            except Exception:
                try:
                    entry.config(state=state)
                except Exception:
                    pass

    def on_refresh_info(self):
        name = self.iface_var.get()
        if not name:
            messagebox.showwarning("提示", "请先选择一个网卡")
            return
        self._append_log(f"读取 {name} 的当前配置信息...\n")
        threading.Thread(target=self._refresh_info_thread, args=(name,), daemon=True).start()

    def _refresh_info_thread(self, name):
        try:
            adapters = self.netmgr.get_all_adapters()
            self._adapters = adapters
            for a in adapters:
                if a.get("name")==name or a.get("desc")==name:
                    self.after(0, lambda ad=a: self.load_selected_adapter_info(ad.get("name")))
                    break
            self._append_log("刷新完成。\n")
        except Exception as e:
            self._append_log(f"读取配置失败: {e}\n")

    def on_apply_clicked(self):
        name = self.iface_var.get()
        if not name:
            messagebox.showwarning("提示", "请选择一个网卡")
            return

        def read_field(field):
            try: return field['var'].get().strip()
            except Exception:
                try: return field.get().strip()
                except Exception: return ""

        ip = read_field(self.ip_entry)
        mask = read_field(self.mask_entry)
        gw = read_field(self.gw_entry)
        dns1 = read_field(self.dns1_entry)
        dns2 = read_field(self.dns2_entry)

        if self.dhcp_var.get():
            if not messagebox.askyesno("确认", f"确定将网卡 [{name}] 切换为 DHCP 模式吗？"):
                return
            self._set_button_state(False)
            threading.Thread(target=self._set_dhcp_thread, args=(name,), daemon=True).start()
            return

        if not ip or not mask:
            messagebox.showwarning("输入错误", "IP 与掩码不能为空（或勾选 DHCP）")
            return

        self._set_button_state(False)
        threading.Thread(target=self._set_static_thread, args=(name, ip, mask, gw, dns1, dns2), daemon=True).start()

    def _set_dhcp_thread(self, name):
        try:
            res = self.netmgr.set_dhcp(name)
            self._append_log(f"{res}\n")
            messagebox.showinfo("完成", res)
            threading.Thread(target=self.refresh_interfaces, daemon=True).start()
        except Exception as e:
            self._append_log(f"设置 DHCP 失败: {e}\n")
            messagebox.showerror("失败", f"设置 DHCP 失败: {e}")
        finally:
            self._set_button_state(True)

    def _set_static_thread(self, name, ip, mask, gw, dns1, dns2):
        try:
            res = self.netmgr.set_static_ip(name, ip, mask, gw)
            self._append_log(f"{res}\n")
            if dns1:
                try:
                    res_dns = self.netmgr.set_dns(name, dns1, dns2)
                    self._append_log(f"{res_dns}\n")
                except Exception as e:
                    self._append_log(f"设置 DNS 失败: {e}\n")
            messagebox.showinfo("完成", "配置已应用（请注意可能需要管理员权限）")
            threading.Thread(target=self.refresh_interfaces, daemon=True).start()
        except Exception as e:
            self._append_log(f"应用静态 IP 失败: {e}\n")
            messagebox.showerror("失败", f"应用静态 IP 失败: {e}")
        finally:
            self._set_button_state(True)

    def on_set_dhcp(self):
        name = self.iface_var.get()
        if not name:
            messagebox.showwarning("提示", "请选择一个网卡")
            return
        if not messagebox.askyesno("确认", f"确定将网卡 [{name}] 切换为 DHCP 模式吗？"):
            return
        self._set_button_state(False)
        threading.Thread(target=self._set_dhcp_thread, args=(name,), daemon=True).start()

    def _append_log(self, text: str):
        try:
            self.result_box.after(0, lambda: (self.result_box.insert(tk.END, text), self.result_box.see(tk.END)))
        except Exception:
            pass
