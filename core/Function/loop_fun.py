import csv
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from core.Function.common import run_hidden
from core.Function.network_fun import NetworkManager


OutputCallback = Callable[[str, Optional[str]], None]
DoneCallback = Callable[[], None]
StatusCallback = Callable[[dict], None]
ResultCallback = Callable[[dict], None]


ALL_ADAPTERS = "全部活动网卡"


@dataclass
class LoopOptions:
    duration_sec: int = 15
    interval_sec: int = 1
    ping_timeout_ms: int = 800


@dataclass
class LoopEvidence:
    non_unicast_pps: float = 0.0
    broadcast_pps: float = 0.0
    multicast_pps: float = 0.0
    non_unicast_ratio: float = 0.0
    error_delta: int = 0
    discard_delta: int = 0
    gateway_ping_sent: int = 0
    gateway_ping_loss: float = 0.0
    gateway_avg_ms: float = 0.0
    gateway_jitter_ms: float = 0.0
    gateway_mac_changes: int = 0
    ip_mac_changes: int = 0
    shared_mac_count: int = 0
    neighbor_unreachable: int = 0
    notes: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        for key, value in data.items():
            if isinstance(value, float):
                data[key] = round(value, 2)
        return data


@dataclass
class LoopResult:
    adapter: str
    ipv4: str
    gateway: str
    interface_index: str
    link_speed: str
    risk_score: int
    risk_level: str
    verdict: str
    evidence: LoopEvidence
    checked_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        data = {
            "adapter": self.adapter,
            "ipv4": self.ipv4,
            "gateway": self.gateway,
            "interface_index": self.interface_index,
            "link_speed": self.link_speed,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "verdict": self.verdict,
            "checked_at": self.checked_at,
        }
        data.update(self.evidence.to_dict())
        return data


