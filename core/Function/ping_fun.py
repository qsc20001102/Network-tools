import concurrent.futures
import csv
import ipaddress
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.Function.common import run_hidden, validate_host, validate_ip


OutputCallback = Callable[[str, Optional[str]], None]
DoneCallback = Callable[[], None]
StatusCallback = Callable[[dict], None]


@dataclass
class PingStats:
    sent: int = 0
    received: int = 0
    rtts: list[float] = field(default_factory=list)
    current_loss_streak: int = 0
    max_loss_streak: int = 0
    last_success_at: str = ""

    @property
    def lost(self) -> int:
        return max(self.sent - self.received, 0)

    @property
    def loss_rate(self) -> float:
        return self.lost / self.sent * 100 if self.sent else 0.0

    @property
    def avg_rtt(self) -> float:
        return sum(self.rtts) / len(self.rtts) if self.rtts else 0.0

    @property
    def jitter(self) -> float:
        if len(self.rtts) < 2:
            return 0.0
        deltas = [abs(self.rtts[index] - self.rtts[index - 1]) for index in range(1, len(self.rtts))]
        return sum(deltas) / len(deltas)

    @property
    def quality(self) -> str:
        if not self.sent:
            return "等待"
        if self.loss_rate >= 30 or self.max_loss_streak >= 3:
            return "丢包严重"
        if self.loss_rate > 0 or self.jitter >= 50:
            return "波动"
        return "稳定"

    def snapshot(self) -> dict:
        return {
            "sent": self.sent,
            "received": self.received,
            "lost": self.lost,
            "loss_rate": self.loss_rate,
            "min_rtt": min(self.rtts) if self.rtts else 0.0,
            "max_rtt": max(self.rtts) if self.rtts else 0.0,
            "avg_rtt": self.avg_rtt,
            "jitter": self.jitter,
            "max_loss_streak": self.max_loss_streak,
            "last_success_at": self.last_success_at,
            "quality": self.quality,
        }


