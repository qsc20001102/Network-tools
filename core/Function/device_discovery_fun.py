import concurrent.futures
import csv
import ipaddress
import json
import unicodedata
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from core.Function.common import run_hidden
from core.Function.loop_fun import normalize_mac
from core.Function.network_fun import NetworkManager
from core.Function.oui_lookup import OuiVendorLookup


OutputCallback = Callable[[str, Optional[str]], None]
DoneCallback = Callable[[], None]
StatusCallback = Callable[[dict], None]
ResultCallback = Callable[[dict], None]


ALL_ADAPTERS = "全部活动网卡"


OUI_VENDOR_MAP = {
    "00-05-69": "VMware",
    "00-0C-29": "VMware",
    "00-1C-14": "VMware",
    "00-50-56": "VMware",
    "00-15-5D": "Microsoft Hyper-V",
    "00-03-FF": "Microsoft",
    "00-1A-A0": "Dell",
    "00-1B-21": "Intel",
    "00-1E-67": "Intel",
    "00-21-5C": "Intel",
    "00-24-D7": "Intel",
    "3C-A8-2A": "Intel",
    "48-7D-2E": "TP-Link",
    "50-C7-BF": "TP-Link",
    "60-E3-27": "TP-Link",
    "A0-F3-C1": "TP-Link",
    "B0-A7-B9": "TP-Link",
    "D8-07-B6": "TP-Link",
    "00-1D-0F": "Cisco",
    "00-22-BD": "Cisco",
    "00-25-9C": "Cisco",
    "A4-18-75": "Cisco",
    "F4-4E-05": "Cisco",
    "00-16-EA": "HPE",
    "00-1F-29": "HPE",
    "3C-A8-2A": "HPE/Intel",
    "00-1E-C2": "Apple",
    "00-25-00": "Apple",
    "3C-15-C2": "Apple",
    "7C-D1-C3": "Apple",
    "A4-C3-F0": "Apple",
    "F0-18-98": "Apple",
    "18-C0-4D": "Realtek",
    "52-54-00": "QEMU/KVM",
    "08-00-27": "VirtualBox",
    "BC-24-11": "Proxmox/QEMU",
}


OUI_LOOKUP = OuiVendorLookup(OUI_VENDOR_MAP)


@dataclass
class DeviceDiscoveryOptions:
    scan_range: str = ""
    workers: int = 64
    timeout_ms: int = 500
    max_hosts: int = 254


@dataclass
class DeviceInfo:
    ip: str
    mac: str
    vendor: str
    adapter: str
    interface_index: str
    latency_ms: float = 0.0
    method: str = "ARP 可见"
    note: str = ""
    checked_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["latency_ms"] = round(self.latency_ms, 1)
        return data


