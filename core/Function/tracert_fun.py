import csv
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from core.Function.common import popen_hidden, validate_host


OutputCallback = Callable[[str, Optional[str]], None]
DoneCallback = Callable[[], None]
StatusCallback = Callable[[dict], None]
ResultCallback = Callable[[dict], None]


TRACE_STATUS = {
    "ok": "正常",
    "timeout": "超时",
    "high_latency": "高延迟",
    "jitter": "波动大",
}


@dataclass
class TraceOptions:
    max_hops: int = 20
    timeout_ms: int = 800
    address_family: str = "自动"
    resolve_names: bool = False
    mode: str = "单次"
    repeat_count: int = 1
    interval_ms: int = 1000
    high_latency_ms: int = 100


@dataclass
class TraceHop:
    run: int
    hop: int
    probe1: str
    probe2: str
    probe3: str
    avg_ms: float
    jitter_ms: float
    host: str
    ip: str
    status: str
    status_text: str
    raw_line: str
    checked_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["avg_ms"] = round(self.avg_ms, 1)
        data["jitter_ms"] = round(self.jitter_ms, 1)
        return data


@dataclass
class TraceStats:
    total_runs: int = 1
    current_run: int = 0
    max_hops: int = 20
    current_hop: int = 0
    timeout_hops: int = 0
    high_latency_hops: int = 0
    jitter_hops: int = 0
    max_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    samples: list[float] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)

    def record(self, hop: TraceHop) -> None:
        self.current_hop = max(self.current_hop, hop.hop)
        if hop.status == "timeout":
            self.timeout_hops += 1
        elif hop.status == "high_latency":
            self.high_latency_hops += 1
        elif hop.status == "jitter":
            self.jitter_hops += 1
        if hop.avg_ms:
            self.samples.append(hop.avg_ms)
            self.max_latency_ms = max(self.max_latency_ms, hop.avg_ms)
            self.avg_latency_ms = sum(self.samples) / len(self.samples)

    def snapshot(self, state: str) -> dict:
        return {
            "state": state,
            "current_run": self.current_run,
            "total_runs": self.total_runs,
            "current_hop": self.current_hop,
            "max_hops": self.max_hops,
            "timeout_hops": self.timeout_hops,
            "high_latency_hops": self.high_latency_hops,
            "jitter_hops": self.jitter_hops,
            "max_latency_ms": self.max_latency_ms,
            "avg_latency_ms": self.avg_latency_ms,
            "elapsed": time.perf_counter() - self.started_at,
        }


