import concurrent.futures
import csv
import ipaddress
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from core.Function.common import run_hidden
from core.Function.loop_fun import normalize_mac
from core.Function.network_fun import NetworkManager


OutputCallback = Callable[[str, Optional[str]], None]
DoneCallback = Callable[[], None]
StatusCallback = Callable[[dict], None]
ResultCallback = Callable[[dict], None]


ALL_ADAPTERS = "全部活动网卡"
MODE_BOTH = "两者都做"
MODE_LOCAL = "本机 IP 检测"
MODE_SUBNET = "网段扫描"


@dataclass
class IpConflictOptions:
    mode: str = MODE_BOTH
    scan_range: str = ""
    workers: int = 64
    timeout_ms: int = 500
    max_hosts: int = 254
    neighbor_samples: int = 3


@dataclass
class IpConflictEvidence:
    address_state: str = ""
    local_mac: str = ""
    observed_macs: list[str] = field(default_factory=list)
    conflict_macs: list[str] = field(default_factory=list)
    tcpip_event_count: int = 0
    gateway_mac_changes: int = 0
    ip_mac_changes: int = 0
    shared_mac_ips: int = 0
    scanned_hosts: int = 0
    notes: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["observed_macs"] = ", ".join(self.observed_macs)
        data["conflict_macs"] = ", ".join(self.conflict_macs)
        return data


@dataclass
class IpConflictResult:
    adapter: str
    ip: str
    mac: str
    conflict_macs: str
    evidence_type: str
    risk_level: str
    verdict: str
    evidence: IpConflictEvidence
    checked_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        data = {
            "adapter": self.adapter,
            "ip": self.ip,
            "mac": self.mac,
            "conflict_macs": self.conflict_macs,
            "evidence_type": self.evidence_type,
            "risk_level": self.risk_level,
            "verdict": self.verdict,
            "checked_at": self.checked_at,
        }
        data.update(self.evidence.to_dict())
        return data