class DeviceDiscovery:
    def __init__(
        self,
        output: OutputCallback,
        done: Optional[DoneCallback] = None,
        status: Optional[StatusCallback] = None,
        result: Optional[ResultCallback] = None,
    ):
        self.output = output
        self.done = done or (lambda: None)
        self.status = status or (lambda _stats: None)
        self.result = result or (lambda _row: None)
        self.network = NetworkManager(lambda _text, _tag=None: None)
        self.stop_event = threading.Event()
        self.worker = None
        self.last_results: list[dict] = []
        self.last_summary = ""
        OUI_LOOKUP.load(self.output)
        OUI_LOOKUP.update_if_stale_async(self.output)

    def get_adapter_choices(self) -> list[str]:
        adapters = self._active_adapters(self.network.get_network_info())
        return [ALL_ADAPTERS] + [adapter["name"] for adapter in adapters]

    def get_adapter_choices_and_default_range(self) -> tuple[list[str], str, str]:
        adapters = self._active_adapters(self.network.get_network_info())
        choices = [ALL_ADAPTERS] + [adapter["name"] for adapter in adapters]
        default_adapter = preferred_discovery_adapter(adapters)
        return choices, adapter_to_safe_range(default_adapter) if default_adapter else "", default_adapter.get("name", "") if default_adapter else ""

    def default_scan_range(self, adapter_name: str = ALL_ADAPTERS) -> str:
        adapters = self._select_adapters(adapter_name)
        if not adapters:
            return ""
        return adapter_to_safe_range(adapters[0])

    def start_discovery(self, adapter_name: str = ALL_ADAPTERS, options: Optional[dict] = None) -> None:
        if self.is_running():
            raise RuntimeError("设备发现正在运行，请先停止当前任务")

        discovery_options = self.normalize_options(options)
        adapters = self._select_adapters(adapter_name)
        if not adapters:
            raise ValueError("没有找到可扫描的活动网卡")

        targets = self.build_scan_targets(adapters, discovery_options)
        if not targets:
            raise ValueError("没有可扫描的目标地址")

        self.stop_event.clear()
        self.last_results = []
        self.last_summary = ""
        self.output(
            f"开始局域网设备发现: {adapter_name or ALL_ADAPTERS}，"
            f"目标 {len(targets)} 个，并发 {min(discovery_options.workers, 24, max(1, len(targets)))}，超时 {discovery_options.timeout_ms}ms\n",
            "muted",
        )
        self.status(self._status("扫描中", adapter_name or ALL_ADAPTERS, describe_targets(targets), len(targets), 0, 0, 0))
        self.worker = threading.Thread(target=self._run_discovery, args=(adapters, targets, discovery_options), daemon=True)
        self.worker.start()

    def _run_discovery(self, adapters: list[dict], targets: list[str], options: DeviceDiscoveryOptions) -> None:
        started = time.perf_counter()
        ping_results: dict[str, dict] = {}

        try:
            ping_results = self.scan_targets(targets, options, started)
            neighbors = self.get_neighbors()
            devices = self.build_devices(adapters, targets, ping_results, neighbors)

            for index, device in enumerate(sorted(devices, key=lambda item: ip_sort_key(item.ip)), start=1):
                if self.stop_event.is_set():
                    break
                row = device.to_dict()
                self.last_results.append(row)
                self.result(row)
                self.status(
                    self._status(
                        "汇总中",
                        device.adapter,
                        describe_targets(targets),
                        len(targets),
                        len(targets),
                        index,
                        time.perf_counter() - started,
                    )
                )

            self.last_summary = build_summary(self.last_results, stopped=self.stop_event.is_set())
            if self.stop_event.is_set():
                self.output("\n设备发现已停止\n", "warning")
            else:
                self.output("\n设备发现完成\n", "success")
            self.output(self.last_summary + "\n", "success")
            self.status(
                self._status(
                    "已停止" if self.stop_event.is_set() else "已完成",
                    "",
                    describe_targets(targets),
                    len(targets),
                    len(targets),
                    len(self.last_results),
                    time.perf_counter() - started,
                )
            )
        except Exception as exc:
            self.output(f"\n设备发现失败: {exc}\n", "error")
            self.status(self._status("失败", "", describe_targets(targets), len(targets), len(ping_results), 0, time.perf_counter() - started))
        finally:
            self.done()

    def scan_targets(self, targets: list[str], options: DeviceDiscoveryOptions, started: float) -> dict[str, dict]:
        results = {}
        completed = 0
        workers = min(options.workers, 24, max(1, len(targets)))

        def task(ip: str) -> dict:
            if self.stop_event.is_set():
                return {"ip": ip, "ok": False, "rtt": 0.0}
            return ping_once(ip, options.timeout_ms)

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(task, ip): ip for ip in targets}
            for future in concurrent.futures.as_completed(futures):
                completed += 1
                ip = futures[future]
                if self.stop_event.is_set():
                    for item in futures:
                        item.cancel()
                    break
                try:
                    result = future.result()
                except Exception:
                    result = {"ip": ip, "ok": False, "rtt": 0.0}
                results[ip] = result
                if completed % 20 == 0 or completed == len(targets):
                    self.status(self._status("扫描中", ip, describe_targets(targets), len(targets), completed, 0, time.perf_counter() - started))
        return results

    def build_devices(
        self,
        adapters: list[dict],
        targets: list[str],
        ping_results: dict[str, dict],
        neighbors: list[dict],
    ) -> list[DeviceInfo]:
        adapter_by_index = {str(adapter.get("interface_index", "")): adapter for adapter in adapters}
        adapter_by_ip = {adapter.get("ipv4", ""): adapter for adapter in adapters}
        target_set = set(targets)
        local_ips = {adapter.get("ipv4", "") for adapter in adapters}
        gateways = {adapter.get("gateway", "") for adapter in adapters if adapter.get("gateway")}
        devices: dict[str, DeviceInfo] = {}

        for adapter in adapters:
            local_ip = adapter.get("ipv4", "")
            if not local_ip:
                continue
            devices[local_ip] = DeviceInfo(
                ip=local_ip,
                mac=normalize_mac(adapter.get("mac", "")),
                vendor=vendor_name(adapter.get("mac", "")),
                adapter=adapter.get("name", ""),
                interface_index=str(adapter.get("interface_index", "")),
                latency_ms=ping_results.get(local_ip, {}).get("rtt", 0.0),
                method="在线" if ping_results.get(local_ip, {}).get("ok") else "本机",
                note="本机",
            )

        for item in neighbors:
            ip = item.get("ip", "")
            mac = normalize_mac(item.get("mac", ""))
            if ip not in target_set and ip not in gateways and ip not in local_ips:
                continue
            if not is_valid_device_mac(mac) or is_multicast_or_broadcast_ip(ip):
                continue
            adapter = adapter_by_index.get(str(item.get("ifIndex", ""))) or adapter_by_ip.get(item.get("interface_ip", "")) or adapter_for_ip(ip, adapters)
            if not adapter:
                continue
            ping = ping_results.get(ip, {})
            method = "在线" if ping.get("ok") else "ARP 可见"
            note = []
            if ip in local_ips:
                note.append("本机")
            if ip in gateways:
                note.append("网关")
            devices[ip] = DeviceInfo(
                ip=ip,
                mac=mac,
                vendor=vendor_name(mac),
                adapter=adapter.get("name", ""),
                interface_index=str(adapter.get("interface_index", "")),
                latency_ms=ping.get("rtt", 0.0),
                method=method,
                note="; ".join(note),
            )

        for ip, ping in ping_results.items():
            if not ping.get("ok") or ip in devices:
                continue
            adapter = adapter_for_ip(ip, adapters)
            if not adapter:
                continue
            devices[ip] = DeviceInfo(
                ip=ip,
                mac="",
                vendor="未知",
                adapter=adapter.get("name", ""),
                interface_index=str(adapter.get("interface_index", "")),
                latency_ms=ping.get("rtt", 0.0),
                method="在线",
                note="网关" if ip in gateways else "本机" if ip in local_ips else "未读取到 MAC",
            )

        return list(devices.values())

    def get_neighbors(self) -> list[dict]:
        script = r"""
$ErrorActionPreference = "SilentlyContinue"
Get-NetNeighbor -AddressFamily IPv4 | Select-Object ifIndex,IPAddress,LinkLayerAddress,State | ConvertTo-Json -Depth 4 -Compress
"""
        try:
            result = run_hidden(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=10)
            if result.returncode != 0:
                raise RuntimeError(result.stdout.strip())
            data = extract_json(result.stdout)
            if isinstance(data, dict):
                data = [data]
            return [normalize_neighbor(item) for item in data]
        except Exception as exc:
            self.output(f"PowerShell 邻居表读取失败，尝试 arp -a: {exc}\n", "warning")
            return self.get_neighbors_from_arp()

    def get_neighbors_from_arp(self) -> list[dict]:
        result = run_hidden(["arp", "-a"], timeout=10)
        if result.returncode != 0:
            return []
        neighbors = []
        current_interface = ""
        for line in result.stdout.splitlines():
            header = re.search(r"Interface:\s+([^\s]+)", line, re.IGNORECASE)
            if header:
                current_interface = header.group(1)
                continue
            match = re.match(r"\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]+)\s+(\w+)", line)
            if match:
                neighbors.append(
                    {
                        "ifIndex": "",
                        "interface_ip": current_interface,
                        "ip": match.group(1),
                        "mac": normalize_mac(match.group(2)),
                        "state": match.group(3),
                    }
                )
        return neighbors

    def build_scan_targets(self, adapters: list[dict], options: DeviceDiscoveryOptions) -> list[str]:
        if options.scan_range:
            return filter_targets_for_adapters(parse_target_range(options.scan_range, options.max_hosts), adapters)
        targets = []
        for adapter in adapters:
            targets.extend(parse_target_range(adapter_to_safe_range(adapter), options.max_hosts))
        return list(dict.fromkeys(targets))[: options.max_hosts]

    def stop_discovery(self) -> None:
        if not self.is_running():
            raise RuntimeError("当前没有正在运行的设备发现")
        self.stop_event.set()
        self.output("\n正在停止设备发现...\n", "warning")

    def export_results(self, path: str) -> None:
        if not self.last_results:
            raise RuntimeError("还没有可导出的设备发现结果")
        fields = ["ip", "mac", "vendor", "adapter", "interface_index", "latency_ms", "method", "note", "checked_at"]
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for row in self.last_results:
                writer.writerow({field_name: row.get(field_name, "") for field_name in fields})

    def copy_summary(self) -> str:
        if not self.last_results:
            return self.last_summary
        return "\n".join(
            f"{row.get('ip', '')}\t{row.get('mac', '')}\t{row.get('vendor', '')}\t{row.get('method', '')}"
            for row in sorted(self.last_results, key=lambda item: ip_sort_key(item.get("ip", "")))
        )

    def normalize_options(self, options: Optional[dict]) -> DeviceDiscoveryOptions:
        options = options or {}
        return DeviceDiscoveryOptions(
            scan_range=str(options.get("scan_range", "")).strip(),
            workers=clamp_int(options.get("workers", 64), 1, 256, "并发数"),
            timeout_ms=clamp_int(options.get("timeout_ms", 500), 100, 10000, "超时"),
            max_hosts=clamp_int(options.get("max_hosts", 254), 1, 254, "最大扫描地址数"),
        )

    def _select_adapters(self, adapter_name: str) -> list[dict]:
        adapters = self._active_adapters(self.network.get_network_info())
        if not adapter_name or adapter_name == ALL_ADAPTERS:
            return adapters
        selected = normalize_adapter_name(adapter_name)
        return [adapter for adapter in adapters if normalize_adapter_name(adapter.get("name", "")) == selected]

    def _active_adapters(self, adapters: list[dict]) -> list[dict]:
        active = []
        for adapter in adapters:
            if not adapter.get("ipv4"):
                continue
            status = str(adapter.get("status", "")).lower()
            if any(value in status for value in ("disconnect", "disabled", "not present", "断开", "禁用")):
                continue
            active.append(adapter)
        return active

    def _status(self, state: str, current: str, scan_range: str, total: int, scanned: int, found: int, elapsed: float) -> dict:
        return {
            "state": state,
            "current": current,
            "scan_range": scan_range,
            "total": total,
            "scanned": scanned,
            "found": found,
            "elapsed": elapsed,
        }

    def is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())