class PingFun:
    def __init__(
        self,
        output: OutputCallback,
        done: Optional[DoneCallback] = None,
        status: Optional[StatusCallback] = None,
    ):
        self.output = output
        self.done = done or (lambda: None)
        self.status = status or (lambda _stats: None)
        self.stop_event = threading.Event()
        self.worker = None
        self.batch_worker = None
        self.stats = PingStats()
        self.last_batch_results = []

    def start_ping(self, host: str, local_ip: str = "", options: Optional[dict] = None) -> None:
        host = validate_host(host)
        local_ip = validate_ip(local_ip, allow_empty=True)
        options = self.normalize_options(options)

        if self.is_running() or self.is_batch_running():
            raise RuntimeError("Ping 正在运行，请先停止当前任务")

        self.stop_event.clear()
        self.stats = PingStats()
        self.status(self.stats.snapshot() | {"state": "运行中"})

        self.output(f"开始 Ping: {host}\n", "muted")
        self.output(self.describe_options(options, local_ip), "muted")
        self.worker = threading.Thread(target=self._run_ping_loop, args=(host, local_ip, options), daemon=True)
        self.worker.start()

    def _run_ping_loop(self, host: str, local_ip: str, options: dict) -> None:
        max_count = None if options["mode"] == "持续" else options["count"]
        try:
            while not self.stop_event.is_set() and (max_count is None or self.stats.sent < max_count):
                started = time.perf_counter()
                result = self.ping_once(host, local_ip, options)
                self._record_single_result(result)
                elapsed_ms = (time.perf_counter() - started) * 1000
                wait_ms = max(options["interval_ms"] - elapsed_ms, 0)
                self.stop_event.wait(wait_ms / 1000)
        finally:
            self._write_statistics("Ping 统计")
            self.status(self.stats.snapshot() | {"state": "已停止" if self.stop_event.is_set() else "已完成"})
            self.done()

    def _record_single_result(self, result: dict) -> None:
        self.stats.sent += 1
        if result["ok"]:
            self.stats.received += 1
            self.stats.current_loss_streak = 0
            self.stats.rtts.append(result["rtt"])
            self.stats.last_success_at = time.strftime("%H:%M:%S")
            self.output(f"[{self.stats.sent}] {result['host']}  通  {result['rtt']:.1f} ms\n", "success")
        else:
            self.stats.current_loss_streak += 1
            self.stats.max_loss_streak = max(self.stats.max_loss_streak, self.stats.current_loss_streak)
            self.output(f"[{self.stats.sent}] {result['host']}  {result['message']}\n", "warning")
        self.status(self.stats.snapshot() | {"state": "运行中"})

    def stop_ping(self) -> None:
        self.stop_event.set()
        self.output("\n已请求停止 Ping\n", "warning")

    def start_batch_ping(self, target_text: str, local_ip: str = "", options: Optional[dict] = None) -> None:
        local_ip = validate_ip(local_ip, allow_empty=True)
        hosts = parse_ping_targets(target_text)
        options = self.normalize_options(options)

        if self.is_running() or self.is_batch_running():
            raise RuntimeError("Ping 正在运行，请先停止当前任务")

        self.stop_event.clear()
        self.last_batch_results = []
        self.status({"state": "批量运行中", "sent": 0, "received": 0, "lost": 0, "loss_rate": 0, "avg_rtt": 0, "jitter": 0, "quality": "等待"})
        self.output(f"开始批量 Ping: 共 {len(hosts)} 个目标\n", "muted")
        self.output(self.describe_options(options, local_ip), "muted")
        self.batch_worker = threading.Thread(target=self._run_batch_ping, args=(hosts, local_ip, options), daemon=True)
        self.batch_worker.start()

    def _run_batch_ping(self, hosts: list[str], local_ip: str, options: dict) -> None:
        results = []
        done = 0
        workers = min(options["workers"], max(1, len(hosts)))

        def task(host: str) -> dict:
            if self.stop_event.is_set():
                return {"host": host, "ok": False, "rtt": 0.0, "message": "已取消"}
            return self.ping_once(host, local_ip, options)

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_host = {executor.submit(task, host): host for host in hosts}
                for future in concurrent.futures.as_completed(future_to_host):
                    if self.stop_event.is_set():
                        for item in future_to_host:
                            item.cancel()
                        break
                    result = future.result()
                    done += 1
                    results.append(result)
                    tag = "success" if result["ok"] else None
                    message = f"{result['rtt']:.1f} ms" if result["ok"] else result["message"]
                    self.output(f"[{done}/{len(hosts)}] {result['host']:<15} {message}\n", tag)
                    self.status(self._batch_snapshot(results, len(hosts)) | {"state": "批量运行中"})
        finally:
            ordered = sorted(results, key=lambda item: ipaddress.ip_address(item["host"]))
            self.last_batch_results = ordered
            if self.stop_event.is_set():
                self.output("\n批量 Ping 已停止\n", "warning")
            else:
                self._write_batch_summary(ordered, len(hosts))
            self.status(self._batch_snapshot(ordered, len(hosts)) | {"state": "已停止" if self.stop_event.is_set() else "已完成"})
            self.done()

    def stop_batch_ping(self) -> None:
        self.stop_event.set()
        self.output("\n正在停止批量 Ping...\n", "warning")

    def ping_once(self, host: str, local_ip: str, options: dict) -> dict:
        command = ["ping", host, "-n", "1", "-w", str(options["timeout_ms"])]
        if local_ip:
            command += ["-S", local_ip]
        if options["size"] > 0:
            command += ["-l", str(options["size"])]
        if options["ttl"] > 0:
            command += ["-i", str(options["ttl"])]
        if options["dont_fragment"]:
            command.append("-f")

        try:
            result = run_hidden(command, timeout=max(2, options["timeout_ms"] / 1000 + 2))
            return parse_ping_output(host, result.stdout)
        except Exception as exc:
            return {"host": host, "ok": False, "rtt": 0.0, "message": str(exc)}

    def normalize_options(self, options: Optional[dict]) -> dict:
        options = options or {}
        return {
            "mode": options.get("mode", "持续"),
            "count": clamp_int(options.get("count", 4), 1, 100000, "次数"),
            "interval_ms": clamp_int(options.get("interval_ms", 1000), 100, 60000, "间隔"),
            "timeout_ms": clamp_int(options.get("timeout_ms", 1200), 100, 60000, "超时"),
            "size": clamp_int(options.get("size", 32), 0, 65500, "包大小"),
            "ttl": clamp_int(options.get("ttl", 0), 0, 255, "TTL"),
            "dont_fragment": bool(options.get("dont_fragment", False)),
            "workers": clamp_int(options.get("workers", 64), 1, 256, "并发数"),
        }

    def describe_options(self, options: dict, local_ip: str) -> str:
        mode = "持续" if options["mode"] == "持续" else f"{options['count']} 次"
        source = local_ip or "默认路由"
        df = "是" if options["dont_fragment"] else "否"
        ttl = options["ttl"] if options["ttl"] else "默认"
        return (
            f"模式: {mode}  源地址: {source}  间隔: {options['interval_ms']}ms  "
            f"超时: {options['timeout_ms']}ms  包大小: {options['size']} bytes  TTL: {ttl}  禁止分片: {df}\n\n"
        )

    def _write_statistics(self, title: str) -> None:
        snapshot = self.stats.snapshot()
        if not snapshot["sent"]:
            return
        lines = [
            f"\n==== {title} ====\n",
            f"发送: {snapshot['sent']}  接收: {snapshot['received']}  丢失: {snapshot['lost']}  丢包率: {snapshot['loss_rate']:.1f}%\n",
            f"延迟: 最小 {snapshot['min_rtt']:.1f} ms  最大 {snapshot['max_rtt']:.1f} ms  平均 {snapshot['avg_rtt']:.1f} ms  抖动 {snapshot['jitter']:.1f} ms\n",
            f"最大连续丢包: {snapshot['max_loss_streak']}  最后成功: {snapshot['last_success_at'] or '-'}  状态: {snapshot['quality']}\n",
        ]
        self.output("".join(lines), "success" if snapshot["loss_rate"] == 0 else "warning")

    def _write_batch_summary(self, results: list[dict], total: int) -> None:
        online = [item for item in results if item["ok"]]
        offline = [item for item in results if not item["ok"] and item["message"] != "超时"]
        timeout = [item for item in results if item["message"] == "超时"]
        snapshot = self._batch_snapshot(results, total)

        self.output("\n==== 批量 Ping 统计 ====\n", "muted")
        self.output(f"总数: {total}  在线: {len(online)}  离线: {len(offline)}  超时: {len(timeout)}  成功率: {100 - snapshot['loss_rate']:.1f}%\n", "success")
        if online:
            self.output("在线 IP: " + ", ".join(item["host"] for item in online) + "\n", "success")
        if timeout:
            self.output("超时 IP: " + ", ".join(item["host"] for item in timeout) + "\n", "warning")
        if offline:
            self.output("离线 IP: " + ", ".join(item["host"] for item in offline) + "\n", "warning")

    def _batch_snapshot(self, results: list[dict], total: int) -> dict:
        received = len([item for item in results if item["ok"]])
        rtts = [item["rtt"] for item in results if item["ok"]]
        sent = len(results)
        loss_rate = (sent - received) / sent * 100 if sent else 0.0
        avg = sum(rtts) / len(rtts) if rtts else 0.0
        jitter = 0.0
        if len(rtts) > 1:
            deltas = [abs(rtts[index] - rtts[index - 1]) for index in range(1, len(rtts))]
            jitter = sum(deltas) / len(deltas)
        return {
            "sent": sent,
            "received": received,
            "lost": max(sent - received, 0),
            "loss_rate": loss_rate,
            "avg_rtt": avg,
            "jitter": jitter,
            "quality": "稳定" if loss_rate == 0 else "波动" if loss_rate < 30 else "丢包严重",
        }

    def export_batch_results(self, path: str) -> None:
        if not self.last_batch_results:
            raise RuntimeError("还没有可导出的批量 Ping 结果")
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=["host", "ok", "rtt", "message"])
            writer.writeheader()
            writer.writerows(self.last_batch_results)

    def is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    def is_batch_running(self) -> bool:
        return bool(self.batch_worker and self.batch_worker.is_alive())


