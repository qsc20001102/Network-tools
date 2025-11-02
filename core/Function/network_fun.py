import subprocess
import locale
import re
import tkinter as tk
from tkinter import scrolledtext, messagebox

import logging


class NetworkManager:
    """获取本地网卡详细信息（含 DNS、DHCP）"""
    def __init__(self, result_box: scrolledtext.ScrolledText):
        self.result_box = result_box

    def get_network_info(self):
        # 自动获取系统编码（例如 'cp936' 中文Windows）
        system_encoding = locale.getpreferredencoding(False)
        
        # 调用 ipconfig /all
        result = subprocess.run(
            "ipconfig /all",
            shell=True,
            capture_output=True,
            text=True,
            encoding=system_encoding,  # 自动根据系统语言选择
            errors="ignore"            # 忽略解码错误
        )

        output = result.stdout
        if not output:
            raise RuntimeError("无法获取 ipconfig 输出，请检查系统命令执行权限。")

        # 按块拆分
        import re
        adapter_blocks = re.split(r"\r?\n(?=\S.*?:)", output)

        adapters = []
        for block in adapter_blocks:
            if not re.search(r"适配器", block):
                continue

            info = {}
            match = re.match(r"(.+?):", block)
            if match:
                info["name"] = match.group(1).strip()

            match = re.search(r"描述.*?:\s*(.+)", block)
            if match:
                info["description"] = match.group(1).strip()

            match = re.search(r"物理地址.*?:\s*(.+)", block)
            if match:
                info["mac"] = match.group(1).strip()

            match = re.search(r"DHCP 已启用.*?:\s*(.+)", block)
            if match:
                value = match.group(1).strip()
                info["dhcp_enabled"] = "是" if value == "是" else "否"

            match = re.search(r"IPv4 地址.*?:\s*([0-9.]+)", block)
            if match:
                info["ipv4"] = match.group(1)

            match = re.search(r"子网掩码.*?:\s*([0-9.]+)", block)
            if match:
                info["netmask"] = match.group(1)

            gateway = ""
            # 先找出 "默认网关" 所在行及后续可能的下一行
            gw_match = re.search(r"默认网关[.\s:]*([^\r\n]*)\r?\n(?:\s*([^\r\n]+))?", block)
            if gw_match:
                # 合并两行文本
                gw_text = " ".join(gw_match.groups(default=""))
                # 提取 IPv4 地址
                ipv4_match = re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", gw_text)
                if ipv4_match:
                    gateway = ipv4_match.group(0)
            info["gateway"] = gateway

            # --- DNS 服务器提取（支持多行 + IPv4优先）---
            dns1 = dns2 = ""
            # 找出 “DNS 服务器” 开始的位置
            dns_match = re.search(r"DNS 服务器[.\s:]*([^\r\n]*)((?:\r?\n\s+[^\r\n]+)*)", block)
            if dns_match:
                # 合并所有行
                dns_text = dns_match.group(1) + dns_match.group(2)
                # 提取所有 IPv4 地址（优先），如果没有，再取 IPv6
                dns_ipv4 = re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", dns_text)
                if dns_ipv4:
                    dns1 = dns_ipv4[0]
                    if len(dns_ipv4) > 1:
                        dns2 = dns_ipv4[1]
                else:
                    # 没有 IPv4，则尝试 IPv6
                    dns_ipv6 = re.findall(r"[a-fA-F0-9:]+(?:%[0-9]+)?", dns_text)
                    if dns_ipv6:
                        dns1 = dns_ipv6[0]
                        if len(dns_ipv6) > 1:
                            dns2 = dns_ipv6[1]

            info["dns1"] = dns1
            info["dns2"] = dns2

            adapters.append(info)
        return adapters
    
    def set_network_info(self, settings):
        """设置指定网卡的网络配置"""
        try:
            self.result_box.insert(tk.END, f"尝试将网卡配置修改为：\n")
            for key, value in settings.items():
                self.result_box.insert(tk.END, f"  {key}: {value}\n")  
            if settings['dhcp_enabled']:
                # 启用 DHCP 自动获取 IP 地址
                subprocess.run(
                    f'netsh interface ip set address name="{settings['name']}" source=dhcp',
                    shell=True, check=True
                )
            else:
                subprocess.run(
                    f'netsh interface ip set address name="{settings['name']}" source=static addr={settings['ipv4']} mask={settings['netmask']} gateway={settings['gateway']}', 
                    shell=True, check=True)
            self.result_box.insert(tk.END, f"网络配置设置完成\n")

        except subprocess.CalledProcessError as e:
            self.result_box.insert(tk.END, f"设置{settings['name']}网络配置失败: {e}\n")
        self.result_box.see(tk.END)