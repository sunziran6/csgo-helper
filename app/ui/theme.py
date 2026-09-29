"""主题与样式：白底黑字、浅色柔和、圆角风格。"""
from __future__ import annotations

from tkinter import ttk

# ===== 配色（浅色 / 柔和 / 现代）=====
COLOR_BG = "#f7f8fa"           # 窗口背景（近白浅灰）
COLOR_PANEL = "#ffffff"        # 面板 / 卡片白
COLOR_NAV = "#ffffff"          # 顶部导航栏白
COLOR_CARD = "#ffffff"         # 卡片白
COLOR_ACCENT = "#3b82f6"       # 主题强调（柔和蓝）
COLOR_ACCENT_DARK = "#2563eb"
COLOR_ACCENT_SOFT = "#eaf1ff"  # 选中态浅蓝背景
COLOR_TEXT = "#1f2328"         # 主文字（近黑）
COLOR_TEXT_DIM = "#8b9099"     # 次要文字（灰）
COLOR_BORDER = "#e8eaed"       # 浅边框
COLOR_INPUT_BORDER = "#cdd3db"  # 输入框边框（更明显）
COLOR_BUTTON_SOFT = "#eef1f5"   # 次级按钮浅灰填充
COLOR_HOVER = "#f0f2f5"        # 悬停浅灰
COLOR_FAB = "#3b82f6"
COLOR_DANGER = "#ef4444"
COLOR_MAP_ACTIVE_BG = "#eaf1ff"

# 圆角半径
RADIUS_CARD = 14
RADIUS_ITEM = 10
RADIUS_SMALL = 8

FONT_APP = ("Microsoft YaHei UI", 15, "bold")
FONT_BASE = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_MAP_TAB = ("Microsoft YaHei UI", 11)
FONT_MAP_TAB_ACTIVE = ("Microsoft YaHei UI", 11, "bold")
FONT_FAB = ("Segoe UI", 22, "bold")
FONT_CARD_TITLE = ("Microsoft YaHei UI", 10, "bold")


def apply_theme(root) -> None:
    """配置 ttk 样式为浅色柔和风。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT,
                    font=FONT_BASE, bordercolor=COLOR_BORDER,
                    lightcolor=COLOR_PANEL, darkcolor=COLOR_PANEL)
    style.configure("TFrame", background=COLOR_BG)
    style.configure("Panel.TFrame", background=COLOR_PANEL)
    style.configure("Nav.TFrame", background=COLOR_NAV)

    style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure("Panel.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT)
    style.configure("Dim.TLabel", background=COLOR_BG, foreground=COLOR_TEXT_DIM)
    style.configure("PanelDim.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT_DIM)
    style.configure("AppTitle.TLabel", background=COLOR_NAV, foreground=COLOR_TEXT, font=FONT_APP)
    style.configure("Nav.TLabel", background=COLOR_NAV, foreground=COLOR_TEXT)

    # 按钮：扁平、柔和、有可见描边
    style.configure("TButton", background=COLOR_BUTTON_SOFT, foreground=COLOR_TEXT,
                    padding=(14, 7), borderwidth=1, relief="flat",
                    focuscolor=COLOR_BUTTON_SOFT, bordercolor=COLOR_INPUT_BORDER)
    style.map("TButton", background=[("active", COLOR_BORDER), ("pressed", COLOR_INPUT_BORDER)],
              foreground=[("active", COLOR_TEXT)],
              bordercolor=[("active", COLOR_INPUT_BORDER)])

    style.configure("Accent.TButton", background=COLOR_ACCENT, foreground="#ffffff",
                    padding=(16, 8), borderwidth=1, relief="flat", bordercolor=COLOR_ACCENT)
    style.map("Accent.TButton", background=[("active", COLOR_ACCENT_DARK)],
              foreground=[("active", "#ffffff")], bordercolor=[("active", COLOR_ACCENT_DARK)])

    style.configure("Danger.TButton", background=COLOR_PANEL, foreground=COLOR_DANGER,
                    padding=(14, 7), borderwidth=1, relief="flat", bordercolor="#f3c9c6")
    style.map("Danger.TButton", background=[("active", "#fdecec")],
              foreground=[("active", COLOR_DANGER)], bordercolor=[("active", COLOR_DANGER)])

    # 输入框：白底 + 清晰边框
    style.configure("TEntry", fieldbackground=COLOR_PANEL, foreground=COLOR_TEXT,
                    insertcolor=COLOR_TEXT, bordercolor=COLOR_INPUT_BORDER,
                    lightcolor=COLOR_INPUT_BORDER, darkcolor=COLOR_INPUT_BORDER,
                    borderwidth=1, relief="solid", padding=7)
    style.configure("TCombobox", fieldbackground=COLOR_PANEL, background=COLOR_PANEL,
                    foreground=COLOR_TEXT, arrowcolor=COLOR_TEXT_DIM,
                    bordercolor=COLOR_INPUT_BORDER, lightcolor=COLOR_INPUT_BORDER,
                    darkcolor=COLOR_INPUT_BORDER, borderwidth=1, relief="solid", padding=6)
    style.map("TCombobox", fieldbackground=[("readonly", COLOR_PANEL)],
              foreground=[("readonly", COLOR_TEXT)],
              bordercolor=[("focus", COLOR_ACCENT), ("active", COLOR_ACCENT)])

    # 分隔线
    style.configure("TSeparator", background=COLOR_BORDER)

    # 滚动条（尽量弱化，多数场景已隐藏）
    style.configure("Vertical.TScrollbar", background=COLOR_BORDER, troughcolor=COLOR_BG,
                    bordercolor=COLOR_BG, arrowcolor=COLOR_TEXT_DIM, relief="flat")
    style.configure("Horizontal.TScrollbar", background=COLOR_BORDER, troughcolor=COLOR_BG,
                    bordercolor=COLOR_BG, arrowcolor=COLOR_TEXT_DIM, relief="flat")


# ===== 圆角绘制辅助 =====
def round_rect(canvas, x1: int, y1: int, x2: int, y2: int, r: int, **kwargs):
    """在 Canvas 上绘制平滑圆角矩形，返回 item id。kwargs 传给 create_polygon。"""
    r = max(0, min(r, (x2 - x1) // 2, (y2 - y1) // 2))
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)
