import ctypes
import platform
import socket
import tkinter as tk
from tkinter import ttk

from core.ui.components import Console
from core.ui.tab_device_discovery import DeviceDiscoveryTab
from core.ui.tab_dns import DnsTab
from core.ui.tab_ip_conflict import IpConflictTab
from core.ui.tab_loop import LoopTab
from core.ui.tab_network import NetworkTab
from core.ui.tab_ping import PingTab
from core.ui.tab_telnet import TelnetTab
from core.ui.tab_tracert import TracertTab
from core.ui.theme import COLORS, apply_theme, build_app_icon


class MainUI:
    def __init__(self, root: tk.Tk, base_dir: str = ""):
        self.root = root
        self.base_dir = base_dir
        self.root.title("NetPilot 网络调试工具")
        self.root.geometry("1440x820")
        self.root.minsize(1280, 760)
        apply_theme(root)

        self.icon_image = build_app_icon()
        self.root.iconphoto(True, self.icon_image)

        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)

        self._build_topbar()

        self.sidebar = tk.Frame(root, width=260, bg=COLORS["sidebar"])
        self.sidebar.grid(row=1, column=0, rowspan=2, sticky="ns")
        self.sidebar.grid_propagate(False)

        self.content = ttk.Frame(root, style="Page.TFrame")
        self.content.grid(row=1, column=1, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self.console_shell = tk.Frame(root, width=410, bg=COLORS["bg"])
        self.console_shell.grid(row=1, column=2, sticky="nsew", padx=(0, 16), pady=(16, 0))
        self.console_shell.grid_propagate(False)
        self.console_shell.rowconfigure(0, weight=1)
        self.console_shell.columnconfigure(0, weight=1)

        self.console_panel = tk.Frame(
            self.console_shell,
            bg=COLORS["panel"],
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["border"],
            highlightthickness=1,
            bd=0,
        )
        self.console_panel.grid(row=0, column=0, sticky="nsew")
        self.console_panel.grid_propagate(False)
        self.console_panel.rowconfigure(1, weight=1)
        self.console_panel.columnconfigure(0, weight=1)
        self._build_console_panel()
        self._build_statusbar()

        self.pages = {}
        self.nav_buttons = {}
        self._build_sidebar()
        self._build_pages()
        self.show_page("network")

    def _build_topbar(self) -> None:
        bar = tk.Frame(self.root, height=44, bg=COLORS["topbar"])
        bar.grid(row=0, column=0, columnspan=3, sticky="ew")
        bar.grid_propagate(False)

        icon = tk.Label(
            bar,
            text="NP",
            bg=COLORS["primary"],
            fg="#ffffff",
            font=("Microsoft YaHei UI", 9, "bold"),
            width=3,
            height=1,
        )
        icon.pack(side="left", padx=(24, 12), pady=8)
        tk.Label(
            bar,
            text="NetPilot 网络调试工具",
            bg=COLORS["topbar"],
            fg="#ffffff",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(side="left")

    def _build_sidebar(self) -> None:
        brand = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=28, pady=(28, 28))

        logo = tk.Label(
            brand,
            text="NP",
            width=4,
            height=2,
            bg=COLORS["primary"],
            fg="#ffffff",
            font=("Microsoft YaHei UI", 18, "bold"),
        )
        logo.pack(side="left")

        title = tk.Frame(brand, bg=COLORS["sidebar"])
        title.pack(side="left", padx=12)
        tk.Label(title, text="NetPilot", bg=COLORS["sidebar"], fg="#ffffff", font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w")
        tk.Label(title, text="网络调试控制台", bg=COLORS["sidebar"], fg="#9fb4d0", font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(4, 0))

        items = [
            ("network", "◎", "网卡配置", "IP / DNS / DHCP"),
            ("dns", "◇", "DNS 诊断", "解析与服务器对比"),
            ("devices", "▦", "设备发现", "局域网资产"),
            ("ping", "⌁", "Ping 探测", "单点与批量探活"),
            ("ports", "⌕", "端口扫描", "TCP 连通性检测"),
            ("trace", "↗", "路由追踪", "跳点路径分析"),
            ("loop", "◇", "环网检测", "二层环路风险"),
            ("ip_conflict", "≠", "IP 冲突", "地址占用排查"),
        ]
        for key, icon, title, subtitle in items:
            self.nav_buttons[key] = self._nav_button(key, icon, title, subtitle)

        footer = tk.Label(
            self.sidebar,
            text="v2 重构版",
            bg=COLORS["sidebar"],
            fg="#7185a0",
            font=("Microsoft YaHei UI", 9),
        )
        footer.pack(side="bottom", anchor="w", padx=22, pady=20)

    def _nav_button(self, key: str, icon: str, title: str, subtitle: str) -> tk.Frame:
        frame = tk.Frame(self.sidebar, bg=COLORS["sidebar"], cursor="hand2")
        frame.pack(fill="x", padx=16, pady=5)

        icon_label = tk.Label(frame, text=icon, width=3, bg=COLORS["sidebar"], fg="#d9e6f7", font=("Microsoft YaHei UI", 18))
        icon_label.pack(side="left", padx=(12, 8), pady=12)

        text_frame = tk.Frame(frame, bg=COLORS["sidebar"])
        text_frame.pack(side="left", fill="x", expand=True)
        title_label = tk.Label(text_frame, text=title, bg=COLORS["sidebar"], fg="#ffffff", font=("Microsoft YaHei UI", 11, "bold"))
        title_label.pack(anchor="w")
        subtitle_label = tk.Label(text_frame, text=subtitle, bg=COLORS["sidebar"], fg="#a6b7ce", font=("Microsoft YaHei UI", 9))
        subtitle_label.pack(anchor="w", pady=(2, 0))

        widgets = (frame, icon_label, text_frame, title_label, subtitle_label)
        for widget in widgets:
            widget.bind("<Button-1>", lambda _event, page=key: self.show_page(page))
            widget.bind("<Enter>", lambda _event, widgets=widgets, page=key: self._paint_nav(widgets, page, hover=True))
            widget.bind("<Leave>", lambda _event, widgets=widgets, page=key: self._paint_nav(widgets, page, hover=False))
        frame._nav_widgets = widgets
        return frame

    def _build_pages(self) -> None:
        self.pages = {
            "network": NetworkTab(self.content, self.console),
            "dns": DnsTab(self.content, self.console),
            "ping": PingTab(self.content, self.console),
            "ports": TelnetTab(self.content, self.console),
            "trace": TracertTab(self.content, self.console),
            "loop": LoopTab(self.content, self.console),
            "ip_conflict": IpConflictTab(self.content, self.console),
            "devices": DeviceDiscoveryTab(self.content, self.console),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

    def show_page(self, key: str) -> None:
        self.active_page = key
        self.pages[key].tkraise()
        for nav_key, frame in self.nav_buttons.items():
            self._paint_nav(frame._nav_widgets, nav_key, hover=False)

    def _paint_nav(self, widgets, key: str, hover: bool) -> None:
        active = getattr(self, "active_page", None) == key
        bg = COLORS["sidebar_active"] if active else COLORS["sidebar_hover"] if hover else COLORS["sidebar"]
        fg = "#ffffff" if active or hover else "#c8d7ec"
        muted = "#dce9ff" if active else "#a6b7ce"
        for index, widget in enumerate(widgets):
            widget.configure(bg=bg)
            if isinstance(widget, tk.Label):
                widget.configure(fg=fg if index in (1, 3) else muted)

    def _build_console_panel(self) -> None:
        header = tk.Frame(self.console_panel, bg=COLORS["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 12))
        header.columnconfigure(0, weight=1)

        tk.Label(
            header,
            text="输出控制台",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Microsoft YaHei UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ttk.Button(header, text="⌫  清空", command=lambda: self.console.clear(), style="Secondary.TButton").grid(row=0, column=1, sticky="e")

        self.console = Console(self.console_panel)
        self.console.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))

    def _build_statusbar(self) -> None:
        status = tk.Frame(
            self.root,
            height=40,
            bg=COLORS["panel"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            bd=0,
        )
        status.grid(row=2, column=1, columnspan=2, sticky="ew")
        status.grid_propagate(False)
        status.columnconfigure(1, weight=1)

        left = tk.Frame(status, bg=COLORS["panel"])
        left.grid(row=0, column=0, sticky="w", padx=28, pady=9)
        self._status_dot(left)
        self._status_label(left, "就绪", color=COLORS["muted"])
        self._status_separator(left)
        self._status_label(left, "本地连接正常", color=COLORS["muted"])

        right = tk.Frame(status, bg=COLORS["panel"])
        right.grid(row=0, column=1, sticky="e", padx=28, pady=9)
        self._status_label(right, f"本机名：{socket.gethostname()}", color=COLORS["muted"])
        self._status_separator(right)
        self._status_label(right, f"操作系统：{platform.system()} {platform.release()}", color=COLORS["muted"])
        self._status_separator(right)
        self._status_label(right, "管理员权限" if self._is_admin() else "普通权限", color=COLORS["muted"])

    def _status_dot(self, parent) -> None:
        tk.Label(parent, text="●", bg=COLORS["panel"], fg="#22c55e", font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 10))

    def _status_label(self, parent, text: str, color: str) -> None:
        tk.Label(parent, text=text, bg=COLORS["panel"], fg=color, font=("Microsoft YaHei UI", 9)).pack(side="left")

    def _status_separator(self, parent) -> None:
        tk.Label(parent, text="|", bg=COLORS["panel"], fg=COLORS["border_dark"], font=("Microsoft YaHei UI", 9)).pack(side="left", padx=14)

    def _is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
