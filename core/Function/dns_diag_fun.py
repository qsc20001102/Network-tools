import concurrent.futures
import csv
import ipaddress
import json
import re
import subprocess
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
DEFAULT_DOMAINS = "www.baidu.com,www.qq.com"
DEFAULT_RECORD_TYPES = "A,AAAA,CNAME,MX,TXT"
PUBLIC_DNS_SERVERS = ["223.5.5.5", "114.114.114.114", "8.8.8.8"]
SUPPORTED_RECORD_TYPES = {"A", "AAAA", "CNAME", "MX", "TXT", "NS"}


@dataclass
class DnsDiagOptions:
    domains: list[str] = field(default_factory=lambda: parse_list(DEFAULT_DOMAINS))
    record_types: list[str] = field(default_factory=lambda: parse_record_types(DEFAULT_RECORD_TYPES))
    dns_servers: list[str] = field(default_factory=list)
    timeout_ms: int = 2000
    repeat_count: int = 1


@dataclass
class DnsQueryResult:
    domain: str
    record_type: str
    dns_server: str
    adapter: str
    status: str
    elapsed_ms: float
    values: str = ""
    error: str = ""
    verdict: str = ""
    attempt: int = 1
    resolver: str = "Resolve-DnsName"
    checked_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["elapsed_ms"] = round(self.elapsed_ms, 1)
        return data


