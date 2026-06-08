import json
import os
import re
import subprocess
import sys
from typing import Callable, Optional

from core.Function.common import preferred_encoding, prefix_to_netmask, run_hidden, validate_ip


OutputCallback = Callable[[str, Optional[str]], None]


class NetworkManager:
    def __init__(self, output: OutputCallback):
        self.output = output
        self.profiles_file = os.path.join(self._base_dir(), "network_profiles.json")

    def _base_dir(self) -> str:
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def get_network_info(self) -> list[dict]:
        script = r"""
$ErrorActionPreference = "SilentlyContinue"
$ipconfigs = @{}
Get-NetIPConfiguration | ForEach-Object { $ipconfigs[[string]$_.InterfaceIndex] = $_ }

$ipifs = @{}
Get-NetIPInterface -AddressFamily IPv4 | ForEach-Object {
    $key = [string]$_.InterfaceIndex
    if (-not $ipifs.ContainsKey($key)) { $ipifs[$key] = $_ }
}

$cims = @{}
Get-CimInstance Win32_NetworkAdapterConfiguration | ForEach-Object {
    if ($_.InterfaceIndex -ne $null) { $cims[[string]$_.InterfaceIndex] = $_ }
}

$dnsMap = @{}
Get-DnsClientServerAddress -AddressFamily IPv4 | ForEach-Object {
    $dnsMap[[string]$_.InterfaceIndex] = @($_.ServerAddresses)
}

$items = Get-NetAdapter | Sort-Object Name | ForEach-Object {
    $adapter = $_
    $alias = $adapter.Name
    $index = $adapter.ifIndex
    $key = [string]$index
    $ipconfig = $ipconfigs[$key]
    $ipif = $ipifs[$key]
    $cim = $cims[$key]
    $dns = @($dnsMap[$key])
    [PSCustomObject]@{
        name = $alias
        description = $adapter.InterfaceDescription
        mac = $adapter.MacAddress
        status = [string]$adapter.Status
        link_speed = [string]$adapter.LinkSpeed
        interface_index = $index
        ipv4 = @($ipconfig.IPv4Address | Select-Object -ExpandProperty IPAddress)[0]
        ipv6 = @($ipconfig.IPv6Address | Select-Object -ExpandProperty IPAddress)
        prefix_length = @($ipconfig.IPv4Address | Select-Object -ExpandProperty PrefixLength)[0]
        gateway = @($ipconfig.IPv4DefaultGateway | Select-Object -ExpandProperty NextHop)[0]
        dns = $dns
        dhcp_server = if ($cim) { $cim.DHCPServer } else { "" }
        dhcp_lease_obtained = if ($cim) { [string]$cim.DHCPLeaseObtained } else { "" }
        dhcp_lease_expires = if ($cim) { [string]$cim.DHCPLeaseExpires } else { "" }
        dhcp_enabled = if ($ipif) { [string]$ipif.Dhcp -eq "Enabled" } elseif ($cim) { [bool]$cim.DHCPEnabled } else { $false }
    }
}
$items | ConvertTo-Json -Depth 5 -Compress
"""
        result = run_hidden(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=30)
        if result.returncode != 0:
            raise RuntimeError(result.stdout.strip() or "PowerShell 获取网卡信息失败")

        output = result.stdout.strip()
        json_start = min([idx for idx in (output.find("["), output.find("{")) if idx >= 0], default=-1)
        if json_start < 0:
            return self._get_network_info_from_ipconfig()

        data = json.loads(output[json_start:])
        if data is None:
            return []
        if isinstance(data, dict):
            data = [data]

        adapters = []
        for item in data:
            dns = item.get("dns") or []
            if isinstance(dns, str):
                dns = [dns]
            ipv6 = item.get("ipv6") or []
            if isinstance(ipv6, str):
                ipv6 = [ipv6]
            adapters.append(
                {
                    "name": item.get("name") or "",
                    "description": item.get("description") or "",
                    "mac": item.get("mac") or "",
                    "status": item.get("status") or "",
                    "link_speed": item.get("link_speed") or "",
                    "interface_index": item.get("interface_index") or "",
                    "ipv4": item.get("ipv4") or "",
                    "ipv6": ipv6,
                    "prefix_length": item.get("prefix_length") or "",
                    "netmask": prefix_to_netmask(item.get("prefix_length")),
                    "gateway": item.get("gateway") or "",
                    "dns1": dns[0] if len(dns) > 0 else "",
                    "dns2": dns[1] if len(dns) > 1 else "",
                    "dhcp_server": item.get("dhcp_server") or "",
                    "dhcp_lease_obtained": item.get("dhcp_lease_obtained") or "",
                    "dhcp_lease_expires": item.get("dhcp_lease_expires") or "",
                    "dhcp_enabled": bool(item.get("dhcp_enabled")),
                }
            )
        return sorted(adapters, key=lambda value: value["name"])

    def _get_network_info_from_ipconfig(self) -> list[dict]:
        result = run_hidden(["ipconfig", "/all"], timeout=15)
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(result.stdout.strip() or "无法读取 ipconfig /all 输出")

        adapters = []
        current = None
        last_key = None
        header_pattern = re.compile(r"^(?:\S.* adapter|.+适配器)\s+(.+):$")
        unknown_header_pattern = re.compile(r"^(?:Unknown adapter|未知适配器)\s+(.+):$")
        value_pattern = re.compile(r"^\s*([^:]+?)\s*:\s*(.*)$")

        def push_current():
            if current and current.get("name"):
                adapters.append(current.copy())

        for raw_line in result.stdout.splitlines():
            line = raw_line.rstrip()
            header = header_pattern.match(line) or unknown_header_pattern.match(line)
            if header:
                push_current()
                current = {
                    "name": header.group(1).strip(),
                    "description": "",
                    "mac": "",
                    "status": "Disconnected" if "Media disconnected" in line else "",
                    "link_speed": "",
                    "interface_index": "",
                    "ipv4": "",
                    "ipv6": [],
                    "prefix_length": "",
                    "netmask": "",
                    "gateway": "",
                    "dns1": "",
                    "dns2": "",
                    "dhcp_server": "",
                    "dhcp_lease_obtained": "",
                    "dhcp_lease_expires": "",
                    "dhcp_enabled": False,
                }
                last_key = None
                continue

            if current is None:
                continue

            if ("Media State" in line and "Media disconnected" in line) or ("媒体状态" in line and "媒体已断开连接" in line):
                current["status"] = "Disconnected"
                continue

            match = value_pattern.match(line)
            if match:
                key = match.group(1).replace(".", "").strip()
                value = self._clean_ipconfig_value(match.group(2))
                last_key = key
                self._assign_ipconfig_value(current, key, value)
                continue

            continuation = line.strip()
            if continuation and last_key == "DNS Servers":
                self._assign_ipconfig_value(current, last_key, self._clean_ipconfig_value(continuation))

        push_current()
        return sorted(adapters, key=lambda value: value["name"])

    def _assign_ipconfig_value(self, adapter: dict, key: str, value: str) -> None:
        if key == "Description":
            adapter["description"] = value
        elif key == "描述":
            adapter["description"] = value
        elif key == "Physical Address":
            adapter["mac"] = value
        elif key == "物理地址":
            adapter["mac"] = value
        elif key == "DHCP Enabled":
            adapter["dhcp_enabled"] = value.lower() == "yes" or value == "是"
        elif key == "DHCP 已启用":
            adapter["dhcp_enabled"] = value.lower() == "yes" or value == "是"
        elif key in ("IPv4 Address", "Autoconfiguration IPv4 Address"):
            adapter["ipv4"] = value
            if not adapter["status"]:
                adapter["status"] = "Up"
        elif key in ("IPv4 地址", "自动配置 IPv4 地址"):
            adapter["ipv4"] = value
            if not adapter["status"]:
                adapter["status"] = "Up"
        elif key == "Link-local IPv6 Address" or key == "IPv6 Address":
            if value:
                adapter["ipv6"].append(value)
        elif key == "本地链接 IPv6 地址" or key == "IPv6 地址":
            if value:
                adapter["ipv6"].append(value)
        elif key == "Subnet Mask":
            adapter["netmask"] = value
        elif key == "子网掩码":
            adapter["netmask"] = value
        elif key == "Default Gateway" and value:
            adapter["gateway"] = value
        elif key == "默认网关" and value:
            adapter["gateway"] = value
        elif key == "DNS Servers" and value:
            if not adapter["dns1"]:
                adapter["dns1"] = value
            elif not adapter["dns2"]:
                adapter["dns2"] = value
        elif key == "DNS 服务器" and value:
            if not adapter["dns1"]:
                adapter["dns1"] = value
            elif not adapter["dns2"]:
                adapter["dns2"] = value
        elif key == "DHCP Server":
            adapter["dhcp_server"] = value
        elif key == "DHCP 服务器":
            adapter["dhcp_server"] = value
        elif key == "Lease Obtained":
            adapter["dhcp_lease_obtained"] = value
        elif key == "获得租约的时间":
            adapter["dhcp_lease_obtained"] = value
        elif key == "Lease Expires":
            adapter["dhcp_lease_expires"] = value
        elif key == "租约过期的时间":
            adapter["dhcp_lease_expires"] = value

    def _clean_ipconfig_value(self, value: str) -> str:
        return re.sub(r"\s*\((?:Preferred|首选)\)\s*$", "", value.strip())

    def set_network_info(self, settings: dict) -> None:
        name = settings["name"].strip()
        if not name:
            raise ValueError("请选择网卡")

        self.output("准备应用网卡配置:\n", "muted")
        for key in ("name", "dhcp_enabled", "ipv4", "netmask", "gateway", "dns1", "dns2"):
            self.output(f"  {key}: {settings.get(key, '')}\n", "muted")

        if settings.get("dhcp_enabled"):
            self._run_netsh(["interface", "ip", "set", "address", f"name={name}", "source=dhcp"])
            self._run_netsh(["interface", "ip", "set", "dnsservers", f"name={name}", "source=dhcp"])
            self.output("已切换为 DHCP 自动获取\n", "success")
            return

        ipv4 = validate_ip(settings.get("ipv4", ""))
        netmask = validate_ip(settings.get("netmask", ""))
        gateway = validate_ip(settings.get("gateway", ""))
        self._run_netsh(
            [
                "interface",
                "ip",
                "set",
                "address",
                f"name={name}",
                "source=static",
                f"addr={ipv4}",
                f"mask={netmask}",
                f"gateway={gateway}",
            ]
        )

        dns1 = validate_ip(settings.get("dns1", ""), allow_empty=True)
        dns2 = validate_ip(settings.get("dns2", ""), allow_empty=True)
        if dns1:
            self._run_netsh(["interface", "ip", "set", "dnsservers", f"name={name}", "source=static", f"address={dns1}", "index=1"])
            if dns2:
                self._run_netsh(["interface", "ip", "add", "dnsservers", f"name={name}", f"address={dns2}", "index=2"])
        else:
            self._run_netsh(["interface", "ip", "set", "dnsservers", f"name={name}", "source=dhcp"])

        self.output("静态 IPv4 配置已应用\n", "success")

    def set_dns_servers(self, name: str, dns_servers: list[str]) -> None:
        adapter_name = name.strip()
        if not adapter_name:
            raise ValueError("请选择网卡")

        servers = [validate_ip(server) for server in dns_servers if str(server).strip()]
        if not servers:
            raise ValueError("请输入至少一个 DNS 服务器")

        self._run_netsh(
            [
                "interface",
                "ip",
                "set",
                "dnsservers",
                f"name={adapter_name}",
                "source=static",
                f"address={servers[0]}",
                "index=1",
            ]
        )
        for index, server in enumerate(servers[1:], start=2):
            self._run_netsh(["interface", "ip", "add", "dnsservers", f"name={adapter_name}", f"address={server}", f"index={index}"])
        self.output(f"已设置 DNS: {adapter_name} -> {', '.join(servers)}\n", "success")

    def flush_dns_cache(self) -> None:
        result = run_hidden(["ipconfig", "/flushdns"], timeout=10)
        if result.returncode != 0:
            raise RuntimeError(result.stdout.strip() or "刷新 DNS 缓存失败")
        self.output("已刷新 DNS 缓存\n", "success")

    def set_adapter_enabled(self, name: str, enabled: bool) -> None:
        adapter_name = name.strip()
        if not adapter_name:
            raise ValueError("请选择网卡")

        action = "启用" if enabled else "禁用"
        self.output(f"准备{action}网卡: {adapter_name}\n", "warning")
        command = "Enable-NetAdapter" if enabled else "Disable-NetAdapter"
        script = f"""
$ErrorActionPreference = "Stop"
{command} -Name {self._ps_quote(adapter_name)} -Confirm:$false
"""
        result = run_hidden(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=20)
        if result.returncode != 0:
            raise RuntimeError(result.stdout.strip() or f"{action}网卡失败，请确认已用管理员权限运行")
        self.output(f"网卡已{action}: {adapter_name}\n", "success")

    def load_profiles(self) -> dict:
        if not os.path.exists(self.profiles_file):
            return {}
        with open(self.profiles_file, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}

    def save_profile(self, profile_name: str, settings: dict) -> None:
        name = profile_name.strip()
        if not name:
            raise ValueError("请输入模板名称")
        profiles = self.load_profiles()
        profiles[name] = {
            "dhcp_enabled": bool(settings.get("dhcp_enabled")),
            "ipv4": settings.get("ipv4", ""),
            "netmask": settings.get("netmask", ""),
            "gateway": settings.get("gateway", ""),
            "dns1": settings.get("dns1", ""),
            "dns2": settings.get("dns2", ""),
        }
        self._write_profiles(profiles)

    def delete_profile(self, profile_name: str) -> None:
        profiles = self.load_profiles()
        if profile_name in profiles:
            del profiles[profile_name]
            self._write_profiles(profiles)

    def _write_profiles(self, profiles: dict) -> None:
        with open(self.profiles_file, "w", encoding="utf-8") as file:
            json.dump(profiles, file, ensure_ascii=False, indent=2)

    def _run_netsh(self, args: list[str]) -> None:
        command = ["netsh"] + args
        result = subprocess.run(command, capture_output=True, text=True, encoding=preferred_encoding(), errors="replace")
        if result.returncode != 0:
            message = (result.stdout + result.stderr).strip()
            raise RuntimeError(message or "netsh 命令执行失败，请确认已用管理员权限运行")

    def _ps_quote(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"