def parse_ping_output(host: str, output: str) -> dict:
    ttl_found = re.search(r"\bTTL=", output, re.IGNORECASE)
    rtt_match = re.search(r"(?:time|时间)[=<]?\s*(\d+(?:\.\d+)?)\s*ms", output, re.IGNORECASE)
    if ttl_found:
        rtt = float(rtt_match.group(1)) if rtt_match else 0.0
        return {"host": host, "ok": True, "rtt": rtt, "message": "在线"}
    if re.search(r"请求超时|timed out|timeout", output, re.IGNORECASE):
        return {"host": host, "ok": False, "rtt": 0.0, "message": "超时"}
    if re.search(r"无法访问|unreachable|could not find host|找不到主机", output, re.IGNORECASE):
        return {"host": host, "ok": False, "rtt": 0.0, "message": "不可达"}
    return {"host": host, "ok": False, "rtt": 0.0, "message": "无响应"}


def parse_ping_targets(text: str) -> list[str]:
    raw = text.strip()
    if not raw:
        raise ValueError("请输入批量 Ping 目标")

    targets = []
    for part in re.split(r"[,，\s]+", raw):
        item = part.strip()
        if not item:
            continue
        if "/" in item:
            network = ipaddress.ip_network(item, strict=False)
            targets.extend(str(ip) for ip in network.hosts())
        elif re.match(r"^\d{1,3}(?:\.\d{1,3}){3}-\d{1,3}$", item):
            prefix, end_text = item.rsplit(".", 1)
            start_text, end_host = end_text.split("-", 1)
            start = int(start_text)
            end = int(end_host)
            if start > end:
                raise ValueError("IP 范围起始值不能大于结束值")
            targets.extend(str(ipaddress.ip_address(f"{prefix}.{index}")) for index in range(start, end + 1))
        else:
            targets.append(str(ipaddress.ip_address(item)))

    unique = list(dict.fromkeys(targets))
    if not unique:
        raise ValueError("没有解析到有效目标")
    return unique


def clamp_int(value, min_value: int, max_value: int, label: str) -> int:
    try:
        number = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if number < min_value or number > max_value:
        raise ValueError(f"{label}必须在 {min_value}-{max_value} 之间")
    return number
