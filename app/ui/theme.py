"""主题与样式：集中定义配色与 ttk 样式，深色主题。"""
from __future__ import annotations

from tkinter import ttk

# 配色（深色系，减少夜间刺眼）
COLOR_BG = "#1e1f22"          # 主背景
COLOR_PANEL = "#2b2d31"       # 面板背景
COLOR_NAV = "#17181a"         # 顶部导航栏
COLOR_CARD = "#313338"        # 卡片/缩略图底
COLOR_ACCENT = "#f0a500"      # 主题强调色（CS 橙黄）
COLOR_ACCENT_DARK = "#c98600"
COLOR_TEXT = "#e6e6e6"        # 主文字
COLOR_TEXT_DIM = "#9aa0a6"    # 次要文字
COLOR_BORDER = "#3f4147"
COLOR_FAB = "#f0a500"
COLOR_DANGER = "#e5534b"

FONT_APP = ("Microsoft YaHei UI", 15, "bold")
FONT_BASE = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_MAP_TAB = ("Microsoft YaHei UI", 11, "bold")
FONT_FAB = ("Segoe UI", 20, "bold")


def apply_theme(root) -> None:
    """配置 ttk 样式。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT,
                    font=FONT_BASE, bordercolor=COLOR_BORDER)
    style.configure("TFrame", background=COLOR_BG)
    style.configure("Panel.TFrame", background=COLOR_PANEL)
    style.configure("Nav.TFrame", background=COLOR_NAV)

    style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure("Panel.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT)
    style.configure("Dim.TLabel", background=COLOR_BG, foreground=COLOR_TEXT_DIM)
    style.configure("PanelDim.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT_DIM)
    style.configure("AppTitle.TLabel", background=COLOR_NAV, foreground=COLOR_ACCENT, font=FONT_APP)
    style.configure("Nav.TLabel", background=COLOR_NAV, foreground=COLOR_TEXT)

    # 按钮
    style.configure("TButton", background=COLOR_CARD, foreground=COLOR_TEXT,
                    padding=(12, 6), borderwidth=0, focuscolor=COLOR_CARD)
    style.map("TButton", background=[("active", COLOR_BORDER)],
              foreground=[("active", COLOR_TEXT)])
    style.configure("Accent.TButton", background=COLOR_ACCENT, foreground="#1a1a1a",
                    padding=(14, 7))
    style.map("Accent.TButton", background=[("active", COLOR_ACCENT_DARK)])
    style.configure("Danger.TButton", background=COLOR_DANGER, foreground="#ffffff", padding=(12, 6))
    style.map("Danger.TButton", background=[("active", "#c93c35")])

    # 输入框
    style.configure("TEntry", fieldbackground=COLOR_CARD, foreground=COLOR_TEXT,
                    insertcolor=COLOR_TEXT, bordercolor=COLOR_BORDER, padding=5)
    style.configure("TCombobox", fieldbackground=COLOR_CARD, background=COLOR_CARD,
                    foreground=COLOR_TEXT, arrowcolor=COLOR_TEXT, bordercolor=COLOR_BORDER)

    # Treeview（分类树）
    style.configure("Treeview", background=COLOR_PANEL, fieldbackground=COLOR_PANEL,
                    foreground=COLOR_TEXT, rowheight=26, borderwidth=0)
    style.configure("Treeview.Heading", background=COLOR_PANEL, foreground=COLOR_TEXT_DIM)
    style.map("Treeview", background=[("selected", COLOR_ACCENT_DARK)],
              foreground=[("selected", "#1a1a1a")])

    # 滚动条
    style.configure("Vertical.TScrollbar", background=COLOR_CARD, troughcolor=COLOR_PANEL,
                    bordercolor=COLOR_PANEL, arrowcolor=COLOR_TEXT_DIM)
    style.configure("Horizontal.TScrollbar", background=COLOR_CARD, troughcolor=COLOR_PANEL,
                    bordercolor=COLOR_PANEL, arrowcolor=COLOR_TEXT_DIM)

    # 分隔线
    style.configure("TSeparator", background=COLOR_BORDER)