class DnsDiagnostic:
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
        self.network = NetworkManager(output)
        self.stop_event = threading.Event()
        self.worker = None
        self.last_results: list[dict] = []
        self.last_summary = ""
        self.local_dns_servers: set[str] = set()

    def get_adapter_choices(self) -> list[str]:
        adapters = self._active_adapters(self.network.get_network_info())
        return [ALL_ADAPTERS] + [adapter["name"] for adapter in adapters]

    def get_adapter_choices_and_default_dns(self) -> tuple[list[str], str]:
        adapters = self._active_adapters(self.network.get_network_info())
        choices = [ALL_ADAPTERS] + [adapter["name"] for adapter in adapters]
        servers = collect_adapter_dns(adapters)
        default_dns = ",".join(list(dict.fromkeys(servers + PUBLIC_DNS_SERVERS)))
        return choices, default_dns

    def default_dns_servers(self, adapter_name: str = ALL_ADAPTERS) -> str:
        adapters = self._select_dns_source_adapters(adapter_name)
        servers = collect_adapter_dns(adapters)
        return ",".join(list(dict.fromkeys(servers + PUBLIC_DNS_SERVERS)))

    def repair_abnormal_dns(self, adapter_name: str = ALL_ADAPTERS) -> dict:
        if self.is_running():
            raise RuntimeError("DNS 诊断正在运行，请先停止当前任务")

        adapters = self._select_repair_adapters(adapter_name)
        if not adapters:
            raise ValueError("没有找到可修复的活动网卡")

        servers = PUBLIC_DNS_SERVERS[:2]
        for adapter in adapters:
            self.network.set_dns_servers(adapter["name"], servers)
        self.network.flush_dns_cache()
        return {"adapters": [adapter["name"] for adapter in adapters], "servers": servers}

    def start_diagnosis(self, adapter_name: str = ALL_ADAPTERS, options: Optional[dict] = None) -> None:
        if self.is_running():
            raise RuntimeError("DNS 诊断正在运行，请先停止当前任务")

        adapters = self._select_adapters(adapter_name)
        if not adapters:
            raise ValueError("没有找到可用于 DNS 诊断的活动网卡")

        diag_options = self.normalize_options(options, adapters)
        tasks = build_tasks(diag_options)
        if not tasks:
            raise ValueError("没有可执行的 DNS 查询任务")

        self.stop_event.clear()
        self.last_results = []
        self.last_summary = ""
        self.local_dns_servers = set(collect_adapter_dns(adapters))
        current_dns = ",".join(sorted(self.local_dns_servers)) or "未读取到本机 DNS"
        self.output(
            f"开始 DNS 诊断: {adapter_name or ALL_ADAPTERS}，"
            f"域名 {len(diag_options.domains)} 个，类型 {len(diag_options.record_types)} 个，"
            f"DNS {len(diag_options.dns_servers)} 个，重复 {diag_options.repeat_count} 次\n",
            "muted",
        )
        self.status(self._status("查询中", current_dns, len(tasks), 0, 0, 0))
        self.worker = threading.Thread(
            target=self._run_diagnosis,
            args=(adapter_name or ALL_ADAPTERS, current_dns, tasks, diag_options),
            daemon=True,
        )
        self.worker.start()

    def _run_diagnosis(self, adapter_name: str, current_dns: str, tasks: list[dict], options: DnsDiagOptions) -> None:
        started = time.perf_counter()
        completed = 0
        abnormal = 0

        try:
            workers = min(8, max(1, len(tasks)))
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(self.query_one, adapter_name, task, options.timeout_ms): task
                    for task in tasks
                }
                for future in concurrent.futures.as_completed(futures):
                    if self.stop_event.is_set():
                        for item in futures:
                            item.cancel()
                        break
                    completed += 1
                    try:
                        row = future.result().to_dict()
                    except Exception as exc:
                        task = futures[future]
                        row = DnsQueryResult(
                            domain=task["domain"],
                            record_type=task["record_type"],
                            dns_server=task["dns_server"],
                            adapter=adapter_name,
                            status="失败",
                            elapsed_ms=0,
                            error=str(exc),
                            verdict="查询失败，建议与其它 DNS 对比",
                            attempt=task["attempt"],
                        ).to_dict()
                    self.last_results.append(row)
                    if row.get("status") != "正常":
                        abnormal += 1
                    self.result(row)
                    self.status(self._status("查询中", current_dns, len(tasks), completed, abnormal, time.perf_counter() - started))

            self.last_summary = build_summary(self.last_results, self.local_dns_servers, stopped=self.stop_event.is_set())
            if self.stop_event.is_set():
                self.output("\nDNS 诊断已停止\n", "warning")
            else:
                self.output("\nDNS 诊断完成\n", "success")
            self.output(self.last_summary + "\n", "success")
            self.status(
                self._status(
                    "已停止" if self.stop_event.is_set() else "已完成",
                    current_dns,
                    len(tasks),
                    completed,
                    abnormal,
                    time.perf_counter() - started,
                )
            )
        except Exception as exc:
            self.output(f"\nDNS 诊断失败: {exc}\n", "error")
            self.status(self._status("失败", current_dns, len(tasks), completed, abnormal, time.perf_counter() - started))
        finally:
            self.done()

    def query_one(self, adapter_name: str, task: dict, timeout_ms: int) -> DnsQueryResult:
        if self.stop_event.is_set():
            return DnsQueryResult(
                domain=task["domain"],
                record_type=task["record_type"],
                dns_server=task["dns_server"],
                adapter=adapter_name,
                status="失败",
                elapsed_ms=0,
                error="任务已停止",
                verdict="任务停止，结果不完整",
                attempt=task["attempt"],
            )

        started = time.perf_counter()
        domain = task["domain"]
        record_type = task["record_type"]
        dns_server = task["dns_server"]
        try:
            values = resolve_with_powershell(domain, record_type, dns_server, timeout_ms)
            resolver = "Resolve-DnsName"
        except Exception as ps_error:
            try:
                values = resolve_with_nslookup(domain, record_type, dns_server, timeout_ms)
                resolver = "nslookup"
            except Exception as ns_error:
                elapsed = (time.perf_counter() - started) * 1000
                error = classify_error(f"{ps_error}; {ns_error}")
                return DnsQueryResult(
                    domain=domain,
                    record_type=record_type,
                    dns_server=dns_server,
                    adapter=adapter_name,
                    status="失败",
                    elapsed_ms=elapsed,
                    error=error,
                    verdict=verdict_for_error(error),
                    attempt=task["attempt"],
                    resolver="fallback",
                )

        elapsed = (time.perf_counter() - started) * 1000
        if values:
            return DnsQueryResult(
                domain=domain,
                record_type=record_type,
                dns_server=dns_server,
                adapter=adapter_name,
                status="正常",
                elapsed_ms=elapsed,
                values="; ".join(values),
                verdict="解析成功",
                attempt=task["attempt"],
                resolver=resolver,
            )
        return DnsQueryResult(
            domain=domain,
            record_type=record_type,
            dns_server=dns_server,
            adapter=adapter_name,
            status="无记录",
            elapsed_ms=elapsed,
            verdict="未返回该类型记录，建议结合其它记录类型判断",
            attempt=task["attempt"],
            resolver=resolver,
        )

    def stop_diagnosis(self) -> None:
        if not self.is_running():
            raise RuntimeError("当前没有正在运行的 DNS 诊断")
        self.stop_event.set()
        self.output("\n正在停止 DNS 诊断...\n", "warning")

    def export_results(self, path: str) -> None:
        if not self.last_results:
            raise RuntimeError("还没有可导出的 DNS 诊断结果")
        fields = [
            "domain",
            "record_type",
            "dns_server",
            "adapter",
            "status",
            "elapsed_ms",
            "values",
            "error",
            "verdict",
            "attempt",
            "resolver",
            "checked_at",
        ]
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for row in self.last_results:
                writer.writerow({field_name: row.get(field_name, "") for field_name in fields})

    def copy_summary(self) -> str:
        return self.last_summary or "\n".join(
            f"{row.get('domain', '')}\t{row.get('record_type', '')}\t{row.get('dns_server', '')}\t"
            f"{row.get('status', '')}\t{row.get('elapsed_ms', '')}ms\t{row.get('values', '') or row.get('error', '')}"
            for row in self.last_results
        )

    def normalize_options(self, options: Optional[dict], adapters: list[dict]) -> DnsDiagOptions:
        options = options or {}
        domains = parse_list(str(options.get("domains", "")).strip() or DEFAULT_DOMAINS)
        record_types = parse_record_types(str(options.get("record_types", "")).strip() or DEFAULT_RECORD_TYPES)
        dns_servers = parse_dns_servers(str(options.get("dns_servers", "")).strip())
        if not dns_servers:
            dns_servers = collect_adapter_dns(adapters) + PUBLIC_DNS_SERVERS
        dns_servers = list(dict.fromkeys(dns_servers))
        return DnsDiagOptions(
            domains=domains,
            record_types=record_types,
            dns_servers=dns_servers,
            timeout_ms=clamp_int(options.get("timeout_ms", 2000), 300, 10000, "超时"),
            repeat_count=clamp_int(options.get("repeat_count", 1), 1, 5, "重复次数"),
        )

    def _select_adapters(self, adapter_name: str) -> list[dict]:
        adapters = self._active_adapters(self.network.get_network_info())
        if not adapter_name or adapter_name == ALL_ADAPTERS:
            return adapters
        return [adapter for adapter in adapters if adapter.get("name") == adapter_name]

    def _select_dns_source_adapters(self, adapter_name: str) -> list[dict]:
        adapters = self._active_adapters(self.network.get_network_info())
        if not adapter_name or adapter_name == ALL_ADAPTERS:
            return adapters
        return [adapter for adapter in adapters if adapter.get("name") == adapter_name]

    def _select_repair_adapters(self, adapter_name: str) -> list[dict]:
        adapters = self._select_adapters(adapter_name)
        if adapter_name and adapter_name != ALL_ADAPTERS:
            return adapters
        return [adapter for adapter in adapters if adapter.get("gateway") or adapter.get("dns1") or adapter.get("dns2")]

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

    def _status(self, state: str, current_dns: str, total: int, completed: int, abnormal: int, elapsed: float) -> dict:
        return {
            "state": state,
            "current_dns": current_dns,
            "total": total,
            "completed": completed,
            "abnormal": abnormal,
            "elapsed": elapsed,
        }

    def is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())