class TracertFun:
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
        self.process = None
        self.stop_event = threading.Event()
        self.worker = None
        self.last_results: list[dict] = []
        self.last_summary = ""

    def start_tracert(self, target: str, max_hops: int = 20, timeout_ms: int = 800, options: Optional[dict] = None) -> None:
        target = validate_host(target)
        trace_options = self.normalize_options(options or {})
        trace_options.max_hops = clamp_int(max_hops, 1, 64, "最大跳数")
        trace_options.timeout_ms = clamp_int(timeout_ms, 100, 60000, "单跳超时")

        if self.is_running():
            raise RuntimeError("路由追踪正在运行，请先停止当前任务")

        self.stop_event.clear()
        self.last_results = []
        self.last_summary = ""
        total_runs = 0 if trace_options.mode == "持续" else trace_options.repeat_count
        stats = TraceStats(total_runs=total_runs, max_hops=trace_options.max_hops)
        self.status(stats.snapshot("运行中"))
        self.output(f"开始路由追踪: {target}\n", "muted")
        self.output(self.describe_options(trace_options), "muted")
        self.worker = threading.Thread(target=self._run_loop, args=(target, trace_options, stats), daemon=True)
        self.worker.start()

    def _run_loop(self, target: str, options: TraceOptions, stats: TraceStats) -> None:
        run = 0
        max_runs = None if options.mode == "持续" else options.repeat_count
        try:
            while not self.stop_event.is_set() and (max_runs is None or run < max_runs):
                run += 1
                stats.current_run = run
                stats.current_hop = 0
                self.output(f"\n==== 第 {run} 次追踪 ====\n", "muted")
                self.status(stats.snapshot("运行中"))
                self._run_once(target, options, stats, run)
                if self.stop_event.is_set() or (max_runs is not None and run >= max_runs):
                    break
                self.stop_event.wait(options.interval_ms / 1000)
        finally:
            state = "已停止" if self.stop_event.is_set() else "已完成"
            self.status(stats.snapshot(state))
            self._write_overall_summary(state)
            self.done()

    def _run_once(self, target: str, options: TraceOptions, stats: TraceStats, run: int) -> None:
        command = self.build_command(target, options)
        run_results = []
        try:
            self.process = popen_hidden(command)
            if not self.process.stdout:
                return
            for raw_line in self.process.stdout:
                if self.stop_event.is_set():
                    break
                line = raw_line.rstrip()
                self.output(raw_line, None)
                hop = parse_trace_line(line, run, options.high_latency_ms)
                if not hop:
                    continue
                row = hop.to_dict()
                self.last_results.append(row)
                run_results.append(row)
                stats.record(hop)
                self.result(row)
                self.status(stats.snapshot("运行中"))
        except Exception as exc:
            self.output(f"\n路由追踪失败: {exc}\n", "error")
        finally:
            if self.process:
                try:
                    if self.stop_event.is_set():
                        self.process.terminate()
                    else:
                        self.process.wait(timeout=1)
                except Exception:
                    pass
                self.process = None
            self._write_run_summary(run_results, run)

    def build_command(self, target: str, options: TraceOptions) -> list[str]:
        command = ["tracert"]
        if not options.resolve_names:
            command.append("-d")
        if options.address_family == "IPv4":
            command.append("-4")
        elif options.address_family == "IPv6":
            command.append("-6")
        command += ["-w", str(options.timeout_ms), "-h", str(options.max_hops), target]
        return command

    def describe_options(self, options: TraceOptions) -> str:
        runs = "持续" if options.mode == "持续" else f"{options.repeat_count} 次"
        names = "开启" if options.resolve_names else "关闭"
        return (
            f"模式: {options.mode}({runs})  地址族: {options.address_family}  最大跳数: {options.max_hops}  "
            f"单跳超时: {options.timeout_ms}ms  间隔: {options.interval_ms}ms  "
            f"解析主机名: {names}  高延迟阈值: {options.high_latency_ms}ms\n"
        )

    def stop_tracert(self) -> None:
        if not self.is_running():
            raise RuntimeError("当前没有正在运行的路由追踪")
        self.stop_event.set()
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
        self.output("\n正在停止路由追踪...\n", "warning")

    def export_results(self, path: str) -> None:
        if not self.last_results:
            raise RuntimeError("还没有可导出的路由追踪结果")
        fields = [
            "run",
            "hop",
            "probe1",
            "probe2",
            "probe3",
            "avg_ms",
            "jitter_ms",
            "host",
            "ip",
            "status",
            "status_text",
            "raw_line",
            "checked_at",
        ]
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for row in self.last_results:
                writer.writerow({field: row.get(field, "") for field in fields})

    def copy_summary(self) -> str:
        return self.last_summary

    def normalize_options(self, options: dict) -> TraceOptions:
        mode = options.get("mode", "单次")
        if mode not in {"单次", "指定次数", "持续"}:
            mode = "单次"
        repeat_count = 1 if mode == "单次" else clamp_int(options.get("repeat_count", 3), 1, 1000, "追踪次数")
        address_family = options.get("address_family", "自动")
        if address_family not in {"自动", "IPv4", "IPv6"}:
            address_family = "自动"
        return TraceOptions(
            address_family=address_family,
            resolve_names=bool(options.get("resolve_names", False)),
            mode=mode,
            repeat_count=repeat_count,
            interval_ms=clamp_int(options.get("interval_ms", 1000), 0, 60000, "追踪间隔"),
            high_latency_ms=clamp_int(options.get("high_latency_ms", 100), 1, 10000, "高延迟阈值"),
        )

    def _write_run_summary(self, rows: list[dict], run: int) -> None:
        if not rows:
            return
        summary = build_diagnosis(rows)
        self.last_summary = summary
        self.output(f"\n==== 第 {run} 次诊断摘要 ====\n{summary}\n", "success" if "整体正常" in summary else "warning")

    def _write_overall_summary(self, state: str) -> None:
        if self.stop_event.is_set():
            self.output("\n路由追踪已停止\n", "warning")
            self.last_summary = "路由追踪已停止。"
            return
        if not self.last_results:
            self.output("\n路由追踪完成，但没有解析到跳点结果\n", "warning")
            self.last_summary = "路由追踪完成，但没有解析到跳点结果。"
            return
        self.last_summary = build_diagnosis(self.last_results)
        self.output(f"\n路由追踪{state}\n", "success")

    def is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())