class IpConflictDetector:
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

    def get_adapter_choices(self) -> list[str]:
        adapters = self._active_adapters(self.network.get_network_info())
        return [ALL_ADAPTERS] + [adapter["name"] for adapter in adapters]

    def default_scan_range(self, adapter_name: str = ALL_ADAPTERS) -> str:
        adapters = self._select_adapters(adapter_name)
        if not adapters:
            return ""
        return adapter_to_safe_range(adapters[0])

    def start_detection(self, adapter_name: str = ALL_ADAPTERS, options: Optional[dict] = None) -> None:
        if self.is_running():
            raise RuntimeError("IP 冲突检测正在运行，请先停止当前任务")

        conflict_options = self.normalize_options(options)
        adapters = self._select_adapters(adapter_name)
        if not adapters:
            raise ValueError("没有找到可检测的活动网卡")

        self.stop_event.clear()
        self.last_results = []
        self.last_summary = ""
        self.output(f"开始 IP 冲突检测: {adapter_name or ALL_ADAPTERS}，模式: {conflict_options.mode}\n", "muted")
        self.output("说明: 检测结果基于本机可见 ARP/邻居表、地址状态和系统事件，不替代交换机侧排查。\n\n", "muted")
        self.status(self._status("运行中", len(adapters), "", 0, 0, 0, 0))
        self.worker = threading.Thread(target=self._run_detection, args=(adapters, conflict_options), daemon=True)
        self.worker.start()

    def _run_detection(self, adapters: list[dict], options: IpConflictOptions) -> None:
        started = time.perf_counter()
        completed = 0
        max_risk = "正常"

        try:
            address_states = self.get_address_states()
            events = self.get_tcpip_conflict_events()
            neighbor_samples = [self.get_neighbors()]

            if options.mode in (MODE_BOTH, MODE_SUBNET):
                targets = self.build_scan_targets(adapters, options)
                self.output(f"准备刷新 ARP: {len(targets)} 个地址，并发 {options.workers}，超时 {options.timeout_ms}ms\n", "muted")
                self.status(self._status("扫描中", len(adapters), "", 0, len(targets), 0, time.perf_counter() - started))
                self.refresh_arp_targets(targets, options)
                neighbor_samples.append(self.get_neighbors())

            for _index in range(max(options.neighbor_samples - len(neighbor_samples), 0)):
                if self.stop_event.is_set():
                    break
                self.stop_event.wait(0.3)
                neighbor_samples.append(self.get_neighbors())

            rows = []
            for adapter in adapters:
                if self.stop_event.is_set():
                    break
                completed += 1
                self.status(self._status("分析中", len(adapters), adapter["name"], 0, 0, completed, time.perf_counter() - started))
                results = self.evaluate_adapter(adapter, address_states, events, neighbor_samples, options)
                if not results:
                    results = [normal_result(adapter, "未发现本机 IP 冲突证据")]
                for item in results:
                    row = item.to_dict()
                    rows.append(row)
                    self.last_results.append(row)
                    max_risk = worse_risk(max_risk, item.risk_level)
                    self.result(row)

            self.last_summary = build_summary(rows, stopped=self.stop_event.is_set())
            self.output("\nIP 冲突检测已停止\n" if self.stop_event.is_set() else "\nIP 冲突检测完成\n", "warning" if self.stop_event.is_set() else "success")
            self.output(self.last_summary + "\n", "success" if max_risk == "正常" else "warning")
            self.status(self._status("已停止" if self.stop_event.is_set() else "已完成", len(adapters), "", risk_rank(max_risk), 0, completed, time.perf_counter() - started))
        except Exception as exc:
            self.output(f"\nIP 冲突检测失败: {exc}\n", "error")
            self.status(self._status("失败", len(adapters), "", 0, 0, completed, time.perf_counter() - started))
        finally:
            self.done()

    def evaluate_adapter(
        self,
        adapter: dict,
        address_states: dict,
        events: list[dict],
        neighbor_samples: list[list[dict]],
        options: IpConflictOptions,
    ) -> list[IpConflictResult]:
        local_mac = normalize_mac(adapter.get("mac", ""))
        local_ip = adapter.get("ipv4", "")
        gateway = adapter.get("gateway", "")
        interface_index = str(adapter.get("interface_index", ""))
        local_neighbors = filter_neighbors(neighbor_samples, interface_index, local_ip)
        ip_to_macs, mac_to_ips = build_neighbor_maps(local_neighbors)
        results = []

        state = address_states.get(local_ip, "")
        event_hits = event_count_for_ip(events, local_ip)
        observed_macs = sorted(ip_to_macs.get(local_ip, set()))
        conflict_macs = sorted([mac for mac in observed_macs if local_mac and mac != local_mac and not is_special_mac(mac)])
        if state in {"Duplicate", "Tentative", "DadFailed"} or event_hits or conflict_macs:
            evidence = IpConflictEvidence(
                address_state=state,
                local_mac=local_mac,
                observed_macs=observed_macs,
                conflict_macs=conflict_macs,
                tcpip_event_count=event_hits,
                scanned_hosts=options.max_hosts,
                notes="本机 IP 冲突证据",
            )
            level = "冲突风险"
            reasons = []
            if state:
                reasons.append(f"地址状态 {state}")
            if event_hits:
                reasons.append(f"系统 Tcpip 冲突事件 {event_hits} 条")
            if conflict_macs:
                reasons.append("本机 IP 被其它 MAC 响应")
            results.append(
                IpConflictResult(
                    adapter=adapter["name"],
                    ip=local_ip,
                    mac=local_mac,
                    conflict_macs=", ".join(conflict_macs),
                    evidence_type="本机 IP",
                    risk_level=level,
                    verdict="疑似本机 IP 冲突，请检查是否有其它设备使用相同地址。证据: " + "、".join(reasons),
                    evidence=evidence,
                )
            )

        multi_mac_ips = sorted(ip for ip, macs in ip_to_macs.items() if len([mac for mac in macs if not is_special_mac(mac)]) > 1)
        for ip in multi_mac_ips:
            if ip in {local_ip, gateway}:
                continue
            macs = sorted(ip_to_macs[ip])
            evidence = IpConflictEvidence(
                local_mac=local_mac,
                observed_macs=macs,
                conflict_macs=macs,
                ip_mac_changes=1,
                scanned_hosts=options.max_hosts,
                notes="同一 IP 出现多个 MAC",
            )
            results.append(
                IpConflictResult(
                    adapter=adapter["name"],
                    ip=ip,
                    mac="",
                    conflict_macs=", ".join(macs),
                    evidence_type="网段 IP",
                    risk_level="冲突风险",
                    verdict="同一 IP 在邻居表中出现多个 MAC，疑似 IP 地址冲突。",
                    evidence=evidence,
                )
            )

        if gateway:
            gateway_macs = sorted(ip_to_macs.get(gateway, set()))
            if len([mac for mac in gateway_macs if not is_special_mac(mac)]) > 1:
                evidence = IpConflictEvidence(
                    local_mac=local_mac,
                    observed_macs=gateway_macs,
                    conflict_macs=gateway_macs,
                    gateway_mac_changes=max(len(gateway_macs) - 1, 0),
                    scanned_hosts=options.max_hosts,
                    notes="网关 MAC 发生变化",
                )
                results.append(
                    IpConflictResult(
                        adapter=adapter["name"],
                        ip=gateway,
                        mac="",
                        conflict_macs=", ".join(gateway_macs),
                        evidence_type="网关",
                        risk_level="可疑",
                        verdict="网关 IP 对应多个 MAC，可能是网关冗余、ARP 欺骗或地址冲突，建议复核网关设备。",
                        evidence=evidence,
                    )
                )

        proxy_rows = []
        for mac, ips in mac_to_ips.items():
            clean_ips = [ip for ip in ips if not is_multicast_or_broadcast_ip(ip)]
            if len(clean_ips) >= 8 and mac != local_mac:
                proxy_rows.append((mac, sorted(clean_ips)))
        for mac, ips in proxy_rows[:3]:
            evidence = IpConflictEvidence(
                local_mac=local_mac,
                observed_macs=[mac],
                shared_mac_ips=len(ips),
                scanned_hosts=options.max_hosts,
                notes="同一 MAC 对应大量 IP，可能是 Proxy ARP 或网关代理，不直接判定为 IP 冲突",
            )
            results.append(
                IpConflictResult(
                    adapter=adapter["name"],
                    ip=", ".join(ips[:5]) + ("..." if len(ips) > 5 else ""),
                    mac=mac,
                    conflict_macs="",
                    evidence_type="Proxy ARP 提示",
                    risk_level="可疑",
                    verdict="同一 MAC 对应大量 IP，更像 Proxy ARP/网关代理，需结合网络拓扑判断。",
                    evidence=evidence,
                )
            )

        return results

    def build_scan_targets(self, adapters: list[dict], options: IpConflictOptions) -> list[str]:
        if options.scan_range:
            return parse_target_range(options.scan_range, options.max_hosts)
        targets = []
        for adapter in adapters:
            targets.extend(parse_target_range(adapter_to_safe_range(adapter), options.max_hosts))
        return list(dict.fromkeys(targets))[: options.max_hosts]

    def refresh_arp_targets(self, targets: list[str], options: IpConflictOptions) -> None:
        done = 0

        def task(ip: str) -> None:
            if self.stop_event.is_set():
                return
            run_hidden(["ping", ip, "-n", "1", "-w", str(options.timeout_ms)], timeout=max(2, options.timeout_ms / 1000 + 2))

        with concurrent.futures.ThreadPoolExecutor(max_workers=options.workers) as executor:
            futures = {executor.submit(task, ip): ip for ip in targets}
            for future in concurrent.futures.as_completed(futures):
                done += 1
                if self.stop_event.is_set():
                    for item in futures:
                        item.cancel()
                    break
                try:
                    future.result()
                except Exception:
                    pass
                if done % 20 == 0 or done == len(targets):
                    self.status(self._status("扫描中", 0, futures[future], risk_rank("正常"), len(targets), done, 0))

    def get_address_states(self) -> dict[str, str]:
        script = r"""
$ErrorActionPreference = "SilentlyContinue"
Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress,InterfaceIndex,AddressState,PrefixLength | ConvertTo-Json -Depth 4 -Compress
"""
        try:
            result = run_hidden(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=10)
            if result.returncode != 0:
                raise RuntimeError(result.stdout.strip())
            data = extract_json(result.stdout)
            if isinstance(data, dict):
                data = [data]
            return {item.get("IPAddress", ""): str(item.get("AddressState", "")) for item in data if item.get("IPAddress")}
        except Exception as exc:
            self.output(f"读取本机地址状态失败: {exc}\n", "warning")
            return {}

    def get_tcpip_conflict_events(self) -> list[dict]:
        script = r"""
$ErrorActionPreference = "SilentlyContinue"
Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Tcpip'; StartTime=(Get-Date).AddDays(-7)} -MaxEvents 80 |
Select-Object TimeCreated,Id,ProviderName,Message | ConvertTo-Json -Depth 4 -Compress
"""
        try:
            result = run_hidden(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=12)
            if result.returncode != 0 or not result.stdout.strip():
                return []
            data = extract_json(result.stdout)
            if isinstance(data, dict):
                data = [data]
            events = []
            for item in data:
                message = str(item.get("Message", ""))
                if re.search(r"conflict|duplicate|冲突|重复", message, re.IGNORECASE):
                    events.append(
                        {
                            "time": str(item.get("TimeCreated", "")),
                            "id": str(item.get("Id", "")),
                            "message": message,
                        }
                    )
            return events
        except Exception as exc:
            self.output(f"读取 Tcpip 系统事件失败: {exc}\n", "warning")
            return []

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

    def stop_detection(self) -> None:
        if not self.is_running():
            raise RuntimeError("当前没有正在运行的 IP 冲突检测")
        self.stop_event.set()
        self.output("\n正在停止 IP 冲突检测...\n", "warning")

    def export_results(self, path: str) -> None:
        if not self.last_results:
            raise RuntimeError("还没有可导出的 IP 冲突检测结果")
        fields = [
            "adapter",
            "ip",
            "mac",
            "conflict_macs",
            "evidence_type",
            "risk_level",
            "verdict",
            "address_state",
            "local_mac",
            "observed_macs",
            "tcpip_event_count",
            "gateway_mac_changes",
            "ip_mac_changes",
            "shared_mac_ips",
            "scanned_hosts",
            "notes",
            "checked_at",
        ]
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for row in self.last_results:
                writer.writerow({field_name: row.get(field_name, "") for field_name in fields})

    def copy_summary(self) -> str:
        return self.last_summary

    def normalize_options(self, options: Optional[dict]) -> IpConflictOptions:
        options = options or {}
        mode = options.get("mode", MODE_BOTH)
        if mode not in {MODE_BOTH, MODE_LOCAL, MODE_SUBNET}:
            mode = MODE_BOTH
        return IpConflictOptions(
            mode=mode,
            scan_range=str(options.get("scan_range", "")).strip(),
            workers=clamp_int(options.get("workers", 64), 1, 256, "并发数"),
            timeout_ms=clamp_int(options.get("timeout_ms", 500), 100, 10000, "超时"),
            max_hosts=clamp_int(options.get("max_hosts", 254), 1, 254, "最大扫描地址数"),
            neighbor_samples=clamp_int(options.get("neighbor_samples", 3), 1, 5, "邻居表采样次数"),
        )

    def _select_adapters(self, adapter_name: str) -> list[dict]:
        adapters = self._active_adapters(self.network.get_network_info())
        if not adapter_name or adapter_name == ALL_ADAPTERS:
            return adapters
        return [adapter for adapter in adapters if adapter.get("name") == adapter_name]

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

    def _status(self, state: str, total: int, current: str, max_risk_rank: int, total_targets: int, completed: int, elapsed: float) -> dict:
        return {
            "state": state,
            "total_adapters": total,
            "current": current,
            "max_risk": risk_from_rank(max_risk_rank),
            "total_targets": total_targets,
            "completed": completed,
            "elapsed": elapsed,
        }

    def is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())