def ping_once(ip: str, timeout_ms: int) -> dict:
    try:
        result = run_hidden(["ping", ip, "-n", "1", "-w", str(timeout_ms)], timeout=max(1.2, timeout_ms / 1000 + 0.8))
        output = result.stdout
        if re.search(r"\bTTL=", output, re.IGNORECASE):
            match = re.search(r"(?:time|时间)[=<]?\s*(\d+(?:\.\d+)?)\s*(?:ms|毫秒)", output, re.IGNORECASE)
            return {"ip": ip, "ok": True, "rtt": float(match.group(1)) if match else 0.0}
    except Exception:
        pass
    return {"ip": ip, "ok": False, "rtt": 0.0}


def parse_target_range(text: str, max_hosts: int = 254) -> list[str]:
    raw = text.strip()
    if not raw:
        return []
    targets = []
    for part in re.split(r"[,，;\s]+", raw):
        item = part.strip()
        if not item:
            continue
        if "/" in item:
            network = ipaddress.ip_network(item, strict=False)
            targets.extend(str(ip) for ip in network.hosts())
        elif re.match(r"^\d{1,3}(?:\.\d{1,3}){3}-\d{1,3}$", item):
            prefix, tail = item.rsplit(".", 1)
            start_text, end_text = tail.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise ValueError("IP 范围起始值不能大于结束值")
            targets.extend(str(ipaddress.ip_address(f"{prefix}.{value}")) for value in range(start, end + 1))
        elif re.match(r"^\d{1,3}(?:\.\d{1,3}){3}-\d{1,3}(?:\.\d{1,3}){3}$", item):
            start_text, end_text = item.split("-", 1)
            start_ip = ipaddress.ip_address(start_text)
            end_ip = ipaddress.ip_address(end_text)
            if start_ip.version != end_ip.version:
                raise ValueError("IP 范围两端必须是同一 IP 版本")
            if int(start_ip) > int(end_ip):
                raise ValueError("IP 范围起始值不能大于结束值")
            targets.extend(str(ipaddress.ip_address(value)) for value in range(int(start_ip), int(end_ip) + 1))
        else:
            targets.append(str(ipaddress.ip_address(item)))
    return list(dict.fromkeys(targets))[:max_hosts]


