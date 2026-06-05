import ipaddress
import locale
import re
import subprocess
import sys
from typing import Iterable, List


CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


def preferred_encoding() -> str:
    return locale.getpreferredencoding(False) or "utf-8"


def run_hidden(command: List[str], timeout=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding=preferred_encoding(),
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


def popen_hidden(command: List[str]) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding=preferred_encoding(),
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )


def validate_host(value: str) -> str:
    host = value.strip()
    if not host:
        raise ValueError("请输入目标地址或域名")
    return host


def validate_ip(value: str, allow_empty: bool = False) -> str:
    ip = value.strip()
    if allow_empty and not ip:
        return ""
    try:
        ipaddress.ip_address(ip)
    except ValueError as exc:
        raise ValueError(f"IP 地址无效: {value}") from exc
    return ip


def validate_port(value, label: str = "端口") -> int:
    try:
        port = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"{label}必须在 1-65535 之间")
    return port


def parse_ports(text: str) -> List[int]:
    ports = set()
    for part in re.split(r"[,，;\s]+", text.strip()):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_raw, end_raw = part.split("-", 1)
            start = validate_port(start_raw, "起始端口")
            end = validate_port(end_raw, "结束端口")
            if start > end:
                raise ValueError("端口范围的起始值不能大于结束值")
            ports.update(range(start, end + 1))
        else:
            ports.add(validate_port(part))
    if not ports:
        raise ValueError("请输入至少一个端口")
    return sorted(ports)


def prefix_to_netmask(prefix_length) -> str:
    if prefix_length in ("", None):
        return ""
    try:
        prefix = int(prefix_length)
        return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)
    except Exception:
        return ""


def iter_hosts(prefix: str, start: int, end: int) -> Iterable[str]:
    if not prefix.endswith("."):
        raise ValueError("网段前缀必须以点号结尾，例如 192.168.1.")
    for value in (start, end):
        if value < 1 or value > 254:
            raise ValueError("主机号范围必须在 1-254 之间")
    if start > end:
        raise ValueError("起始主机号不能大于结束主机号")
    for host_id in range(start, end + 1):
        yield validate_ip(f"{prefix}{host_id}")
