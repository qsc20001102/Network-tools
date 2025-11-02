import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import re

import logging
from core.ui.basic_ui import BasicUI
from core.Function.network_fun import NetworkManager  

logger = logging.getLogger(__name__)

class NetworkTab(ttk.Frame, BasicUI):
    """网卡配置 Tab（兼容最新 NetworkManager）"""

    def __init__(self, parent):
        super().__init__(parent)
        
        self.networkname_list = []
        self.networkconfig = []
        self.build_ui()
        self.netmgr = NetworkManager(self.result_box)
        self.refresh_allnetwork()

    def build_ui(self):
        self.create_iface_section()
        self.create_config_section()
        self.create_action_section()
        self.create_output_section()

    def refresh_allnetwork(self):
        '''刷新网卡列表'''
        self.networkname_list = []
        try:
            self.networkconfigs = self.netmgr.get_network_info()
            for config in self.networkconfigs:
                self.networkname_list.append(config.get("name", "未知网卡"))
            self.iface_cb['combobox']['values'] = self.networkname_list
            self.iface_cb['var'].set(self.networkname_list[0])
            self.result_box.insert(tk.END, f"获取网卡信息完成，共:{len(self.networkname_list)}个启用网卡\n")
            self.refresh_network_callback()

            logger.info(f"获取网卡信息完成，共:{len(self.networkname_list)}个启用网卡")
            logger.info(f"所有获取网卡信息：{self.networkconfigs}")
        except Exception as e:
            messagebox.showerror("错误", f"获取网卡信息失败: {e}")
            logger.error(f"获取网卡信息失败: {e}")
            self.networkconfigs = []

    # ---------------- UI 构建 ----------------
    def create_iface_section(self):
        frame = ttk.LabelFrame(self, text="网卡选择", padding=8)
        frame.pack(side='top', fill='x', padx=10, pady=6)

        self.iface_cb = self.add_combobox(frame, "选择网卡", row=0, col=0, listbox=[], width=40, inivar=-1)
        self.iface_cb['combobox'].bind("<<ComboboxSelected>>", lambda e: self.refresh_network_callback())
        self.refresh_btn = self.add_button(frame, "刷新网卡列表", row=0, col=1, width=15, command=self.refresh_allnetwork)
        self.description_entry = self.add_input(frame, "网卡名称", row=1, col=0, inivar="", entry_width=40)
        self.description_entry['entry'].config(state='disabled')
        self.mac_entry = self.add_input(frame, "MAC地址", row=1, col=1, inivar="", entry_width=40)
        self.mac_entry['entry'].config(state='disabled')

    def create_config_section(self):
        frame = ttk.LabelFrame(self, text="IP 配置（编辑后点击应用）", padding=8)
        frame.pack(side='top', fill='x', padx=10, pady=6)

        self.ip_entry = self.add_input(frame, "IPv4 地址", row=0, col=0, inivar="", entry_width=20)
        self.mask_entry = self.add_input(frame, "子网掩码", row=0, col=1, inivar="", entry_width=20)
        self.gw_entry = self.add_input(frame, "默认网关", row=0, col=2, inivar="", entry_width=20)
        #self.dns1_entry = self.add_input(frame, "主 DNS", row=1, col=0, inivar="", entry_width=20)
        #self.dns2_entry = self.add_input(frame, "备选 DNS", row=1, col=1, inivar="", entry_width=20)
        self.dhcp_cb = self.add_combobox(frame, "自动获取", row=2, col=0, listbox=["是","否"], width=5, inivar=-1)
        self.dhcp_cb['combobox'].bind("<<ComboboxSelected>>", lambda e: self.dhcp_entry_state())

    def create_action_section(self):
        frame = ttk.LabelFrame(self, text="修改操作", padding=8)
        frame.pack(side='top', fill='x', padx=10, pady=6)

        self.apply_btn = self.add_button(frame, "应用修改", row=0, col=0, width=10, command=self.apply_btn_callback)
        self.refresh_info_btn = self.add_button(frame, "刷新当前信息", row=0, col=2, width=15, command=self.refresh_network_callback)

    def create_output_section(self):
        frame = ttk.LabelFrame(self, text="输出信息", padding=6)
        frame.pack(side='top', fill='both', expand=True, padx=10, pady=6)

        self.result_box = scrolledtext.ScrolledText(frame, width=100, height=12)
        self.result_box.pack(fill='both', expand=True, padx=4, pady=4)


    # ---------------- 事件回调 ----------------
    def refresh_network_callback(self):
        '''刷新当前网卡信息'''
        # 刷新所有所有网卡信息
        self.refresh_allnetwork()
        # 获取选中的网卡信息
        iface_name = self.iface_cb['var'].get()
        config = self.get_network_config(iface_name)
        # 不可修改配置
        self.description_entry['var'].set(config.get("description", ""))
        self.mac_entry['var'].set(config.get("mac", ""))
        # 可修改配置
        self.ip_entry['var'].set(config.get("ipv4", ""))
        self.mask_entry['var'].set(config.get("netmask", ""))   
        self.gw_entry['var'].set(config.get("gateway", ""))
        #self.dns1_entry['var'].set(config.get("dns1", ""))
        #self.dns2_entry['var'].set(config.get("dns2", ""))
        if config.get("dhcp_enabled", "") == "是":
            self.dhcp_cb['var'].set("是")
        elif config.get("dhcp_enabled", "") == "否":
            self.dhcp_cb['var'].set("否")
        else:
            self.dhcp_cb['var'].set("")
        self.dhcp_entry_state()
        self.get_network_settings()
        self.output_network_settings()

    def get_network_config(self, iface_name):
        '''根据网卡名称获取对应的配置信息'''
        for config in self.networkconfigs:
            if config.get("name") == iface_name:
                return config
        return None

    def dhcp_entry_state(self):
        '''根据 DHCP 选择框设置输入框状态'''
        if self.dhcp_cb['var'].get() == "是":
            # 禁用手动输入
            self.ip_entry['entry'].config(state='disabled')
            self.mask_entry['entry'].config(state='disabled')
            self.gw_entry['entry'].config(state='disabled')
        else:
            # 启用手动输入
            self.ip_entry['entry'].config(state='normal')
            self.mask_entry['entry'].config(state='normal')
            self.gw_entry['entry'].config(state='normal')

    def get_network_settings(self):
        '''获取当前输入的网卡配置信息'''
        self.networkconfig = {
            "name": re.sub(r"^(.*?(适配器))\s*", "", self.iface_cb['var'].get()).strip(),
            "ipv4": self.ip_entry['var'].get(),
            "netmask": self.mask_entry['var'].get(),
            "gateway": self.gw_entry['var'].get(),
            #"dns1": self.dns1_entry['var'].get(),
            #"dns2": self.dns2_entry['var'].get(),
            "dhcp_enabled": self.dhcp_cb['var'].get() == "是"
        }

    def output_network_settings(self):
        '''输出当前网卡配置信息到日志框'''
        self.result_box.insert(tk.END, f"当前网卡配置：\n")
        for key, value in self.networkconfig.items():
            self.result_box.insert(tk.END, f"  {key}: {value}\n")
        self.result_box.see(tk.END)

    def apply_btn_callback(self):
        '''应用当前网卡配置信息'''
        self.get_network_settings()
        self.netmgr.set_network_info(self.networkconfig)
        #self.refresh_allnetwork()