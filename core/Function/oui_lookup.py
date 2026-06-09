import csv
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional


OutputCallback = Callable[[str, Optional[str]], None]


IEEE_OUI_SOURCES = [
    ("MA-L", "https://standards-oui.ieee.org/oui/oui.csv"),
    ("MA-M", "https://standards-oui.ieee.org/oui28/mam.csv"),
    ("MA-S", "https://standards-oui.ieee.org/oui36/oui36.csv"),
]
UPDATE_INTERVAL_SECONDS = 7 * 24 * 60 * 60
UNKNOWN_VENDOR = "未知"
LOCAL_ADMIN_VENDOR = "随机/本地管理地址"


class OuiVendorLookup:
    def __init__(self, fallback_map: Optional[dict[str, str]] = None):
        self.fallback_map = {normalize_prefix(key): value for key, value in (fallback_map or {}).items()}
        self.vendors: dict[str, str] = {}
        self.source = "未加载"
        self.updated_at = 0.0
        self._loaded = False
        self._update_started = False
        self._lock = threading.RLock()

    def load(self, output: Optional[OutputCallback] = None) -> None:
        with self._lock:
            if self._loaded:
                return

            loaded = self._load_json_file(cache_file())
            if loaded:
                self.vendors, self.updated_at = loaded
                self.source = "本地缓存"
                self._loaded = True
                write(output, f"已加载 OUI 厂商缓存：{len(self.vendors)} 条\n", "muted")
                return

            loaded = self._load_json_file(seed_file())
            if loaded:
                self.vendors, self.updated_at = loaded
                self.source = "离线内置"
                self._loaded = True
                write(output, f"已加载离线 OUI 厂商库：{len(self.vendors)} 条\n", "muted")
                return

            self.vendors = dict(self.fallback_map)
            self.updated_at = 0.0
            self.source = "内置兜底"
            self._loaded = True
            write(output, f"已加载内置 OUI 兜底表：{len(self.vendors)} 条\n", "muted")

    def lookup(self, mac: str) -> str:
        self.load()
        normalized = normalize_mac_hex(mac)
        if len(normalized) < 6:
            return UNKNOWN_VENDOR

        with self._lock:
            for prefix_length in (9, 7, 6):
                if len(normalized) >= prefix_length:
                    vendor = self.vendors.get(normalized[:prefix_length])
                    if vendor:
                        return vendor
                fallback = self.fallback_map.get(normalized[:prefix_length])
                if fallback:
                    return fallback

        if is_locally_administered(normalized):
            return LOCAL_ADMIN_VENDOR
        return UNKNOWN_VENDOR

    def update_if_stale_async(self, output: Optional[OutputCallback] = None) -> None:
        self.load(output)
        with self._lock:
            if self._update_started or not self.is_stale():
                return
            self._update_started = True

        thread = threading.Thread(target=self._update_worker, args=(output,), daemon=True)
        thread.start()

    def update_now(self, output: Optional[OutputCallback] = None) -> bool:
        self.load(output)
        vendors = download_ieee_oui()
        if not vendors:
            raise RuntimeError("未下载到有效 OUI 数据")
        payload = {"updated_at": time.time(), "vendors": vendors}
        save_json_atomic(cache_file(), payload)
        with self._lock:
            self.vendors = vendors
            self.updated_at = float(payload["updated_at"])
            self.source = "联网更新"
        write(output, f"OUI 厂商库已更新：{len(vendors)} 条\n", "success")
        return True

    def is_stale(self) -> bool:
        if not self.updated_at:
            return True
        return time.time() - self.updated_at > UPDATE_INTERVAL_SECONDS

    def _update_worker(self, output: Optional[OutputCallback]) -> None:
        try:
            self.update_now(output)
        except Exception as exc:
            write(output, f"OUI 厂商库更新失败，继续使用离线库：{exc}\n", "warning")

    def _load_json_file(self, path: Path) -> Optional[tuple[dict[str, str], float]]:
        try:
            if not path.exists():
                return None
            with path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
            raw_vendors = payload.get("vendors", {})
            vendors = {
                normalize_prefix(prefix): compact_vendor_name(vendor)
                for prefix, vendor in raw_vendors.items()
                if normalize_prefix(prefix) and compact_vendor_name(vendor)
            }
            if not vendors:
                return None
            return vendors, float(payload.get("updated_at") or 0)
        except Exception:
            return None


def download_ieee_oui() -> dict[str, str]:
    vendors: dict[str, str] = {}
    for _registry, url in IEEE_OUI_SOURCES:
        text = download_text(url)
        vendors.update(parse_ieee_csv(text))
    return vendors


def download_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "NetPilot/1.0 (+https://standards.ieee.org/develop/regauth/)",
            "Accept": "text/csv,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8-sig", errors="replace")


def parse_ieee_csv(text: str) -> dict[str, str]:
    rows = csv.DictReader(text.splitlines())
    vendors: dict[str, str] = {}
    for row in rows:
        prefix = normalize_prefix(row.get("Assignment", ""))
        vendor = compact_vendor_name(row.get("Organization Name", ""))
        if prefix and vendor:
            vendors[prefix] = vendor
    return vendors


def normalize_prefix(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", str(value or "")).upper()
    if len(cleaned) in (6, 7, 9):
        return cleaned
    return ""


def normalize_mac_hex(value: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", str(value or "")).upper()


def compact_vendor_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_locally_administered(mac_hex: str) -> bool:
    try:
        return bool(int(mac_hex[:2], 16) & 0x02)
    except Exception:
        return False


def cache_file() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), "AppData", "Local")
    return Path(base) / "NetPilot" / "oui_vendors.json"


def seed_file() -> Path:
    candidates = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "assets" / "oui_vendors_seed.json")
    candidates.append(Path(__file__).resolve().parents[2] / "assets" / "oui_vendors_seed.json")
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "assets" / "oui_vendors_seed.json")
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def save_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, separators=(",", ":"))
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def write(output: Optional[OutputCallback], text: str, tag: Optional[str] = None) -> None:
    if output:
        output(text, tag)