def normal_result(adapter: dict, verdict: str) -> IpConflictResult:
    evidence = IpConflictEvidence(address_state="", local_mac=normalize_mac(adapter.get("mac", "")), notes="未发现冲突证据")
    return IpConflictResult(
        adapter=adapter.get("name", ""),
        ip=adapter.get("ipv4", ""),
        mac=normalize_mac(adapter.get("mac", "")),
        conflict_macs="",
        evidence_type="本机 IP",
        risk_level="正常",
        verdict=verdict,
        evidence=evidence,
    )


def filter_neighbors(samples: list[list[dict]], interface_index: str, interface_ip: str) -> list[dict]:
    rows = []
    for sample in samples:
        for item in sample:
            if item.get("ifIndex"):
                if str(item.get("ifIndex")) == str(interface_index):
                    rows.append(item)
            elif item.get("interface_ip") == interface_ip:
                rows.append(item)
    return rows


def build_neighbor_maps(neighbors: list[dict]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    ip_to_macs: dict[str, set[str]] = {}
    mac_to_ips: dict[str, set[str]] = {}
    for item in neighbors:
        ip = item.get("ip", "")
        mac = normalize_mac(item.get("mac", ""))
        if not ip or not mac or is_special_mac(mac):
            continue
        ip_to_macs.setdefault(ip, set()).add(mac)
        mac_to_ips.setdefault(mac, set()).add(ip)
    return ip_to_macs, mac_to_ips


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
        network = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
        return str(network)
    except Exception:
        parts = ip.split(".")
        return ".".join(parts[:3]) + ".0/24" if len(parts) == 4 else ""


def netmask_to_prefix(netmask: str) -> Optional[int]:
    if not netmask:
        return None
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen
    except Exception:
        return None


def event_count_for_ip(events: list[dict], ip: str) -> int:
    return len([event for event in events if ip and ip in event.get("message", "")])


def build_summary(rows: list[dict], stopped: bool = False) -> str:
    if stopped:
        return "检测已停止，当前结果仅代表已完成部分。"
    if not rows:
        return "没有生成 IP 冲突检测结果。"
    ordered = sorted(rows, key=lambda row: risk_rank(row.get("risk_level", "正常")), reverse=True)
    highest = ordered[0]
    conflict = [row for row in ordered if row.get("risk_level") == "冲突风险"]
    suspicious = [row for row in ordered if row.get("risk_level") == "可疑"]
    lines = [
        "==== IP 冲突诊断摘要 ====",
        f"最高风险: {highest.get('adapter', '')} {highest.get('ip', '')}  {highest.get('risk_level', '')}",
        "结论基于本机 Windows 可见证据，建议结合交换机 MAC 地址表和现场设备确认。",
    ]
    if conflict:
        lines.append(f"发现 {len(conflict)} 条冲突风险。")
        for row in conflict[:5]:
            lines.append(f"{row['adapter']} {row['ip']}: {row['verdict']}")
    elif suspicious:
        lines.append(f"发现 {len(suspicious)} 条可疑信号，建议复测或结合交换机侧信息确认。")
        for row in suspicious[:5]:
            lines.append(f"{row['adapter']} {row['ip']}: {row['verdict']}")
    else:
        lines.append("整体正常，未发现本机 IP 被其它 MAC 占用、同 IP 多 MAC 或 Tcpip 冲突事件。")
    return "\n".join(lines)


def normalize_neighbor(item: dict) -> dict:
    return {
        "ifIndex": str(item.get("ifIndex", "")),
        "interface_ip": "",
        "ip": str(item.get("IPAddress", "")),
        "mac": normalize_mac(item.get("LinkLayerAddress", "")),
        "state": str(item.get("State", "")),
    }


def extract_json(text: str):
    output = text.strip()
    json_start = min([idx for idx in (output.find("["), output.find("{")) if idx >= 0], default=-1)
    if json_start < 0:
        raise RuntimeError("未获取到 JSON 输出")
    return json.loads(output[json_start:])


def is_special_mac(mac: str) -> bool:
    if not mac or mac == "00-00-00-00-00-00":
        return True
    return mac.startswith("FF-FF-FF") or mac.startswith("01-00-5E")


def is_multicast_or_broadcast_ip(ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(ip)
        return parsed.is_multicast or str(parsed).endswith(".255")
    except ValueError:
        return False


def worse_risk(left: str, right: str) -> str:
    return left if risk_rank(left) >= risk_rank(right) else right


def risk_rank(level: str) -> int:
    return {"正常": 0, "可疑": 1, "冲突风险": 2}.get(level, 0)


def risk_from_rank(value: int) -> str:
    if value >= 2:
        return "冲突风险"
    if value == 1:
        return "可疑"
    return "正常"


def clamp_int(value, min_value: int, max_value: int, label: str) -> int:
    try:
        number = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if number < min_value or number > max_value:
        raise ValueError(f"{label}必须在 {min_value}-{max_value} 之间")
    return number
