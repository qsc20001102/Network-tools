import threading
from tkinter import messagebox

from core.Function.network_fun import NetworkManager
from core.ui.components import Page, action_bar, button, combo, field, set_entry_state


class NetworkTab(Page):
    def __init__(self, parent, console):
        super().__init__(parent, "网卡配置", "查看本机网卡信息，切换 DHCP，或写入静态 IPv4 / DNS 配置。")
        self.console = console
        self.body.rowconfigure(3, weight=1)
        self.adapters = []
        self.profiles = {}

        selector = self.section("网卡选择", 0, columns=4)
        self.iface = combo(selector, "选择网卡", 1, 0, [], "", 44, colspan=2)
        self.iface["combobox"].bind("<<ComboboxSelected>>", lambda _event: self.load_selected_adapter())
        self.status = field(selector, "连接状态", 1, 2, "", 14)
        self.status["entry"].configure(state="disabled")
        actions = action_bar(selector, 2, 4)
        self.refresh_btn = button(actions, "刷新网卡", self.refresh_adapters, "Primary.TButton")

        identity = self.section("网卡信息", 1, columns=4)
        self.description = field(identity, "设备描述", 1, 0, "", 46, colspan=2)
        self.mac = field(identity, "MAC 地址", 1, 2, "", 24)
        adapter_actions = action_bar(identity, 2, 4)
        self.enable_adapter_btn = button(adapter_actions, "启用网卡", self.enable_adapter, "Primary.TButton")
        self.disable_adapter_btn = button(adapter_actions, "禁用网卡", self.disable_adapter, "Danger.TButton")
        for item in (self.description, self.mac):
            item["entry"].configure(state="disabled")

        config = self.section("IPv4 配置", 2, columns=4)
        self.dhcp = combo(config, "地址模式", 1, 0, ["DHCP 自动获取", "静态手动配置"], "DHCP 自动获取", 18)
        self.dhcp["combobox"].bind("<<ComboboxSelected>>", lambda _event: self.update_entry_state())
        self.ipv4 = field(config, "IPv4 地址", 1, 1, "", 18)
        self.netmask = field(config, "子网掩码", 1, 2, "", 18)
        self.gateway = field(config, "默认网关", 1, 3, "", 18)
        self.dns1 = field(config, "首选 DNS", 2, 1, "", 18)
        self.dns2 = field(config, "备用 DNS", 2, 2, "", 18)
        config_actions = action_bar(config, 3, 4)
        self.apply_btn = button(config_actions, "应用配置", self.apply_settings, "Primary.TButton")
        self.reload_btn = button(config_actions, "重新读取", self.refresh_adapters, "Secondary.TButton")

        profiles = self.section("配置模板", 3, columns=4)
        self.profile_name = field(profiles, "模板名称", 1, 0, "", 20)
        self.profile_select = combo(profiles, "选择模板", 1, 1, [], "", 24)
        profile_actions = action_bar(profiles, 2, 4)
        self.save_profile_btn = button(profile_actions, "保存当前为模板", self.save_profile, "Primary.TButton")
        self.apply_profile_btn = button(profile_actions, "套用模板到表单", self.apply_profile_to_form, "Secondary.TButton")
        self.delete_profile_btn = button(profile_actions, "删除模板", self.delete_profile, "Danger.TButton")

        self.netmgr = NetworkManager(self.write)
        self.load_profiles()
        self.after(250, self.refresh_adapters)

    def write(self, text, tag=None):
        self.console.write(text, tag)

    def refresh_adapters(self, clear=True):
        self.refresh_btn.configure(state="disabled")
        self.reload_btn.configure(state="disabled")
        self.enable_adapter_btn.configure(state="disabled")
        self.disable_adapter_btn.configure(state="disabled")
        if clear:
            self.console.clear()
        self.write("正在读取本机网卡信息...\n", "muted")

        def worker():
            try:
                adapters = self.netmgr.get_network_info()
                self.after(0, lambda: self.on_adapters_loaded(adapters))
            except Exception as exc:
                self.after(0, lambda: self.on_refresh_failed(exc))

        threading.Thread(target=worker, daemon=True).start()

    def on_adapters_loaded(self, adapters):
        self.adapters = adapters
        names = [adapter["name"] for adapter in adapters]
        self.iface["combobox"]["values"] = names
        if names:
            current = self.iface["var"].get()
            self.iface["var"].set(current if current in names else names[0])
            self.load_selected_adapter()
            self.write(f"读取完成，共发现 {len(names)} 个网卡\n", "success")
        else:
            self.write("未发现可用网卡\n", "warning")
            self.update_adapter_action_state()
        self.refresh_btn.configure(state="normal")
        self.reload_btn.configure(state="normal")

    def on_refresh_failed(self, exc):
        self.write(f"读取网卡失败: {exc}\n", "error")
        self.refresh_btn.configure(state="normal")
        self.reload_btn.configure(state="normal")
        self.update_adapter_action_state()
        messagebox.showerror("读取网卡失败", str(exc))

    def load_selected_adapter(self):
        adapter = self.current_adapter()
        if not adapter:
            return

        self.status["entry"].configure(state="normal")
        self.description["entry"].configure(state="normal")
        self.mac["entry"].configure(state="normal")

        self.status["var"].set(adapter.get("status", ""))
        self.description["var"].set(adapter.get("description", ""))
        self.mac["var"].set(adapter.get("mac", ""))
        self.ipv4["var"].set(adapter.get("ipv4", ""))
        self.netmask["var"].set(adapter.get("netmask", ""))
        self.gateway["var"].set(adapter.get("gateway", ""))
        self.dns1["var"].set(adapter.get("dns1", ""))
        self.dns2["var"].set(adapter.get("dns2", ""))
        self.dhcp["var"].set("DHCP 自动获取" if adapter.get("dhcp_enabled") else "静态手动配置")

        self.status["entry"].configure(state="disabled")
        self.description["entry"].configure(state="disabled")
        self.mac["entry"].configure(state="disabled")
        self.update_entry_state()
        self.update_adapter_action_state(adapter)
        self.write_current_adapter(adapter)

    def current_adapter(self):
        name = self.iface["var"].get()
        for adapter in self.adapters:
            if adapter.get("name") == name:
                return adapter
        return None

    def update_entry_state(self):
        static = self.dhcp["var"].get() == "静态手动配置"
        for item in (self.ipv4, self.netmask, self.gateway, self.dns1, self.dns2):
            set_entry_state(item, static)

    def update_adapter_action_state(self, adapter=None):
        adapter = adapter or self.current_adapter()
        if not adapter:
            self.enable_adapter_btn.configure(state="disabled")
            self.disable_adapter_btn.configure(state="disabled")
            return

        status = str(adapter.get("status", "")).lower()
        disabled = "disabled" in status or "禁用" in status
        self.enable_adapter_btn.configure(state="normal" if disabled else "disabled")
        self.disable_adapter_btn.configure(state="disabled" if disabled else "normal")

    def enable_adapter(self):
        self.set_adapter_enabled(True)

    def disable_adapter(self):
        adapter = self.current_adapter()
        if not adapter:
            messagebox.showwarning("无法禁用网卡", "请先选择网卡")
            return
        name = adapter.get("name", "")
        if not messagebox.askyesno("确认禁用网卡", f"确定禁用网卡“{name}”吗？\n\n这可能会中断当前网络连接。"):
            return
        self.set_adapter_enabled(False)

    def set_adapter_enabled(self, enabled: bool):
        adapter = self.current_adapter()
        if not adapter:
            messagebox.showwarning("无法操作网卡", "请先选择网卡")
            return

        self.enable_adapter_btn.configure(state="disabled")
        self.disable_adapter_btn.configure(state="disabled")
        action = "启用" if enabled else "禁用"

        def worker():
            try:
                self.netmgr.set_adapter_enabled(adapter.get("name", ""), enabled)
                self.after(0, lambda: self.on_adapter_action_success(action))
            except Exception as exc:
                self.after(0, lambda: self.on_adapter_action_failed(action, exc))

        threading.Thread(target=worker, daemon=True).start()

    def on_adapter_action_success(self, action: str):
        self.write(f"网卡{action}完成，正在刷新网卡信息...\n", "success")
        self.refresh_adapters(clear=False)

    def on_adapter_action_failed(self, action: str, exc):
        self.write(f"网卡{action}失败: {exc}\n", "error")
        self.update_adapter_action_state()
        messagebox.showerror(f"网卡{action}失败", f"{exc}\n\n请确认程序已用管理员权限运行。")

    def write_current_adapter(self, adapter):
        self.write("\n当前网卡:\n", "muted")
        rows = [
            ("名称", adapter.get("name", "")),
            ("描述", adapter.get("description", "")),
            ("状态", adapter.get("status", "")),
            ("速率", adapter.get("link_speed", "")),
            ("接口索引", adapter.get("interface_index", "")),
            ("IPv4", adapter.get("ipv4", "")),
            ("IPv6", ", ".join(adapter.get("ipv6", []))),
            ("掩码", adapter.get("netmask", "")),
            ("网关", adapter.get("gateway", "")),
            ("DNS", ", ".join(value for value in (adapter.get("dns1", ""), adapter.get("dns2", "")) if value)),
            ("DHCP", "是" if adapter.get("dhcp_enabled") else "否"),
            ("DHCP 服务器", adapter.get("dhcp_server", "")),
            ("租约获取", adapter.get("dhcp_lease_obtained", "")),
            ("租约过期", adapter.get("dhcp_lease_expires", "")),
        ]
        for key, value in rows:
            self.write(f"  {key}: {value}\n", "muted")

    def collect_settings(self):
        return {
            "name": self.iface["var"].get(),
            "dhcp_enabled": self.dhcp["var"].get() == "DHCP 自动获取",
            "ipv4": self.ipv4["var"].get(),
            "netmask": self.netmask["var"].get(),
            "gateway": self.gateway["var"].get(),
            "dns1": self.dns1["var"].get(),
            "dns2": self.dns2["var"].get(),
        }

    def apply_settings(self):
        settings = self.collect_settings()
        if not settings["name"]:
            messagebox.showwarning("无法应用配置", "请先选择网卡")
            return

        self.apply_btn.configure(state="disabled")
        self.write("\n开始应用配置。修改网卡通常需要管理员权限。\n", "warning")

        def worker():
            try:
                self.netmgr.set_network_info(settings)
                self.after(0, self.on_apply_success)
            except Exception as exc:
                self.after(0, lambda: self.on_apply_failed(exc))

        threading.Thread(target=worker, daemon=True).start()

    def on_apply_success(self):
        self.apply_btn.configure(state="normal")
        self.write("配置应用完成，正在刷新网卡信息...\n", "success")
        self.refresh_adapters(clear=False)

    def on_apply_failed(self, exc):
        self.apply_btn.configure(state="normal")
        self.write(f"配置应用失败: {exc}\n", "error")
        messagebox.showerror("配置应用失败", f"{exc}\n\n请确认程序已用管理员权限运行。")

    def load_profiles(self):
        try:
            self.profiles = self.netmgr.load_profiles()
        except Exception as exc:
            self.profiles = {}
            self.write(f"读取模板失败: {exc}\n", "warning")
        names = sorted(self.profiles.keys())
        self.profile_select["combobox"]["values"] = names
        if names and not self.profile_select["var"].get():
            self.profile_select["var"].set(names[0])

    def save_profile(self):
        try:
            name = self.profile_name["var"].get().strip()
            if not name:
                adapter = self.current_adapter()
                name = adapter.get("name", "未命名模板") if adapter else "未命名模板"
            self.netmgr.save_profile(name, self.collect_settings())
            self.profile_name["var"].set(name)
            self.profile_select["var"].set(name)
            self.load_profiles()
            self.write(f"已保存配置模板: {name}\n", "success")
        except Exception as exc:
            messagebox.showwarning("保存模板失败", str(exc))

    def apply_profile_to_form(self):
        name = self.profile_select["var"].get()
        profile = self.profiles.get(name)
        if not profile:
            messagebox.showinfo("提示", "请选择要套用的模板")
            return

        self.dhcp["var"].set("DHCP 自动获取" if profile.get("dhcp_enabled") else "静态手动配置")
        self.ipv4["var"].set(profile.get("ipv4", ""))
        self.netmask["var"].set(profile.get("netmask", ""))
        self.gateway["var"].set(profile.get("gateway", ""))
        self.dns1["var"].set(profile.get("dns1", ""))
        self.dns2["var"].set(profile.get("dns2", ""))
        self.update_entry_state()
        self.write(f"已套用模板到表单: {name}\n", "success")

    def delete_profile(self):
        name = self.profile_select["var"].get()
        if not name:
            messagebox.showinfo("提示", "请选择要删除的模板")
            return
        if not messagebox.askyesno("确认删除模板", f"确定删除配置模板“{name}”吗？"):
            return
        try:
            self.netmgr.delete_profile(name)
            self.profile_select["var"].set("")
            self.load_profiles()
            self.write(f"已删除配置模板: {name}\n", "success")
        except Exception as exc:
            messagebox.showwarning("删除模板失败", str(exc))
