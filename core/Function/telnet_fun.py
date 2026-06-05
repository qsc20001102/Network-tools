import concurrent.futures
import csv
import ipaddress
import re
import socket
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Optional

from core.Function.common import parse_ports, validate_host, validate_port


OutputCallback = Callable[[str, Optional[str]], None]
DoneCallback = Callable[[], None]
StatusCallback = Callable[[dict], None]
ResultCallback = Callable[[dict], None]


STATUS_TEXT = {
    "open": "开放",
    "closed": "关闭",
    "timeout": "超时",
    "unreachable": "不可达",
    "dns_error": "解析失败",
    "cancelled": "已取消",
    "error": "错误",
}

COMMON_SERVICES = {
    20: "FTP-DATA",
    21: "FTP",
    22: "SSH",
    23: "TELNET",
    25: "SMTP",
    53: "DNS",
    67: "DHCP",
    68: "DHCP",
    80: "HTTP",
    110: "POP3",
    123: "NTP",
    135: "MSRPC",
    137: "NETBIOS",
    138: "NETBIOS",
    139: "NETBIOS",
    143: "IMAP",
    389: "LDAP",
    443: "HTTPS",
    445: "SMB",
    465: "SMTPS",
    587: "SMTP",
    636: "LDAPS",
    993: "IMAPS",
    995: "POP3S",
    1433: "MSSQL",
    1521: "ORACLE",
    3306: "MYSQL",
    3389: "RDP",
    5432: "POSTGRES",
    5900: "VNC",
    5985: "WINRM",
    5986: "WINRM-SSL",
    6379: "REDIS",
    8000: "HTTP-ALT",
    8080: "HTTP-ALT",
    8443: "HTTPS-ALT",
    9200: "ELASTIC",
    27017: "MONGODB",
}

HTTP_BANNER_PORTS = {80, 8000, 8008, 8080, 8081, 8888, 9000}


@dataclass
class ScanOptions:
    timeout_ms: int = 800
    workers: int = 128
    show_closed: bool = False
    banner_probe: bool = False


@dataclass
class PortResult:
    host: str
    resolved_ip: str
    ip_version: str
    port: int
    service: str
    status: str
    status_text: str
    latency_ms: float = 0.0
    banner: str = ""
    error: str = ""
    checked_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["latency_ms"] = round(self.latency_ms, 1)
        return data


@dataclass
class ScanStats:
    total: int = 0
    scanned: int = 0
    open_count: int = 0
    closed_count: int = 0
    timeout_count: int = 0
    unreachable_count: int = 0
    dns_error_count: int = 0
    error_count: int = 0
    cancelled_count: int = 0
    started_at: float = field(default_factory=time.perf_counter)

    def record(self, status: str, count: int = 1) -> None:
        self.scanned += count
        if status == "open":
            self.open_count += count
        elif status == "closed":
            self.closed_count += count
        elif status == "timeout":
            self.timeout_count += count
        elif status == "unreachable":
            self.unreachable_count += count
        elif status == "dns_error":
            self.dns_error_count += count
        elif status == "cancelled":
            self.cancelled_count += count
        else:
            self.error_count += count

    def snapshot(self, state: str) -> dict:
        elapsed = time.perf_counter() - self.started_at
        progress = self.scanned / self.total * 100 if self.total else 0.0
        return {
            "state": state,
            "total": self.total,
            "scanned": self.scanned,
            "open": self.open_count,
            "closed": self.closed_count,
            "timeout": self.timeout_count,
            "unreachable": self.unreachable_count,
            "dns_error": self.dns_error_count,
            "error": self.error_count,
            "cancelled": self.cancelled_count,
            "progress": progress,
            "elapsed": elapsed,
        }