def adapter_to_safe_range(adapter: dict) -> str:
    ip = adapter.get("ipv4", "")
    if not ip:
        return ""
    prefix = adapter.get("prefix_length")
    if prefix in ("", None):
        prefix = netmask_to_prefix(adapter.get("netmask", "")) or 24
    try:
        prefix = int(prefix)
        if prefix < 24:
            prefix = 24
        return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))
    except Exception:
        parts = ip.split(".")
        return ".".join(parts[:3]) + ".0/24" if len(parts) == 4 else ""


def preferred_discovery_adapter(adapters: list[dict]) -> Optional[dict]:
    if not adapters:
        return None
    for adapter in adapters:
        if adapter.get("gateway"):
            return adapter
    for adapter in adapters:
        prefix = adapter.get("prefix_length")
        try:
            if prefix not in ("", None) and int(prefix) <= 24:
                return adapter
        except (TypeError, ValueError):
            continue
    return adapters[0]


def filter_targets_for_adapters(targets: list[str], adapters: list[dict]) -> list[str]:
    return [target for target in targets if target_in_adapter_network(target, adapters)]


def target_in_adapter_network(target: str, adapters: list[dict]) -> bool:
    try:
        address = ipaddress.ip_address(target)
    except ValueError:
        return False
    for adapter in adapters:
        local_ip = adapter.get("ipv4", "")
        if not local_ip:
            continue
        prefix = adapter.get("prefix_length") or netmask_to_prefix(adapter.get("netmask", "")) or 24
        try:
            if address in ipaddress.ip_network(f"{local_ip}/{prefix}", strict=False):
                return True
        except Exception:
            continue
    return False


