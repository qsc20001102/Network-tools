import subprocess
import re

class NetworkManager:
    """获取并设置本机网络适配器信息（Windows）"""

    def get_all_adapters(self):
        """返回本机所有网卡信息列表，每个网卡是字典"""
        result = subprocess.run("ipconfig /all", capture_output=True, text=True, shell=True)
        lines = result.stdout.splitlines()
        
        adapters = []
        adapter = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 匹配网卡名称
            m = re.match(r'(?:以太网适配器|无线局域网适配器|未知适配器|Ethernet|Wi-Fi|Adapter)\s*(.+):', line)
            if m:
                if adapter:
                    adapters.append(adapter)
                adapter = {
                    'name': m.group(1),
                    'ip': '',
                    'mask': '',
                    'gateway': '',
                    'dns1': '',
                    'dns2': '',
                    'dhcp': '',
                    'media': '',
                    'desc': ''
                }
                continue

            if adapter is None:
                continue

            # 解析字段
            if "IPv4 地址" in line or "IPv4 Address" in line:
                adapter['ip'] = line.split(':')[-1].strip().split('(')[0]
            elif "子网掩码" in line or "Subnet Mask" in line:
                adapter['mask'] = line.split(':')[-1].strip()
            elif "默认网关" in line or "Default Gateway" in line:
                if not adapter['gateway']:
                    adapter['gateway'] = line.split(':')[-1].strip()
            elif "DHCP 已启用" in line or "DHCP Enabled" in line:
                adapter['dhcp'] = line.split(':')[-1].strip()
            elif "媒体状态" in line or "Media State" in line:
                adapter['media'] = line.split(':')[-1].strip()
            elif "描述" in line or "Description" in line:
                adapter['desc'] = line.split(':')[-1].strip()
            elif "DNS 服务器" in line or "DNS Servers" in line:
                dns = line.split(':')[-1].strip()
                if not adapter['dns1']:
                    adapter['dns1'] = dns
                elif not adapter['dns2']:
                    adapter['dns2'] = dns

        if adapter:
            adapters.append(adapter)

        return adapters

    def set_static_ip(self, name, ip, mask, gateway):
        """设置静态 IP"""
        cmd = f'netsh interface ip set address name="{name}" static {ip} {mask} {gateway} 1'
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="gbk").stdout

    def set_dhcp(self, name):
        """切换 DHCP"""
        cmd1 = f'netsh interface ip set address name="{name}" dhcp'
        cmd2 = f'netsh interface ip set dns name="{name}" dhcp'
        out1 = subprocess.run(cmd1, shell=True, capture_output=True, text=True, encoding="gbk").stdout
        out2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True, encoding="gbk").stdout
        return out1 + "\n" + out2

    def set_dns(self, name, dns1, dns2=None):
        """设置 DNS"""
        cmd1 = f'netsh interface ip set dns name="{name}" static {dns1} primary'
        out = subprocess.run(cmd1, shell=True, capture_output=True, text=True, encoding="gbk").stdout
        if dns2:
            cmd2 = f'netsh interface ip add dns name="{name}" {dns2} index=2'
            out += subprocess.run(cmd2, shell=True, capture_output=True, text=True, encoding="gbk").stdout
        return out