def build_tasks(options: DnsDiagOptions) -> list[dict]:
    tasks = []
    for attempt in range(1, options.repeat_count + 1):
        for domain in options.domains:
            for record_type in options.record_types:
                for dns_server in options.dns_servers:
                    tasks.append(
                        {
                            "domain": domain,
                            "record_type": record_type,
                            "dns_server": dns_server,
                            "attempt": attempt,
                        }
                    )
    return tasks


def resolve_with_powershell(domain: str, record_type: str, dns_server: str, timeout_ms: int) -> list[str]:
    script = f"""
$ErrorActionPreference = "Stop"
$items = Resolve-DnsName -Name {ps_quote(domain)} -Type {ps_quote(record_type)} -Server {ps_quote(dns_server)} -DnsOnly -ErrorAction Stop
$items | Select-Object Name,Type,QueryType,IPAddress,NameHost,NameExchange,Preference,Strings,CharacterStrings | ConvertTo-Json -Depth 5 -Compress
"""
    result = run_hidden(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout=max(3, timeout_ms / 1000 + 2),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or "Resolve-DnsName 查询失败")
    data = extract_json(result.stdout)
    if isinstance(data, dict):
        data = [data]
    return normalize_record_values(data)


def resolve_with_nslookup(domain: str, record_type: str, dns_server: str, timeout_ms: int) -> list[str]:
    seconds = max(1, int(round(timeout_ms / 1000)))
    try:
        result = run_hidden(["nslookup", f"-timeout={seconds}", f"-type={record_type}", domain, dns_server], timeout=seconds + 3)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("nslookup 查询超时") from exc
    output = result.stdout.strip()
    if result.returncode != 0 and not output:
        raise RuntimeError("nslookup 查询失败")
    if is_nslookup_error(output):
        raise RuntimeError(output)
    return parse_nslookup_output(output, record_type)