def parse_trace_line(line: str, run: int = 1, high_latency_ms: int = 100) -> Optional[TraceHop]:
    match = re.match(r"^\s*(\d+)\s+(.+)$", line)
    if not match:
        return None

    hop = int(match.group(1))
    rest = match.group(2)
    probe_matches = list(re.finditer(r"\*|<\s*\d+\s*(?:ms|毫秒)|\d+\s*(?:ms|毫秒)", rest, flags=re.IGNORECASE))
    if not probe_matches:
        return None

    probes = []
    values = []
    for probe_match in probe_matches[:3]:
        raw = normalize_probe_text(probe_match.group(0))
        probes.append(raw)
        value = probe_to_ms(raw)
        if value is not None:
            values.append(value)
    while len(probes) < 3:
        probes.append("*")

    endpoint = rest[probe_matches[min(len(probe_matches), 3) - 1].end() :].strip()
    host, ip = parse_endpoint(endpoint)
    avg_ms = sum(values) / len(values) if values else 0.0
    jitter_ms = max(values) - min(values) if len(values) > 1 else 0.0
    status = classify_hop(values, avg_ms, jitter_ms, high_latency_ms)
    return TraceHop(
        run=run,
        hop=hop,
        probe1=probes[0],
        probe2=probes[1],
        probe3=probes[2],
        avg_ms=avg_ms,
        jitter_ms=jitter_ms,
        host=host,
        ip=ip,
        status=status,
        status_text=TRACE_STATUS[status],
        raw_line=line,
    )


def normalize_probe_text(text: str) -> str:
    text = re.sub(r"\s+", "", text.strip())
    text = text.replace("毫秒", "ms")
    return text.replace("MS", "ms").replace("Ms", "ms")


def probe_to_ms(text: str) -> Optional[float]:
    if text == "*":
        return None
    if text.startswith("<"):
        return 1.0
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def parse_endpoint(endpoint: str) -> tuple[str, str]:
    cleaned = endpoint.strip()
    if not cleaned or re.search(r"请求超时|request timed out", cleaned, re.IGNORECASE):
        return "", ""
    bracket_match = re.match(r"(.+?)\s+\[([^\]]+)\]$", cleaned)
    if bracket_match:
        return bracket_match.group(1).strip(), bracket_match.group(2).strip()
    return "", cleaned


def classify_hop(values: list[float], avg_ms: float, jitter_ms: float, high_latency_ms: int) -> str:
    if not values:
        return "timeout"
    if avg_ms >= high_latency_ms:
        return "high_latency"
    if jitter_ms >= max(30, high_latency_ms * 0.5):
        return "jitter"
    return "ok"


def build_diagnosis(rows: list[dict]) -> str:
    if not rows:
        return "没有解析到可诊断的跳点。"

    latest_run = max(int(row.get("run") or 1) for row in rows)
    latest = [row for row in rows if int(row.get("run") or 1) == latest_run]
    latest.sort(key=lambda row: int(row.get("hop") or 0))

    timeout_hops = [row for row in latest if row.get("status") == "timeout"]
    high_hops = [row for row in latest if row.get("status") == "high_latency"]
    jitter_hops = [row for row in latest if row.get("status") == "jitter"]
    ok_after_timeout = False
    for index, row in enumerate(latest):
        if row.get("status") == "timeout" and any(next_row.get("status") != "timeout" for next_row in latest[index + 1 :]):
            ok_after_timeout = True
            break

    lines = [
        f"本次共解析 {len(latest)} 跳，超时 {len(timeout_hops)} 跳，高延迟 {len(high_hops)} 跳，波动 {len(jitter_hops)} 跳。"
    ]
    if latest and latest[0].get("status") == "timeout":
        lines.append("第一跳无响应，优先检查本机网关、防火墙或本地网络。")
    if ok_after_timeout:
        lines.append("中间跳点超时但后续恢复，通常是中间路由器限制 ICMP，不一定代表链路故障。")
    if len(latest) >= 2 and latest[-1].get("status") == "timeout" and latest[-2].get("status") == "timeout":
        lines.append("末段连续超时，目标侧网络、跨网链路或目标防火墙可能存在限制。")
    if high_hops:
        detail = ", ".join(f"第 {row['hop']} 跳 {row.get('avg_ms', 0):.1f}ms" for row in high_hops[:5])
        lines.append(f"发现高延迟跳点: {detail}。")
    if jitter_hops:
        detail = ", ".join(f"第 {row['hop']} 跳抖动 {row.get('jitter_ms', 0):.1f}ms" for row in jitter_hops[:5])
        lines.append(f"发现延迟波动: {detail}。")
    if not timeout_hops and not high_hops and not jitter_hops:
        lines.append("整体正常，未发现明显超时、高延迟或波动。")
    return "\n".join(lines)


def clamp_int(value, min_value: int, max_value: int, label: str) -> int:
    try:
        number = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if number < min_value or number > max_value:
        raise ValueError(f"{label}必须在 {min_value}-{max_value} 之间")
    return number
