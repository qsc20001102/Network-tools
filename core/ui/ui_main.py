import tkinter as tk
from tkinter import ttk

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
        self.root.geometry("1160x720")
        apply_theme(root)

        self.icon_image = build_app_icon()
        self.root.iconphoto(True, self.icon_image)

        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.sidebar = tk.Frame(root, width=232, bg=COLORS["sidebar"])
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)

        self.content = ttk.Frame(root, style="Panel.TFrame")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self.pages = {}
        self.nav_buttons = {}
        self._build_sidebar()
        self._build_pages()
        self.show_page("network")

    def _build_sidebar(self) -> None:
        brand = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=20, pady=(24, 26))

        logo = tk.Label(
            brand,
            text="NP",
            width=4,
            height=2,
            bg=COLORS["primary"],
            fg="#ffffff",
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        logo.pack(side="left")

        title = tk.Frame(brand, bg=COLORS["sidebar"])
        title.pack(side="left", padx=12)
        tk.Label(title, text="NetPilot", bg=COLORS["sidebar"], fg="#ffffff", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        tk.Label(title, text="网络调试控制台", bg=COLORS["sidebar"], fg="#9fb4d0", font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        items = [
            ("network", "◎", "网卡配置", "IP / DNS / DHCP"),
            ("ping", "⌁", "Ping 探测", "单点与批量探活"),
            ("ports", "⌕", "端口扫描", "TCP 连通性检测"),
            ("trace", "↗", "路由追踪", "跳点路径分析"),
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
        frame.pack(fill="x", padx=14, pady=4)

        icon_label = tk.Label(frame, text=icon, width=3, bg=COLORS["sidebar"], fg="#c8d7ec", font=("Microsoft YaHei UI", 18))
        icon_label.pack(side="left", padx=(8, 6), pady=10)

        text_frame = tk.Frame(frame, bg=COLORS["sidebar"])
        text_frame.pack(side="left", fill="x", expand=True)
        title_label = tk.Label(text_frame, text=title, bg=COLORS["sidebar"], fg="#ffffff", font=("Microsoft YaHei UI", 10, "bold"))
        title_label.pack(anchor="w")
        subtitle_label = tk.Label(text_frame, text=subtitle, bg=COLORS["sidebar"], fg="#9fb4d0", font=("Microsoft YaHei UI", 8))
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
            "network": NetworkTab(self.content),
            "ping": PingTab(self.content),
            "ports": TelnetTab(self.content),
            "trace": TracertTab(self.content),
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
        muted = "#dce9ff" if active else "#9fb4d0"
        for index, widget in enumerate(widgets):
            widget.configure(bg=bg)
            if isinstance(widget, tk.Label):
                widget.configure(fg=fg if index in (1, 3) else muted)