class LoopDetector:
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

    def start_detection(self, adapter_name: str = ALL_ADAPTERS, options: Optional[dict] = None) -> None:
        if self.is_running():
            raise RuntimeError("环网检测正在运行，请先停止当前任务")

        loop_options = self.normalize_options(options)
        adapters = self._select_adapters(adapter_name)
        if not adapters:
            raise ValueError("没有找到可检测的活动网卡")

        self.stop_event.clear()
        self.last_results = []
        self.last_summary = ""
        self.output(
            f"开始环网风险检测: {adapter_name or ALL_ADAPTERS}，"
            f"检测 {loop_options.duration_sec}s，采样间隔 {loop_options.interval_sec}s\n",
            "muted",
        )
        self.output("说明: 本功能基于本机侧证据判断疑似二层环路风险，不等同于交换机 STP/SNMP 的绝对结论。\n\n", "muted")
        self.status(self._status("运行中", len(adapters), "", 0, 0, 0))
        self.worker = threading.Thread(target=self._run_detection, args=(adapters, loop_options), daemon=True)
        self.worker.start()

    def _run_detection(self, adapters: list[dict], options: LoopOptions) -> None:
        started = time.perf_counter()
        ping_samples = {adapter["name"]: [] for adapter in adapters}
        neighbor_samples = []
        start_stats = {}
        end_stats = {}

        try:
            start_stats = self.get_adapter_statistics()
            neighbor_samples.append(self.get_neighbors())
            end_time = started + options.duration_sec
            sample_index = 0

            while not self.stop_event.is_set() and time.perf_counter() < end_time:
                sample_index += 1
                for adapter in adapters:
                    if self.stop_event.is_set():
                        break
                    self.status(self._status("运行中", len(adapters), adapter["name"], 0, sample_index, time.perf_counter() - started))
                    gateway = adapter.get("gateway", "")
                    if gateway:
                        ping_samples[adapter["name"]].append(self.ping_gateway(gateway, options.ping_timeout_ms))
                neighbor_samples.append(self.get_neighbors())
                remaining = end_time - time.perf_counter()
                if remaining <= 0:
                    break
                self.stop_event.wait(min(options.interval_sec, remaining))

            end_stats = self.get_adapter_statistics()
            rows = []
            max_score = 0
            for index, adapter in enumerate(adapters, start=1):
                result = self.evaluate_adapter(
                    adapter,
                    start_stats.get(adapter["name"], {}),
                    end_stats.get(adapter["name"], {}),
                    neighbor_samples,
                    ping_samples.get(adapter["name"], []),
                    max(time.perf_counter() - started, 1.0),
                )
                row = result.to_dict()
                rows.append(row)
                self.last_results.append(row)
                max_score = max(max_score, result.risk_score)
                self.result(row)
                self.status(self._status("汇总中", len(adapters), adapter["name"], max_score, index, time.perf_counter() - started))

            self.last_summary = build_summary(rows, stopped=self.stop_event.is_set())
            if self.stop_event.is_set():
                self.output("\n环网检测已停止\n", "warning")
            else:
                self.output("\n环网检测完成\n", "success")
            self.output(self.last_summary + "\n", "success" if max_score < 30 else "warning")
            self.status(self._status("已停止" if self.stop_event.is_set() else "已完成", len(adapters), "", max_score, len(adapters), time.perf_counter() - started))
        except Exception as exc:
            self.output(f"\n环网检测失败: {exc}\n", "error")
            self.status(self._status("失败", len(adapters), "", 0, 0, time.perf_counter() - started))
        finally:
            self.done()

    def evaluate_adapter(
        self,
        adapter: dict,
        start_stats: dict,
        end_stats: dict,
        neighbor_samples: list[list[dict]],
        pings: list[dict],
        duration_sec: float,
    ) -> LoopResult:
        evidence = build_evidence(adapter, start_stats, end_stats, neighbor_samples, pings, duration_sec)
        score, reasons = score_evidence(evidence)
        level = risk_level(score)
        verdict = build_verdict(level, reasons)
        return LoopResult(
            adapter=adapter.get("name", ""),
            ipv4=adapter.get("ipv4", ""),
            gateway=adapter.get("gateway", ""),
            interface_index=str(adapter.get("interface_index", "")),
            link_speed=adapter.get("link_speed", ""),
            risk_score=score,
            risk_level=level,
            verdict=verdict,
            evidence=evidence,
        )

    def get_adapter_statistics(self) -> dict[str, dict]:
        script = r"""
$ErrorActionPreference = "SilentlyContinue"
Get-NetAdapterStatistics | Select-Object InterfaceAlias,
ReceivedBroadcastPackets,SentBroadcastPackets,
ReceivedMulticastPackets,SentMulticastPackets,
ReceivedUnicastPackets,SentUnicastPackets,
ReceivedPacketErrors,OutboundPacketErrors,
ReceivedDiscardedPackets,OutboundDiscardedPackets,
ReceivedBytes,SentBytes | ConvertTo-Json -Depth 4 -Compress
"""
        try:
            result = run_hidden(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=10)
            if result.returncode != 0:
                raise RuntimeError(result.stdout.strip())
            output = result.stdout.strip()
            json_start = min([idx for idx in (output.find("["), output.find("{")) if idx >= 0], default=-1)
            if json_start < 0:
                raise RuntimeError("未获取到网卡统计 JSON")
            data = json.loads(output[json_start:])
            if isinstance(data, dict):
                data = [data]
            return {item.get("InterfaceAlias", ""): normalize_stat_item(item) for item in data if item.get("InterfaceAlias")}
        except Exception as exc:
            self.output(f"读取网卡统计失败，相关证据将降级: {exc}\n", "warning")
            return {}

    def get_neighbors(self) -> list[dict]:
        script = r"""
$ErrorActionPreference = "SilentlyContinue"
Get-NetNeighbor -AddressFamily IPv4 | Select-Object ifIndex,IPAddress,LinkLayerAddress,State | ConvertTo-Json -Depth 4 -Compress
"""
        try:
            result = run_hidden(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=10)
            if result.returncode != 0:
                raise RuntimeError(result.stdout.strip())
            output = result.stdout.strip()
            json_start = min([idx for idx in (output.find("["), output.find("{")) if idx >= 0], default=-1)
            if json_start < 0:
                raise RuntimeError("未获取到邻居表 JSON")
            data = json.loads(output[json_start:])
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

    def ping_gateway(self, gateway: str, timeout_ms: int) -> dict:
        try:
            result = run_hidden(["ping", gateway, "-n", "1", "-w", str(timeout_ms)], timeout=max(2, timeout_ms / 1000 + 2))
            return parse_ping_result(gateway, result.stdout)
        except Exception as exc:
            return {"gateway": gateway, "ok": False, "rtt": 0.0, "message": str(exc)}

    def stop_detection(self) -> None:
        if not self.is_running():
            raise RuntimeError("当前没有正在运行的环网检测")
        self.stop_event.set()
        self.output("\n正在停止环网检测...\n", "warning")

    def export_results(self, path: str) -> None:
        if not self.last_results:
            raise RuntimeError("还没有可导出的环网检测结果")
        fields = [
            "adapter",
            "ipv4",
            "gateway",
            "interface_index",
            "link_speed",
            "risk_score",
            "risk_level",
            "verdict",
            "non_unicast_pps",
            "broadcast_pps",
            "multicast_pps",
            "non_unicast_ratio",
            "error_delta",
            "discard_delta",
            "gateway_ping_sent",
            "gateway_ping_loss",
            "gateway_avg_ms",
            "gateway_jitter_ms",
            "gateway_mac_changes",
            "ip_mac_changes",
            "shared_mac_count",
            "neighbor_unreachable",
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

    def normalize_options(self, options: Optional[dict]) -> LoopOptions:
        options = options or {}
        return LoopOptions(
            duration_sec=clamp_int(options.get("duration_sec", 15), 5, 300, "检测时长"),
            interval_sec=clamp_int(options.get("interval_sec", 1), 1, 30, "采样间隔"),
            ping_timeout_ms=clamp_int(options.get("ping_timeout_ms", 800), 100, 10000, "Ping 超时"),
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
            if "disconnect" in status or "断开" in status:
                continue
            active.append(adapter)
        return active

    def _status(self, state: str, total: int, current: str, max_score: int, completed: int, elapsed: float) -> dict:
        return {
            "state": state,
            "total_adapters": total,
            "current_adapter": current,
            "max_score": max_score,
            "risk_level": risk_level(max_score),
            "completed": completed,
            "elapsed": elapsed,
        }

    def is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())


def build_evidence(
    adapter: dict,
    start_stats: dict,
    end_stats: dict,
    neighbor_samples: list[list[dict]],
    pings: list[dict],
    duration_sec: float,
) -> LoopEvidence:
    broadcast_delta = positive_delta(start_stats, end_stats, "broadcast_packets")
    multicast_delta = positive_delta(start_stats, end_stats, "multicast_packets")
    unicast_delta = positive_delta(start_stats, end_stats, "unicast_packets")
    error_delta = positive_delta(start_stats, end_stats, "packet_errors")
    discard_delta = positive_delta(start_stats, end_stats, "discarded_packets")
    non_unicast = broadcast_delta + multicast_delta
    total_packets = non_unicast + unicast_delta

    ping_rtts = [item["rtt"] for item in pings if item.get("ok")]
    sent = len(pings)
    received = len(ping_rtts)
    loss = (sent - received) / sent * 100 if sent else 0.0
    avg_ms = sum(ping_rtts) / len(ping_rtts) if ping_rtts else 0.0
    jitter = 0.0
    if len(ping_rtts) > 1:
        deltas = [abs(ping_rtts[index] - ping_rtts[index - 1]) for index in range(1, len(ping_rtts))]
        jitter = sum(deltas) / len(deltas)

    arp = analyze_neighbors(adapter, neighbor_samples)
    notes = []
    if not start_stats or not end_stats:
        notes.append("网卡统计不可用")
    if not adapter.get("gateway"):
        notes.append("未发现默认网关，跳过网关 Ping")

    return LoopEvidence(
        non_unicast_pps=non_unicast / duration_sec,
        broadcast_pps=broadcast_delta / duration_sec,
        multicast_pps=multicast_delta / duration_sec,
        non_unicast_ratio=(non_unicast / total_packets * 100) if total_packets else 0.0,
        error_delta=error_delta,
        discard_delta=discard_delta,
        gateway_ping_sent=sent,
        gateway_ping_loss=loss,
        gateway_avg_ms=avg_ms,
        gateway_jitter_ms=jitter,
        gateway_mac_changes=arp["gateway_mac_changes"],
        ip_mac_changes=arp["ip_mac_changes"],
        shared_mac_count=arp["shared_mac_count"],
        neighbor_unreachable=arp["neighbor_unreachable"],
        notes="; ".join(notes),
    )


def analyze_neighbors(adapter: dict, samples: list[list[dict]]) -> dict:
    interface_index = str(adapter.get("interface_index", ""))
    interface_ip = adapter.get("ipv4", "")
    gateway = adapter.get("gateway", "")
    gateway_macs = set()
    ip_to_macs: dict[str, set[str]] = {}
    mac_to_ips: dict[str, set[str]] = {}
    unreachable = 0

    for sample in samples:
        for item in sample:
            if not neighbor_belongs_to_adapter(item, interface_index, interface_ip):
                continue
            ip = item.get("ip", "")
            mac = normalize_mac(item.get("mac", ""))
            state = str(item.get("state", ""))
            if not ip or not mac or is_special_mac(mac):
                continue
            if state.lower() in {"unreachable", "incomplete"} or state in {"不可达", "不完整"}:
                unreachable += 1
            ip_to_macs.setdefault(ip, set()).add(mac)
            mac_to_ips.setdefault(mac, set()).add(ip)
            if gateway and ip == gateway:
                gateway_macs.add(mac)

    return {
        "gateway_mac_changes": max(len(gateway_macs) - 1, 0),
        "ip_mac_changes": len([ip for ip, macs in ip_to_macs.items() if len(macs) > 1]),
        "shared_mac_count": len([mac for mac, ips in mac_to_ips.items() if len(ips) >= 6]),
        "neighbor_unreachable": unreachable,
    }


def score_evidence(evidence: LoopEvidence) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    if evidence.non_unicast_pps >= 2000:
        score += 35
        reasons.append("非单播流量速率极高")
    elif evidence.non_unicast_pps >= 500:
        score += 25
        reasons.append("非单播流量速率偏高")
    elif evidence.non_unicast_pps >= 100:
        score += 15
        reasons.append("非单播流量明显增加")
    elif evidence.non_unicast_pps >= 20:
        score += 8
        reasons.append("非单播流量轻微偏高")

    if evidence.non_unicast_ratio >= 60:
        score += 20
        reasons.append("非单播占比过高")
    elif evidence.non_unicast_ratio >= 30:
        score += 12
        reasons.append("非单播占比较高")
    elif evidence.non_unicast_ratio >= 10:
        score += 6
        reasons.append("非单播占比偏高")

    if evidence.error_delta + evidence.discard_delta >= 20:
        score += 20
        reasons.append("错误/丢弃包明显增加")
    elif evidence.error_delta + evidence.discard_delta > 0:
        score += 10
        reasons.append("出现错误/丢弃包")

    if evidence.gateway_ping_sent:
        if evidence.gateway_ping_loss >= 50:
            score += 20
            reasons.append("网关 Ping 丢包严重")
        elif evidence.gateway_ping_loss > 0:
            score += 10
            reasons.append("网关 Ping 存在丢包")
        if evidence.gateway_jitter_ms >= 50:
            score += 10
            reasons.append("网关延迟波动较大")
        if evidence.gateway_avg_ms >= 100:
            score += 8
            reasons.append("网关平均延迟偏高")

    if evidence.gateway_mac_changes:
        score += 25
        reasons.append("网关 MAC 发生变化")
    if evidence.ip_mac_changes:
        score += 20
        reasons.append("同一 IP 出现多个 MAC")
    if evidence.shared_mac_count:
        score += 8
        reasons.append("部分 MAC 对应过多 IP")
    if evidence.neighbor_unreachable >= 5:
        score += 8
        reasons.append("邻居表不可达项较多")

    return min(score, 100), reasons


def build_verdict(level: str, reasons: list[str]) -> str:
    if not reasons:
        return "未发现明显环网风险，仅基于本机侧证据判断。"
    prefix = {
        "高风险": "疑似二层环路或广播风暴，请优先检查交换机端口、网线回接和 STP 状态。",
        "可疑": "存在环网风险迹象，建议结合交换机端口流量和 STP 日志复核。",
        "正常": "存在轻微信号，但尚不足以判断为环网风险。",
    }[level]
    return prefix + " 证据: " + "、".join(reasons)


def build_summary(rows: list[dict], stopped: bool = False) -> str:
    if stopped:
        return "检测已停止，当前结果仅代表已完成采样。"
    if not rows:
        return "没有生成检测结果。"
    ordered = sorted(rows, key=lambda row: row.get("risk_score", 0), reverse=True)
    highest = ordered[0]
    lines = [
        "==== 环网风险诊断摘要 ====",
        f"最高风险: {highest['adapter']}  {highest['risk_level']}  {highest['risk_score']} 分",
        "结论基于本机网卡统计、ARP/邻居表和网关 Ping，不能替代交换机 STP/SNMP 侧确认。",
    ]
    risky = [row for row in ordered if row.get("risk_score", 0) >= 30]
    if not risky:
        lines.append("整体正常，未发现明显广播风暴、ARP 抖动或网关稳定性异常。")
    else:
        for row in risky:
            lines.append(f"{row['adapter']}: {row['verdict']}")
    return "\n".join(lines)


def normalize_stat_item(item: dict) -> dict:
    return {
        "broadcast_packets": to_int(item.get("ReceivedBroadcastPackets")) + to_int(item.get("SentBroadcastPackets")),
        "multicast_packets": to_int(item.get("ReceivedMulticastPackets")) + to_int(item.get("SentMulticastPackets")),
        "unicast_packets": to_int(item.get("ReceivedUnicastPackets")) + to_int(item.get("SentUnicastPackets")),
        "packet_errors": to_int(item.get("ReceivedPacketErrors")) + to_int(item.get("OutboundPacketErrors")),
        "discarded_packets": to_int(item.get("ReceivedDiscardedPackets")) + to_int(item.get("OutboundDiscardedPackets")),
        "bytes": to_int(item.get("ReceivedBytes")) + to_int(item.get("SentBytes")),
    }


def normalize_neighbor(item: dict) -> dict:
    return {
        "ifIndex": str(item.get("ifIndex", "")),
        "interface_ip": "",
        "ip": str(item.get("IPAddress", "")),
        "mac": normalize_mac(item.get("LinkLayerAddress", "")),
        "state": str(item.get("State", "")),
    }


def neighbor_belongs_to_adapter(item: dict, interface_index: str, interface_ip: str) -> bool:
    if item.get("ifIndex"):
        return str(item.get("ifIndex")) == str(interface_index)
    if item.get("interface_ip"):
        return item.get("interface_ip") == interface_ip
    return False


def parse_ping_result(gateway: str, output: str) -> dict:
    if re.search(r"\bTTL=", output, re.IGNORECASE):
        match = re.search(r"(?:time|时间)[=<]?\s*(\d+(?:\.\d+)?)\s*(?:ms|毫秒)", output, re.IGNORECASE)
        return {"gateway": gateway, "ok": True, "rtt": float(match.group(1)) if match else 0.0, "message": "在线"}
    if re.search(r"请求超时|timed out|timeout", output, re.IGNORECASE):
        return {"gateway": gateway, "ok": False, "rtt": 0.0, "message": "超时"}
    return {"gateway": gateway, "ok": False, "rtt": 0.0, "message": "无响应"}


def positive_delta(start: dict, end: dict, key: str) -> int:
    return max(to_int(end.get(key)) - to_int(start.get(key)), 0)


def to_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def risk_level(score: int) -> str:
    if score >= 60:
        return "高风险"
    if score >= 30:
        return "可疑"
    return "正常"


def normalize_mac(value: str) -> str:
    raw = str(value or "").strip().replace(":", "-").upper()
    return raw


def is_special_mac(mac: str) -> bool:
    if not mac or mac == "00-00-00-00-00-00":
        return True
    return mac.startswith("FF-FF-FF") or mac.startswith("01-00-5E")


def clamp_int(value, min_value: int, max_value: int, label: str) -> int:
    try:
        number = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if number < min_value or number > max_value:
        raise ValueError(f"{label}必须在 {min_value}-{max_value} 之间")
    return number