class PortScanner:
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
        self.result = result or (lambda _result: None)
        self.stop_event = threading.Event()
        self.scan_thread = None
        self.executor = None
        self.last_results: list[dict] = []

    def test_connect(self, host: str, port: int, timeout: float = 1.0, options: Optional[dict] = None) -> None:
        options = self.normalize_options(options or {"timeout_ms": int(timeout * 1000), "workers": 1, "show_closed": True})
        host = validate_host(host)
        port = validate_port(port)
        self._start_scan([host], [port], options, "单端口测试")

    def start_text_scan(self, host: str, ports_text: str, timeout: float = 0.8, options: Optional[dict] = None) -> None:
        options = self.normalize_options(options or {"timeout_ms": int(timeout * 1000)})
        self.start_list_scan(host, parse_ports(ports_text), timeout=timeout, options=options)

    def start_range_scan(self, host: str, start_port: int, end_port: int, timeout: float = 0.8, options: Optional[dict] = None) -> None:
        start_port = validate_port(start_port, "起始端口")
        end_port = validate_port(end_port, "结束端口")
        if start_port > end_port:
            raise ValueError("起始端口不能大于结束端口")
        options = self.normalize_options(options or {"timeout_ms": int(timeout * 1000)})
        self.start_list_scan(host, range(start_port, end_port + 1), timeout=timeout, options=options)

    def start_list_scan(
        self,
        host: str,
        ports: Iterable[int],
        timeout: float = 0.8,
        options: Optional[dict] = None,
    ) -> None:
        host = validate_host(host)
        ports = normalize_ports(ports)
        options = self.normalize_options(options or {"timeout_ms": int(timeout * 1000)})
        self._start_scan([host], ports, options, "端口扫描")

    def start_scan(self, host: str, ports_text: str, options: Optional[dict] = None) -> None:
        host = validate_host(host)
        ports = parse_ports(ports_text)
        self._start_scan([host], ports, self.normalize_options(options), "端口扫描")

    def start_batch_scan(self, hosts_text: str, ports_text: str, options: Optional[dict] = None) -> None:
        hosts = parse_scan_hosts(hosts_text)
        ports = parse_ports(ports_text)
        self._start_scan(hosts, ports, self.normalize_options(options), "批量主机扫描")

    def _start_scan(self, hosts: list[str], ports: list[int], options: ScanOptions, title: str) -> None:
        if self.is_scanning():
            raise RuntimeError("端口扫描正在运行，请先停止当前任务")
        if not ports:
            raise ValueError("请输入至少一个端口")

        self.stop_event.clear()
        self.last_results = []
        total = len(hosts) * len(ports)
        self.output(f"开始{title}: {len(hosts)} 个目标，{len(ports)} 个端口，共 {total} 次连接\n", "muted")
        self.output(self.describe_options(options), "muted")
        self.status(ScanStats(total=total).snapshot("运行中"))
        self.scan_thread = threading.Thread(target=self._scan, args=(hosts, ports, options, title), daemon=True)
        self.scan_thread.start()

    def _scan(self, hosts: list[str], ports: list[int], options: ScanOptions, title: str) -> None:
        stats = ScanStats(total=len(hosts) * len(ports))
        resolved_hosts = []

        try:
            for host in hosts:
                if self.stop_event.is_set():
                    break
                info = resolve_host(host)
                if info["ok"]:
                    resolved_hosts.append(info)
                    suffix = "" if info["resolved_ip"] == host else f" -> {info['resolved_ip']}"
                    self.output(f"解析: {host}{suffix} ({info['ip_version']})\n", "muted")
                else:
                    self._record_host_error(host, info["error"], len(ports), stats)

            workers = min(options.workers, max(1, stats.total))
            pair_iter = iter((host_info, port) for host_info in resolved_hosts for port in ports)
            futures = {}
            exhausted = False

            self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
            while not self.stop_event.is_set() and (futures or not exhausted):
                while not self.stop_event.is_set() and not exhausted and len(futures) < workers * 2:
                    try:
                        host_info, port = next(pair_iter)
                    except StopIteration:
                        exhausted = True
                        break
                    futures[self.executor.submit(self._scan_port, host_info, port, options)] = (host_info, port)

                if not futures:
                    break

                done, _pending = concurrent.futures.wait(
                    futures,
                    timeout=0.15,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    context = futures.pop(future, None)
                    try:
                        item = future.result()
                    except Exception as exc:
                        host_info, port = context or ({"host": "", "resolved_ip": "", "ip_version": ""}, 0)
                        item = PortResult(
                            host=host_info["host"],
                            resolved_ip=host_info["resolved_ip"],
                            ip_version=host_info["ip_version"],
                            port=port,
                            service=service_name(port),
                            status="error",
                            status_text=STATUS_TEXT["error"],
                            error=str(exc),
                        )
                    self._record_result(item, stats, options)

            if self.stop_event.is_set():
                for future in futures:
                    future.cancel()
        finally:
            if self.executor:
                self.executor.shutdown(wait=False, cancel_futures=True)
                self.executor = None

            state = "已停止" if self.stop_event.is_set() else "已完成"
            self.status(stats.snapshot(state))
            self.last_results = sorted(self.last_results, key=result_sort_key)
            self._write_summary(title, stats, state)
            self.done()

    def _record_host_error(self, host: str, error: str, port_count: int, stats: ScanStats) -> None:
        item = PortResult(
            host=host,
            resolved_ip="",
            ip_version="",
            port=0,
            service="",
            status="dns_error",
            status_text=STATUS_TEXT["dns_error"],
            error=error,
        )
        stats.record("dns_error", port_count)
        self.last_results.append(item.to_dict())
        self.result(item.to_dict())
        self.output(f"{host}  解析失败: {error}\n", "warning")
        self.status(stats.snapshot("运行中"))

    def _record_result(self, item: PortResult, stats: ScanStats, options: ScanOptions) -> None:
        stats.record(item.status)
        row = item.to_dict()
        self.last_results.append(row)
        self.result(row)

        should_print = options.show_closed or item.status == "open" or item.status in {"dns_error", "error"}
        if should_print:
            tag = "success" if item.status == "open" else "warning" if item.status != "closed" else None
            latency = f"{item.latency_ms:.0f} ms" if item.latency_ms else "-"
            detail = item.banner or item.error
            detail = f"  {detail}" if detail else ""
            self.output(
                f"[{stats.scanned}/{stats.total}] {item.host}:{item.port:<5} "
                f"{item.service:<10} {item.status_text:<6} {latency}{detail}\n",
                tag,
            )

        self.status(stats.snapshot("运行中"))

    def _scan_port(self, host_info: dict, port: int, options: ScanOptions) -> PortResult:
        if self.stop_event.is_set():
            return PortResult(
                host=host_info["host"],
                resolved_ip=host_info["resolved_ip"],
                ip_version=host_info["ip_version"],
                port=port,
                service=service_name(port),
                status="cancelled",
                status_text=STATUS_TEXT["cancelled"],
            )

        started = time.perf_counter()
        timeout = options.timeout_ms / 1000
        try:
            with socket.create_connection((host_info["resolved_ip"], port), timeout=timeout) as sock:
                elapsed = (time.perf_counter() - started) * 1000
                banner = self._read_banner(sock, host_info["host"], port, timeout) if options.banner_probe else ""
                return PortResult(
                    host=host_info["host"],
                    resolved_ip=host_info["resolved_ip"],
                    ip_version=host_info["ip_version"],
                    port=port,
                    service=service_name(port),
                    status="open",
                    status_text=STATUS_TEXT["open"],
                    latency_ms=elapsed,
                    banner=banner,
                )
        except socket.timeout:
            return self._closed_result(host_info, port, "timeout", "连接超时")
        except OSError as exc:
            status = classify_os_error(exc)
            return self._closed_result(host_info, port, status, clean_error(exc))

    def _closed_result(self, host_info: dict, port: int, status: str, error: str) -> PortResult:
        return PortResult(
            host=host_info["host"],
            resolved_ip=host_info["resolved_ip"],
            ip_version=host_info["ip_version"],
            port=port,
            service=service_name(port),
            status=status,
            status_text=STATUS_TEXT.get(status, STATUS_TEXT["error"]),
            error=error,
        )

    def _read_banner(self, sock: socket.socket, host: str, port: int, timeout: float) -> str:
        try:
            sock.settimeout(min(max(timeout, 0.25), 1.0))
            if port in HTTP_BANNER_PORTS:
                request = f"HEAD / HTTP/1.0\r\nHost: {host}\r\nConnection: close\r\n\r\n"
                sock.sendall(request.encode("ascii", errors="ignore"))
            data = sock.recv(256)
        except Exception:
            return ""
        text = data.decode("utf-8", errors="replace")
        text = re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()
        return text[:160]

    def stop_scan(self) -> None:
        if not self.is_scanning():
            raise RuntimeError("当前没有正在运行的端口扫描")
        self.stop_event.set()
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
        self.output("\n正在停止端口扫描...\n", "warning")

    def export_results(self, path: str) -> None:
        if not self.last_results:
            raise RuntimeError("还没有可导出的端口扫描结果")
        fields = [
            "host",
            "resolved_ip",
            "ip_version",
            "port",
            "service",
            "status",
            "status_text",
            "latency_ms",
            "banner",
            "error",
            "checked_at",
        ]
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for row in self.last_results:
                writer.writerow({field_name: row.get(field_name, "") for field_name in fields})

    def open_ports_summary(self) -> str:
        open_items = [item for item in self.last_results if item.get("status") == "open"]
        if not open_items:
            return ""
        grouped: dict[str, list[str]] = {}
        for item in sorted(open_items, key=result_sort_key):
            grouped.setdefault(item["host"], []).append(str(item["port"]))
        return "\n".join(f"{host}: {', '.join(ports)}" for host, ports in grouped.items())

    def describe_options(self, options: ScanOptions) -> str:
        closed = "显示" if options.show_closed else "只显示开放端口"
        banner = "开启" if options.banner_probe else "关闭"
        return f"超时: {options.timeout_ms}ms  并发: {options.workers}  输出: {closed}  Banner 探测: {banner}\n\n"

    def normalize_options(self, options: Optional[dict]) -> ScanOptions:
        options = options or {}
        return ScanOptions(
            timeout_ms=clamp_int(options.get("timeout_ms", 800), 100, 60000, "超时"),
            workers=clamp_int(options.get("workers", 128), 1, 512, "并发数"),
            show_closed=bool(options.get("show_closed", False)),
            banner_probe=bool(options.get("banner_probe", False)),
        )

    def _write_summary(self, title: str, stats: ScanStats, state: str) -> None:
        snapshot = stats.snapshot(state)
        self.output(f"\n==== {title}统计 ====\n", "muted")
        self.output(
            f"状态: {state}  已扫: {snapshot['scanned']}/{snapshot['total']}  "
            f"开放: {snapshot['open']}  关闭: {snapshot['closed']}  超时: {snapshot['timeout']}  "
            f"不可达: {snapshot['unreachable']}  错误: {snapshot['error'] + snapshot['dns_error']}  "
            f"耗时: {snapshot['elapsed']:.1f}s\n",
            "success" if snapshot["open"] else "warning",
        )
        summary = self.open_ports_summary()
        if summary:
            self.output("开放端口汇总:\n" + summary + "\n", "success")

    def is_scanning(self) -> bool:
        return bool(self.scan_thread and self.scan_thread.is_alive())


def normalize_ports(ports: Iterable[int]) -> list[int]:
    unique = sorted({validate_port(port) for port in ports})
    if not unique:
        raise ValueError("请输入至少一个端口")
    return unique


def parse_scan_hosts(text: str) -> list[str]:
    raw = text.strip()
    if not raw:
        raise ValueError("请输入扫描目标")

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
            targets.append(validate_host(item))

    unique = list(dict.fromkeys(targets))
    if not unique:
        raise ValueError("没有解析到有效目标")
    return unique


def resolve_host(host: str) -> dict:
    try:
        parsed = ipaddress.ip_address(host)
        return {"ok": True, "host": host, "resolved_ip": str(parsed), "ip_version": f"IPv{parsed.version}", "error": ""}
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return {"ok": False, "host": host, "resolved_ip": "", "ip_version": "", "error": clean_error(exc)}

    addresses = []
    for family, _socktype, _proto, _canonname, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        ip = sockaddr[0]
        if ip not in addresses:
            addresses.append(ip)

    if not addresses:
        return {"ok": False, "host": host, "resolved_ip": "", "ip_version": "", "error": "没有可用的 TCP 地址"}

    selected = addresses[0]
    version = "IPv6" if ":" in selected else "IPv4"
    return {"ok": True, "host": host, "resolved_ip": selected, "ip_version": version, "error": ""}


def service_name(port: int) -> str:
    if port <= 0:
        return ""
    if port in COMMON_SERVICES:
        return COMMON_SERVICES[port]
    try:
        return socket.getservbyport(port, "tcp").upper()
    except OSError:
        return ""


def classify_os_error(exc: OSError) -> str:
    code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
    text = str(exc).lower()
    if code in {10061, 111, 61} or "refused" in text or "拒绝" in text:
        return "closed"
    if code in {10051, 10064, 10065, 101, 113} or "unreachable" in text or "不可达" in text:
        return "unreachable"
    if "timed out" in text or "超时" in text:
        return "timeout"
    return "error"


def clean_error(exc: BaseException) -> str:
    if isinstance(exc, OSError):
        return exc.strerror or str(exc)
    return str(exc)


def result_sort_key(item: dict) -> tuple:
    host_key = item.get("resolved_ip") or item.get("host") or ""
    try:
        host_key = f"{int(ipaddress.ip_address(host_key)):039d}"
    except ValueError:
        pass
    return (host_key, int(item.get("port") or 0))


def clamp_int(value, min_value: int, max_value: int, label: str) -> int:
    try:
        number = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if number < min_value or number > max_value:
        raise ValueError(f"{label}必须在 {min_value}-{max_value} 之间")
    return number