def normalize_adapter_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"[\s\u200b-\u200d\ufeff]+", " ", normalized).strip().casefold()


def netmask_to_prefix(netmask: str) -> Optional[int]:
    if not netmask:
        return None
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen
    except Exception:
        return None


def normalize_neighbor(item: dict) -> dict:
    return {
        "ifIndex": str(item.get("ifIndex", "")),
        "interface_ip": "",
        "ip": str(item.get("IPAddress", "")),
        "mac": normalize_mac(item.get("LinkLayerAddress", "")),
        "state": str(item.get("State", "")),
    }


def vendor_name(mac: str) -> str:
    return OUI_LOOKUP.lookup(mac)


def build_summary(rows: list[dict], stopped: bool = False) -> str:
    if stopped:
        return "设备发现已停止，当前结果仅代表已完成扫描。"
    if not rows:
        return "未发现有效局域网设备。"
    online = len([row for row in rows if row.get("method") == "在线"])
    arp = len([row for row in rows if row.get("method") == "ARP 可见"])
    gateway = len([row for row in rows if "网关" in row.get("note", "")])
    local = len([row for row in rows if "本机" in row.get("note", "")])
    vendors = sorted({row.get("vendor", "未知") for row in rows if row.get("vendor") and row.get("vendor") != "未知"})
    lines = [
        "==== 局域网设备发现摘要 ====",
        f"发现设备: {len(rows)}  在线: {online}  ARP 可见: {arp}  本机: {local}  网关: {gateway}",
    ]
    if vendors:
        lines.append("识别厂商: " + ", ".join(vendors[:8]))
    else:
        lines.append("未识别到已知厂商，可能需要后续扩展 OUI 数据。")
    return "\n".join(lines)


def describe_targets(targets: list[str]) -> str:
    if not targets:
        return ""
    if len(targets) == 1:
        return targets[0]
    return f"{targets[0]} - {targets[-1]}"


def adapter_for_ip(ip: str, adapters: list[dict]) -> Optional[dict]:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None
    for adapter in adapters:
        local_ip = adapter.get("ipv4", "")
        if not local_ip:
            continue
        prefix = adapter.get("prefix_length") or netmask_to_prefix(adapter.get("netmask", "")) or 24
        try:
            network = ipaddress.ip_network(f"{local_ip}/{prefix}", strict=False)
            if address in network:
                return adapter
        except Exception:
            continue
    return adapters[0] if adapters else None


def is_valid_device_mac(mac: str) -> bool:
    normalized = normalize_mac(mac)
    if not normalized or normalized == "00-00-00-00-00-00":
        return False
    if normalized.startswith("FF-FF-FF") or normalized.startswith("01-00-5E"):
        return False
    return bool(re.match(r"^[0-9A-F]{2}(?:-[0-9A-F]{2}){5}$", normalized))


def is_multicast_or_broadcast_ip(ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(ip)
        return parsed.is_multicast or str(parsed).endswith(".255") or str(parsed) == "255.255.255.255"
    except ValueError:
        return True


def ip_sort_key(value: str) -> tuple:
    try:
        return (0, int(ipaddress.ip_address(value)))
    except ValueError:
        return (1, value)


def extract_json(text: str):
    output = text.strip()
    json_start = min([idx for idx in (output.find("["), output.find("{")) if idx >= 0], default=-1)
    if json_start < 0:
        raise RuntimeError("未获取到 JSON 输出")
    data = json.loads(output[json_start:])
    return [] if data is None else data


def clamp_int(value, min_value: int, max_value: int, label: str) -> int:
    try:
        number = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if number < min_value or number > max_value:
        raise ValueError(f"{label}必须在 {min_value}-{max_value} 之间")
    return number