def normalize_record_values(items) -> list[str]:
    values = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if item.get("IPAddress"):
            values.append(str(item["IPAddress"]))
        if item.get("NameHost"):
            values.append(str(item["NameHost"]).rstrip("."))
        if item.get("NameExchange"):
            exchange = str(item["NameExchange"]).rstrip(".")
            preference = item.get("Preference")
            values.append(f"{preference} {exchange}" if preference not in ("", None) else exchange)
        for key in ("Strings", "CharacterStrings"):
            text = item.get(key)
            if isinstance(text, list):
                values.append(" ".join(str(part) for part in text))
            elif text:
                values.append(str(text))
    return sorted(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def parse_nslookup_output(output: str, record_type: str) -> list[str]:
    values = []
    answer_started = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if not line:
            continue
        if lower.startswith("name:") or line.startswith("名称:") or "canonical name =" in lower or "mail exchanger =" in lower:
            answer_started = True
        if record_type in {"A", "AAAA"}:
            match = re.search(r"(?:address|addresses|地址)\s*:\s*([0-9a-fA-F:.]+)", line, re.IGNORECASE)
            if match and answer_started:
                value = match.group(1)
                if ":" in value or "." in value:
                    values.append(value)
        elif record_type == "CNAME":
            match = re.search(r"canonical name\s*=\s*(.+)$", line, re.IGNORECASE)
            if match:
                values.append(match.group(1).strip().rstrip("."))
        elif record_type == "MX":
            match = re.search(r"mail exchanger\s*=\s*(.+)$", line, re.IGNORECASE)
            if match:
                values.append(match.group(1).strip().rstrip("."))
        elif record_type == "TXT":
            match = re.search(r'text\s*=\s*"?(.*?)"?$', line, re.IGNORECASE)
            if match:
                values.append(match.group(1).strip())
        elif record_type == "NS":
            match = re.search(r"nameserver\s*=\s*(.+)$", line, re.IGNORECASE)
            if match:
                values.append(match.group(1).strip().rstrip("."))
        if answer_started and record_type in {"A", "AAAA"}:
            bare_ip = re.match(r"^([0-9a-fA-F:.]+)$", line)
            if bare_ip:
                values.append(bare_ip.group(1))
    return sorted(dict.fromkeys(value for value in values if value))


def build_summary(rows: list[dict], local_dns_servers: set[str], stopped: bool = False) -> str:
    if stopped:
        return "DNS 诊断已停止，当前结果仅代表已完成查询。"
    if not rows:
        return "DNS 诊断未产生结果。"

    total = len(rows)
    ok_rows = [row for row in rows if row.get("status") == "正常"]
    failed_rows = [row for row in rows if row.get("status") != "正常"]
    avg_elapsed = sum(float(row.get("elapsed_ms") or 0) for row in ok_rows) / len(ok_rows) if ok_rows else 0
    lines = [
        "==== DNS 诊断摘要 ====",
        f"查询总数: {total}  成功: {len(ok_rows)}  异常: {len(failed_rows)}  成功平均耗时: {avg_elapsed:.1f} ms",
    ]

    for (domain, record_type), group in group_by_domain_type(rows).items():
        local = [row for row in group if row.get("dns_server") in local_dns_servers]
        public = [row for row in group if row.get("dns_server") not in local_dns_servers]
        local_ok = any(row.get("status") == "正常" for row in local)
        public_ok = any(row.get("status") == "正常" for row in public)
        any_ok = any(row.get("status") == "正常" for row in group)
        if local and not local_ok and public_ok:
            lines.append(f"{domain} {record_type}: 本机 DNS 失败但对比 DNS 成功，本机 DNS 服务器疑似异常。")
        elif not any_ok:
            lines.append(f"{domain} {record_type}: 所有 DNS 均未成功，可能域名不存在、网络不可达或上游 DNS 异常。")
        elif values_are_inconsistent(group):
            lines.append(f"{domain} {record_type}: 不同 DNS 返回结果不一致，可能存在 CDN、缓存、污染或策略差异。")

    if len(lines) == 2:
        lines.append("未发现明显 DNS 异常；如故障偶发，建议增加重复次数复测。")
    return "\n".join(lines)


def group_by_domain_type(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        grouped.setdefault((row.get("domain", ""), row.get("record_type", "")), []).append(row)
    return grouped


def values_are_inconsistent(rows: list[dict]) -> bool:
    value_sets = {
        tuple(sorted(value.strip() for value in str(row.get("values", "")).split(";") if value.strip()))
        for row in rows
        if row.get("status") == "正常" and row.get("values")
    }
    return len(value_sets) > 1


def collect_adapter_dns(adapters: list[dict]) -> list[str]:
    servers = []
    for adapter in adapters:
        for key in ("dns1", "dns2"):
            value = str(adapter.get(key, "")).strip()
            if value and is_ip_address(value):
                servers.append(value)
    return list(dict.fromkeys(servers))


def parse_list(text: str, max_items: int = 20) -> list[str]:
    items = [item.strip() for item in re.split(r"[,，;\s]+", text.strip()) if item.strip()]
    return list(dict.fromkeys(items))[:max_items]


def parse_record_types(text: str) -> list[str]:
    values = [item.upper() for item in parse_list(text, 10)]
    invalid = [item for item in values if item not in SUPPORTED_RECORD_TYPES]
    if invalid:
        raise ValueError("不支持的 DNS 记录类型: " + ", ".join(invalid))
    return values


def parse_dns_servers(text: str) -> list[str]:
    servers = []
    for item in parse_list(text, 12):
        if not is_ip_address(item):
            raise ValueError(f"DNS 服务器必须是 IP 地址: {item}")
        servers.append(item)
    return list(dict.fromkeys(servers))


def classify_error(text: str) -> str:
    clean = compact_text(text)
    lower = clean.lower()
    if "timed out" in lower or "timeout" in lower or "超时" in clean:
        return "查询超时"
    if "non-existent" in lower or "nxdomain" in lower or "不存在" in clean:
        return "域名或记录不存在"
    if "refused" in lower or "拒绝" in clean:
        return "DNS 服务器拒绝查询"
    if "server failed" in lower or "servfail" in lower:
        return "上游 DNS 返回失败"
    return clean[:240] if clean else "解析失败"


def verdict_for_error(error: str) -> str:
    if "超时" in error:
        return "查询超时，可能 DNS 服务器不可达或网络阻塞"
    if "不存在" in error:
        return "未查询到该记录，建议与其它 DNS 或记录类型对比"
    if "拒绝" in error:
        return "DNS 服务器拒绝查询，可能存在策略限制"
    return "解析失败，建议与其它 DNS 对比"


def is_nslookup_error(output: str) -> bool:
    lower = output.lower()
    return any(token in lower for token in ("timed out", "can't find", "non-existent", "servfail", "refused"))


def is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def extract_json(text: str):
    output = text.strip()
    if not output:
        return []
    json_start = min([idx for idx in (output.find("["), output.find("{")) if idx >= 0], default=-1)
    if json_start < 0:
        return []
    data = json.loads(output[json_start:])
    return [] if data is None else data


def ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def clamp_int(value, min_value: int, max_value: int, label: str) -> int:
    try:
        number = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if number < min_value or number > max_value:
        raise ValueError(f"{label}必须在 {min_value}-{max_value} 之间")
    return number
