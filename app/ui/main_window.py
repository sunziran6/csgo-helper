"""主窗口：顶部导航 + 地图横栏 + 左分类栏 + 右展示区 + 右下角悬浮加号。

浅色柔和风：白底黑字、圆角卡片、无展开箭头、无滚动条（仅滚轮滑动）。
"""
from __future__ import annotations

import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import config
from ..context import AppContext
from ..logging_setup import get_logger
from ..services.map_service import ServiceError
from . import add_page, theme as T
from .image_viewer import open_image_viewer

log = get_logger("aim.ui")

DIRECT = "direct"  # 「地图直属」分类的键


# ============================================================
# 通用滚动区域：仅滚轮滑动，无滚动条
# ============================================================
class ScrollArea(tk.Frame):
    def __init__(self, parent, horizontal: bool = False, bg: str = None):
        bg = bg if bg is not None else T.COLOR_BG
        super().__init__(parent, bg=bg)
        self.horizontal = horizontal
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        # 进入时接管滚轮，离开时释放
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _on_inner(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e):
        if not self.horizontal:
            self.canvas.itemconfigure(self._win, width=e.width)

    def _bind_wheel(self, _e=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")

    def _unbind_wheel(self, _e=None):
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

    def _on_wheel(self, event):
        step = -1 if event.delta > 0 else 1
        if self.horizontal:
            self.canvas.xview_scroll(step * 2, "units")
        else:
            self.canvas.yview_scroll(step * 2, "units")

    def scroll_to_top(self):
        self.canvas.yview_moveto(0)


class MainWindow:
    def __init__(self, root: tk.Tk, ctx: AppContext):
        self.root = root
        self.ctx = ctx
        self.svc = ctx.maps

        self.current_map: dict | None = None
        self.current_category_id = None      # int | DIRECT | None
        self.current_spot: dict | None = None

        # 分类栏状态
        self.expanded: set = set()           # 展开的分类键
        self.selection = None                # ("cat", key) / ("spot", id)
        self._cat_rows: dict = {}            # key -> 行内可高亮 widget 列表
        self._spot_rows: dict = {}           # spot_id -> widget 列表
        self._map_tabs: dict = {}            # map_id -> canvas
        self._thumb_refs: list = []
        self._search_job = None

        self._setup_window()
        self._build_ui()
        self.refresh_maps(select_first=True)

    # ================= 窗口与骨架 =================
    def _setup_window(self) -> None:
        self.root.title(config.APP_NAME)
        self.root.geometry("1120x740")
        self.root.minsize(900, 580)
        self.root.configure(bg=T.COLOR_BG)

    def _build_ui(self) -> None:
        self._build_nav()
        self._build_map_bar()
        self._build_main_area()
        self._build_statusbar()
        self._build_fab()
        self.root.bind("<Configure>", lambda e: self._reposition_fab())

    # ---------- ① 顶部导航栏 ----------
    def _build_nav(self) -> None:
        nav = tk.Frame(self.root, bg=T.COLOR_NAV, height=60)
        nav.pack(fill="x", side="top")
        nav.pack_propagate(False)

        tk.Label(nav, text="CS:GO 瞄点记录", bg=T.COLOR_NAV, fg=T.COLOR_TEXT,
                 font=T.FONT_APP).pack(side="left", padx=22)
        # 底部细分隔线
        tk.Frame(self.root, bg=T.COLOR_BORDER, height=1).pack(fill="x", side="top")

        right = tk.Frame(nav, bg=T.COLOR_NAV)
        right.pack(side="right", padx=18)

        self._flat_button(right, "设置", self._open_settings).pack(side="right", padx=(10, 0))
        self._flat_button(right, "导入", self._on_import).pack(side="right", padx=(10, 0))
        self._flat_button(right, "导出", self._on_export).pack(side="right", padx=(10, 0))

        self.scope_var = tk.StringVar(value="当前地图")
        scope = ttk.Combobox(right, textvariable=self.scope_var, width=9, state="readonly",
                             values=["全部地图", "当前地图", "当前分类"])
        scope.pack(side="right", padx=(10, 0))

        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(right, textvariable=self.search_var, width=20)
        self.search_entry.pack(side="right", padx=(10, 0))
        self.search_entry.bind("<KeyRelease>", self._on_search_key)
        tk.Label(right, text="🔍", bg=T.COLOR_NAV, fg=T.COLOR_TEXT_DIM,
                 font=T.FONT_BASE).pack(side="right")

        self.root.bind("<Control-f>", lambda e: self.search_entry.focus_set())

    def _flat_button(self, parent, text, cmd) -> tk.Label:
        """扁平文字按钮（悬停变色）。"""
        lbl = tk.Label(parent, text=text, bg=T.COLOR_NAV, fg=T.COLOR_TEXT_DIM,
                       font=T.FONT_BASE, cursor="hand2", padx=8, pady=4)
        lbl.bind("<Enter>", lambda e: lbl.configure(fg=T.COLOR_ACCENT))
        lbl.bind("<Leave>", lambda e: lbl.configure(fg=T.COLOR_TEXT_DIM))
        lbl.bind("<Button-1>", lambda e: cmd())
        return lbl

    # ---------- ② 地图横栏（圆角标签 + 横向滚轮）----------
    def _build_map_bar(self) -> None:
        bar = tk.Frame(self.root, bg=T.COLOR_BG, height=62)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        self.map_area = ScrollArea(bar, horizontal=True, bg=T.COLOR_BG)
        self.map_area.pack(fill="both", expand=True, padx=14, pady=8)
        self.map_inner = self.map_area.inner

    def _make_map_tab(self, m: dict, active: bool) -> tk.Canvas:
        text = m["name"]
        width = max(72, 26 + 13 * len(text))
        h = 36
        cv = tk.Canvas(self.map_inner, width=width, height=h, bg=T.COLOR_BG,
                       highlightthickness=0, bd=0, cursor="hand2")
        fill = T.COLOR_ACCENT_SOFT if active else T.COLOR_PANEL
        outline = T.COLOR_ACCENT if active else T.COLOR_BORDER
        fg = T.COLOR_ACCENT_DARK if active else T.COLOR_TEXT
        T.round_rect(cv, 1, 1, width - 1, h - 1, 18, fill=fill, outline=outline, width=1)
        cv.create_text(width // 2, h // 2, text=text,
                       font=T.FONT_MAP_TAB_ACTIVE if active else T.FONT_MAP_TAB, fill=fg)
        cv.pack(side="left", padx=5)

        mid = m["id"]
        cv.bind("<Button-1>", lambda e, i=mid: self._select_map(i))
        cv.bind("<Button-3>", lambda e, i=mid: self._on_map_right_click(e, i))
        if not active:
            cv.bind("<Enter>", lambda e, c=cv: c.itemconfigure("all", outline=T.COLOR_ACCENT))
            cv.bind("<Leave>", lambda e, c=cv: c.itemconfigure("all", outline=T.COLOR_BORDER))
        return cv

    def refresh_maps(self, select_first: bool = False) -> None:
        for w in self.map_inner.winfo_children():
            w.destroy()
        self._map_tabs.clear()

        maps = self.svc.list_maps()
        if not maps:
            tk.Label(self.map_inner, text="暂无地图，点击右下角 ＋ 新建地图",
                     bg=T.COLOR_BG, fg=T.COLOR_TEXT_DIM, font=T.FONT_BASE).pack(padx=16, pady=10)
            self.current_map = None
            self._refresh_tree()
            self._refresh_display()
            self._update_status()
            return

        active_id = None
        if select_first or (self.current_map and self.current_map["id"] not in [m["id"] for m in maps]):
            active_id = maps[0]["id"]
        elif self.current_map:
            active_id = self.current_map["id"]

        for m in maps:
            tab = self._make_map_tab(m, m["id"] == active_id)
            self._map_tabs[m["id"]] = tab

        if active_id:
            self._select_map(active_id)

    def _select_map(self, map_id: int) -> None:
        self.current_map = self.svc.dao.maps.get(map_id)
        self.current_category_id = None
        self.current_spot = None
        self.expanded.clear()
        self.selection = None
        # 重绘标签高亮
        for m in self.svc.list_maps():
            tab = self._map_tabs.get(m["id"])
            if not tab:
                continue
            active = m["id"] == map_id
            tab.destroy()
            new_tab = self._make_map_tab(m, active)
            self._map_tabs[m["id"]] = new_tab
        # 重新按顺序 pack（destroy 后顺序丢失）
        self._repack_map_tabs()
        self._refresh_tree()
        self._refresh_display()
        self._update_status()

    def _repack_map_tabs(self) -> None:
        for w in self.map_inner.winfo_children():
            w.pack_forget()
        for m in self.svc.list_maps():
            tab = self._map_tabs.get(m["id"])
            if tab:
                tab.pack(side="left", padx=5)

    def _on_map_right_click(self, event, map_id: int) -> None:
        self._select_map(map_id)
        menu = self._popup_menu()
        menu.add_command(label="重命名地图", command=lambda: self._rename_map(map_id))
        menu.add_command(label="导出此地图", command=lambda: self._export_single_map(map_id))
        menu.add_separator()
        menu.add_command(label="删除地图", command=lambda: self._delete_map(map_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _popup_menu(self) -> tk.Menu:
        return tk.Menu(self.root, tearoff=0, bg=T.COLOR_PANEL, fg=T.COLOR_TEXT,
                       activebackground=T.COLOR_ACCENT_SOFT, activeforeground=T.COLOR_ACCENT_DARK,
                       relief="flat", bd=0, font=T.FONT_BASE)

    def _export_single_map(self, map_id: int) -> None:
        default_name = f"aim_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}.zip"
        path = filedialog.asksaveasfilename(
            title="导出当前地图", defaultextension=".zip", initialfile=default_name,
            filetypes=[("备份包", "*.zip")])
        if not path:
            return
        try:
            info = self.ctx.backup.export(path, map_id=map_id)
            messagebox.showinfo("导出成功",
                                f"已导出到：\n{info['path']}\n\n瞄点 {info['spots']} / 图片 {info['images']}")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("导出失败", str(e))

    # ---------- ③ 主内容区 ----------
    def _build_main_area(self) -> None:
        main = tk.Frame(self.root, bg=T.COLOR_BG)
        main.pack(fill="both", expand=True, side="top")

        # 左：分类栏（白底，无箭头，可折叠）
        left = tk.Frame(main, bg=T.COLOR_PANEL, width=250)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Frame(main, bg=T.COLOR_BORDER, width=1).pack(side="left", fill="y")

        # 左栏不再显示「分类」标题：该栏同时容纳分类与地图直属瞄点
        self.cat_area = ScrollArea(left, bg=T.COLOR_PANEL)
        self.cat_area.pack(fill="both", expand=True, padx=10, pady=(12, 10))
        self.cat_inner = self.cat_area.inner

        # 右：展示区
        self.right = tk.Frame(main, bg=T.COLOR_BG)
        self.right.pack(side="left", fill="both", expand=True)
        self.disp_area = ScrollArea(self.right, bg=T.COLOR_BG)
        self.disp_area.pack(fill="both", expand=True)
        self.disp_inner = self.disp_area.inner

    # ---------- 状态栏 ----------
    def _build_statusbar(self) -> None:
        tk.Frame(self.root, bg=T.COLOR_BORDER, height=1).pack(fill="x", side="bottom")
        self.status = tk.Label(self.root, text="", bg=T.COLOR_BG, fg=T.COLOR_TEXT_DIM,
                               font=T.FONT_SMALL, anchor="w", padx=18, pady=6)
        self.status.pack(fill="x", side="bottom")

    def _update_status(self) -> None:
        try:
            s = self.svc.stats()
            extra = f"  ·  当前：{self.current_spot['name']}" if self.current_spot else ""
            self.status.configure(
                text=f"{s['maps']} 张地图  ·  {s['categories']} 个分类  ·  {s['spots']} 个瞄点{extra}")
        except Exception:  # noqa: BLE001
            pass

    # ---------- ④ 右下角悬浮圆形加号 ----------
    def _build_fab(self) -> None:
        size = 58
        self.fab = tk.Canvas(self.root, width=size, height=size, bg=T.COLOR_BG,
                             highlightthickness=0, bd=0, cursor="hand2")
        self.fab.place(relx=1.0, rely=1.0, x=-32, y=-48, anchor="se")
        self._draw_fab(size, T.COLOR_FAB)
        self.fab.bind("<Button-1>", lambda e: self._open_add())
        self.fab.bind("<Enter>", lambda e: self._draw_fab(size, T.COLOR_ACCENT_DARK))
        self.fab.bind("<Leave>", lambda e: self._draw_fab(size, T.COLOR_FAB))

    def _draw_fab(self, size, color) -> None:
        self.fab.delete("all")
        self.fab.create_oval(3, 3, size - 3, size - 3, fill=color, outline=color)
        self.fab.create_text(size // 2, size // 2, text="＋", font=T.FONT_FAB, fill="#ffffff")

    def _reposition_fab(self) -> None:
        try:
            self.fab.place(relx=1.0, rely=1.0, x=-32, y=-48, anchor="se")
            self.fab.lift()
        except Exception:  # noqa: BLE001
            pass

    # ================= 左侧分类栏（自定义，无箭头）=================
    def _refresh_tree(self) -> None:
        for w in self.cat_inner.winfo_children():
            w.destroy()
        self._cat_rows.clear()
        self._spot_rows.clear()
        if not self.current_map:
            return
        map_id = self.current_map["id"]
        # 上：分类（可展开，展开后显示其下瞄点）
        cats = self.svc.list_categories(map_id)
        for c in cats:
            self._add_category_row(c["id"], c["name"])
        # 下：地图直属瞄点（不归任何分类，直接平铺，不再显示「地图直属」节点）
        direct_spots = self.svc.list_map_direct_spots(map_id)
        if direct_spots:
            if cats:
                self._add_divider()
            for s in direct_spots:
                self._add_spot_row(s)

    def _add_category_row(self, key, name: str) -> None:
        is_direct = key == DIRECT
        selected = self.selection == ("cat", key)
        expanded = key in self.expanded
        bg = T.COLOR_ACCENT_SOFT if selected else T.COLOR_PANEL

        row = tk.Frame(self.cat_inner, bg=bg, cursor="hand2")
        row.pack(fill="x", pady=1)
        # 左侧选中色条
        bar = tk.Frame(row, bg=T.COLOR_ACCENT if selected else bg, width=3)
        bar.pack(side="left", fill="y")
        label = tk.Label(row, text=name, bg=bg, fg=T.COLOR_TEXT if selected else T.COLOR_TEXT,
                         font=T.FONT_BOLD if selected else T.FONT_BASE, anchor="w", padx=12, pady=8)
        label.pack(side="left", fill="x", expand=True)
        # 右侧展开状态箭头：展开 ▲ / 折叠 ▼
        chevron = tk.Label(row, text=("▲" if expanded else "▼"), bg=bg, fg=T.COLOR_TEXT_DIM,
                           font=("Microsoft YaHei UI", 8), padx=12)
        chevron.pack(side="right")

        widgets = [row, bar, label, chevron]
        self._cat_rows[key] = widgets
        for w in widgets:
            w.bind("<Button-1>", lambda e, k=key: self._on_category_click(k))
            w.bind("<Button-3>", lambda e, k=key: self._on_category_right_click(e, k))
            if not selected:
                w.bind("<Enter>", lambda e, ws=widgets: self._hover(ws, T.COLOR_HOVER))
                w.bind("<Leave>", lambda e, ws=widgets: self._hover(ws, T.COLOR_PANEL))

        if expanded:
            self._add_spot_rows(key)

    def _add_spot_rows(self, key) -> None:
        if key == DIRECT:
            spots = self.svc.list_map_direct_spots(self.current_map["id"])
        else:
            spots = self.svc.list_spots_by_category(key)
        for s in spots:
            self._add_spot_row(s)

    def _add_spot_row(self, spot: dict) -> None:
        sid = spot["id"]
        selected = self.selection == ("spot", sid)
        bg = T.COLOR_ACCENT_SOFT if selected else T.COLOR_PANEL
        row = tk.Frame(self.cat_inner, bg=bg, cursor="hand2")
        row.pack(fill="x")
        spacer = tk.Frame(row, bg=bg, width=18)
        spacer.pack(side="left")
        dot = tk.Label(row, text="•", bg=bg, fg=T.COLOR_ACCENT if selected else T.COLOR_TEXT_DIM,
                       font=T.FONT_BASE)
        dot.pack(side="left")
        label = tk.Label(row, text=spot["name"], bg=bg,
                         fg=T.COLOR_ACCENT_DARK if selected else T.COLOR_TEXT,
                         font=T.FONT_BOLD if selected else T.FONT_SMALL, anchor="w", padx=6, pady=5)
        label.pack(side="left", fill="x", expand=True)

        widgets = [row, spacer, dot, label]
        self._spot_rows[sid] = widgets
        for w in widgets:
            w.bind("<Button-1>", lambda e, i=sid: self._on_spot_click(i))
            w.bind("<Button-3>", lambda e, i=sid: self._on_spot_right_click(e, i))
            if not selected:
                w.bind("<Enter>", lambda e, ws=widgets: self._hover(ws, T.COLOR_HOVER))
                w.bind("<Leave>", lambda e, ws=widgets: self._hover(ws, T.COLOR_PANEL))

    def _add_divider(self) -> None:
        """分类与地图直属瞄点之间的细分隔线。"""
        d = tk.Frame(self.cat_inner, bg=T.COLOR_BORDER, height=1)
        d.pack(fill="x", padx=14, pady=8)

    def _hover(self, widgets, color) -> None:
        for w in widgets:
            try:
                w.configure(bg=color)
            except Exception:
                pass

    def _on_category_click(self, key) -> None:
        # 切换展开
        if key in self.expanded:
            self.expanded.discard(key)
        else:
            self.expanded.add(key)
        self.selection = ("cat", key)
        self.current_category_id = None if key == DIRECT else key
        self.current_spot = None
        self._refresh_tree()
        self._show_category_grid()
        self._update_status()

    def _on_spot_click(self, spot_id: int) -> None:
        self.selection = ("spot", spot_id)
        self.current_spot = self.svc.get_spot(spot_id)
        self._refresh_tree()
        self._show_spot_detail(self.current_spot)
        self._update_status()

    def _on_category_right_click(self, event, key) -> None:
        menu = self._popup_menu()
        menu.add_command(label="在此分类下新建瞄点", command=lambda: self._open_add("瞄点", key))
        menu.add_command(label="重命名分类", command=lambda: self._rename_category(key))
        menu.add_separator()
        menu.add_command(label="删除分类", command=lambda: self._delete_category(key))
        menu.tk_popup(event.x_root, event.y_root)

    def _on_spot_right_click(self, event, spot_id: int) -> None:
        menu = self._popup_menu()
        menu.add_command(label="编辑瞄点", command=lambda: self._edit_spot(spot_id))
        menu.add_separator()
        menu.add_command(label="删除瞄点", command=lambda: self._delete_spot(spot_id))
        menu.tk_popup(event.x_root, event.y_root)

    # ================= 右侧展示区 =================
    def _clear_display(self) -> None:
        for w in self.disp_inner.winfo_children():
            w.destroy()
        self._thumb_refs.clear()
        self.disp_area.scroll_to_top()

    def _show_empty(self, text: str) -> None:
        self._clear_display()
        tk.Label(self.disp_inner, text=text, bg=T.COLOR_BG, fg=T.COLOR_TEXT_DIM,
                 font=T.FONT_BASE).pack(pady=80)

    def _show_category_grid(self) -> None:
        if not self.current_map:
            self._show_empty("请先选择地图")
            return
        key = self.current_category_id
        if isinstance(key, int):
            cat = self.svc.dao.categories.get(key)
            spots = self.svc.list_spots_by_category(key)
            title = cat["name"] if cat else "瞄点"
            self._render_grid(title, spots, cat_id=key)
        else:
            # 未选中具体分类：默认展示空
            self._show_empty("从左侧选择分类或瞄点查看详情")

    def _render_grid(self, title: str, spots: list[dict], cat_id: int | None = None) -> None:
        self._clear_display()
        head = tk.Frame(self.disp_inner, bg=T.COLOR_BG)
        head.pack(fill="x", padx=26, pady=(22, 6))
        tk.Label(head, text=title, bg=T.COLOR_BG, fg=T.COLOR_TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(side="left")
        tk.Label(head, text=f"{len(spots)} 个瞄点", bg=T.COLOR_BG, fg=T.COLOR_TEXT_DIM,
                 font=T.FONT_SMALL).pack(side="left", padx=(10, 0), pady=(6, 0))
        # 选中真实分类时，右上角提供编辑/删除（与瞄点一致）
        if cat_id is not None:
            ttk.Button(head, text="删除", style="Danger.TButton",
                       command=lambda: self._delete_category(cat_id)).pack(side="right", padx=(8, 0))
            ttk.Button(head, text="编辑",
                       command=lambda: self._rename_category(cat_id)).pack(side="right")

        if not spots:
            tk.Label(self.disp_inner, text="暂无瞄点，点击右下角 ＋ 添加",
                     bg=T.COLOR_BG, fg=T.COLOR_TEXT_DIM, font=T.FONT_BASE).pack(pady=50)
            return

        grid = tk.Frame(self.disp_inner, bg=T.COLOR_BG)
        grid.pack(fill="x", padx=18, pady=10)
        cols = 4
        for i, s in enumerate(spots):
            r, c = divmod(i, cols)
            self._make_spot_card(grid, s).grid(row=r, column=c, padx=9, pady=9, sticky="nsew")
            grid.columnconfigure(c, weight=1, uniform="card")

    def _make_spot_card(self, parent, spot: dict) -> tk.Widget:
        """圆角瞄点卡片（Canvas 自绘）。"""
        w, h = 190, 170
        cv = tk.Canvas(parent, width=w, height=h, bg=T.COLOR_BG, highlightthickness=0,
                       bd=0, cursor="hand2")
        T.round_rect(cv, 1, 1, w - 1, h - 1, T.RADIUS_CARD, fill=T.COLOR_CARD, outline=T.COLOR_BORDER, width=1)

        # 缩略图（首图，圆角区域内）
        img_top, img_bottom = 10, 112
        imgs = spot.get("images") or ([spot["image_path"]] if spot.get("image_path") else [])
        first_rel = imgs[0] if imgs else None
        thumb = self.svc.images.thumbnail_path(first_rel, size=200)
        img_count = len(imgs)
        if thumb and thumb.exists():
            try:
                from PIL import Image, ImageTk
                im = Image.open(thumb).convert("RGB")
                im.thumbnail((w - 24, img_bottom - img_top - 6), Image.LANCZOS)
                photo = ImageTk.PhotoImage(im)
                cv.create_image(w // 2, (img_top + img_bottom) // 2, image=photo)
                self._thumb_refs.append(photo)
                # 多图角标
                if img_count > 1:
                    T.round_rect(cv, w - 46, img_bottom - 26, w - 12, img_bottom - 8, 8,
                                 fill="#000000", outline="#000000")
                    cv.create_text(w - 29, img_bottom - 17, text=f"{img_count}图",
                                   fill="#ffffff", font=("Microsoft YaHei UI", 8, "bold"))
            except Exception:  # noqa: BLE001
                cv.create_text(w // 2, (img_top + img_bottom) // 2, text="无图片",
                               fill=T.COLOR_TEXT_DIM, font=T.FONT_SMALL)
        else:
            cv.create_text(w // 2, (img_top + img_bottom) // 2, text="无图片",
                           fill=T.COLOR_TEXT_DIM, font=T.FONT_SMALL)

        # 名称
        name = spot["name"]
        if len(name) > 12:
            name = name[:12] + "…"
        cv.create_text(w // 2, img_bottom + 24, text=name, fill=T.COLOR_TEXT,
                       font=T.FONT_CARD_TITLE)

        cv.bind("<Button-1>", lambda e, i=spot["id"]: self._on_card_click(i))
        cv.bind("<Enter>", lambda e, c=cv: c.itemconfigure(1, outline=T.COLOR_ACCENT))
        cv.bind("<Leave>", lambda e, c=cv: c.itemconfigure(1, outline=T.COLOR_BORDER))
        return cv

    def _on_card_click(self, spot_id: int) -> None:
        self.selection = ("spot", spot_id)
        self.current_spot = self.svc.get_spot(spot_id)
        # 展开所属分类并高亮
        if self.current_spot:
            key = self.current_spot.get("category_id") or DIRECT
            self.expanded.add(key)
        self._refresh_tree()
        self._show_spot_detail(self.current_spot)
        self._update_status()

    def _show_spot_detail(self, spot: dict | None) -> None:
        if not spot:
            return
        self._clear_display()
        wrap = tk.Frame(self.disp_inner, bg=T.COLOR_BG)
        wrap.pack(fill="both", expand=True, padx=26, pady=20)

        top = tk.Frame(wrap, bg=T.COLOR_BG)
        top.pack(fill="x")
        tk.Label(top, text=spot["name"], bg=T.COLOR_BG, fg=T.COLOR_TEXT,
                 font=("Microsoft YaHei UI", 17, "bold")).pack(side="left")
        ttk.Button(top, text="删除", style="Danger.TButton",
                   command=lambda: self._delete_spot(spot["id"])).pack(side="right", padx=(8, 0))
        ttk.Button(top, text="编辑", command=lambda: self._edit_spot(spot["id"])).pack(side="right")

        cat_txt = "地图直属"
        if spot.get("category_id"):
            cat = self.svc.dao.categories.get(spot["category_id"])
            cat_txt = cat["name"] if cat else "地图直属"
        map_name = self.current_map["name"] if self.current_map else "?"
        tk.Label(wrap, text=f"{map_name}   ·   {cat_txt}", bg=T.COLOR_BG, fg=T.COLOR_TEXT_DIM,
                 font=T.FONT_SMALL, anchor="w").pack(fill="x", pady=(6, 14))

        # 图片画廊（多图，圆角容器）
        imgs = spot.get("images") or ([spot["image_path"]] if spot.get("image_path") else [])
        abs_paths: list[str] = []
        for rel in imgs:
            p = config.abspath(rel)
            if p and p.exists():
                abs_paths.append(str(p))

        img_wrap = tk.Frame(wrap, bg=T.COLOR_PANEL, bd=0, highlightthickness=1,
                            highlightbackground=T.COLOR_BORDER)
        img_wrap.pack(fill="x")
        if not abs_paths:
            tk.Label(img_wrap, text="无图片", bg=T.COLOR_PANEL, fg=T.COLOR_TEXT_DIM,
                     font=T.FONT_BASE).pack(padx=10, pady=24)
        else:
            if len(abs_paths) > 1:
                tk.Label(img_wrap, text=f"共 {len(abs_paths)} 张图片（点击看大图，可左右切换）",
                         bg=T.COLOR_PANEL, fg=T.COLOR_TEXT_DIM, font=T.FONT_SMALL,
                         anchor="w").pack(fill="x", padx=14, pady=(10, 0))
            gallery = tk.Frame(img_wrap, bg=T.COLOR_PANEL)
            gallery.pack(fill="x", padx=8, pady=10)
            from PIL import Image, ImageTk
            per_row = 3
            for i, p in enumerate(abs_paths):
                r, c = divmod(i, per_row)
                try:
                    im = Image.open(p)
                    im.thumbnail((230, 160), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(im)
                    self._thumb_refs.append(photo)
                    lbl = tk.Label(gallery, image=photo, bg=T.COLOR_PANEL, cursor="hand2", bd=0)
                    lbl.grid(row=r, column=c, padx=6, pady=6, sticky="n")
                    lbl.bind("<Button-1>", lambda e, idx=i: open_image_viewer(self.root, abs_paths, idx))
                except Exception:  # noqa: BLE001
                    tk.Label(gallery, text="加载失败", bg=T.COLOR_PANEL, fg=T.COLOR_TEXT_DIM,
                             width=28, height=8).grid(row=r, column=c, padx=6, pady=6)

        # 描述卡片
        desc_card = tk.Frame(wrap, bg=T.COLOR_PANEL, bd=0, highlightthickness=1,
                             highlightbackground=T.COLOR_BORDER)
        desc_card.pack(fill="x", pady=(16, 0))
        inner = tk.Frame(desc_card, bg=T.COLOR_PANEL)
        inner.pack(fill="x", padx=16, pady=14)
        tk.Label(inner, text="描述", bg=T.COLOR_PANEL, fg=T.COLOR_TEXT_DIM,
                 font=T.FONT_BOLD, anchor="w").pack(fill="x")
        tk.Label(inner, text=spot.get("description") or "（无描述）", bg=T.COLOR_PANEL,
                 fg=T.COLOR_TEXT, font=T.FONT_BASE, wraplength=740, justify="left",
                 anchor="nw").pack(fill="x", pady=(6, 0))

    # ================= 新增 / 编辑 / 删除 =================
    def _open_add(self, default_type: str = None, force_category=None) -> None:
        if default_type is None:
            default_type = "瞄点" if self.current_map else "地图"
        if not self.current_map and default_type in ("瞄点", "分类"):
            default_type = "地图"

        cat_id = force_category
        if cat_id == DIRECT:
            cat_id = None
        cat_name = None
        if cat_id is None and force_category is None:
            # 依据当前选择推断归属
            if self.selection and self.selection[0] == "cat":
                k = self.selection[1]
                cat_id = None if k == DIRECT else k
            elif isinstance(self.current_category_id, int):
                cat_id = self.current_category_id
        if isinstance(cat_id, int):
            cat = self.svc.dao.categories.get(cat_id)
            cat_name = cat["name"] if cat else None

        ctx = {
            "map_id": self.current_map["id"] if self.current_map else None,
            "map_name": self.current_map["name"] if self.current_map else None,
            "category_id": cat_id,
            "category_name": cat_name,
            "allow_type_switch": True,
        }
        result = add_page.open_add_dialog(self.root, ctx, self.ctx.images, default_type)
        if not result:
            return
        self._apply_add(result, ctx)

    def _apply_add(self, result: dict, ctx: dict) -> None:
        t = result["type"]
        try:
            if t == "地图":
                new_id = self.svc.create_map(result["name"])
                self.refresh_maps()
                self._select_map(new_id)
            elif t == "分类":
                if not ctx.get("map_id"):
                    messagebox.showwarning("提示", "请先选择地图")
                    return
                self.svc.create_category(ctx["map_id"], result["name"])
                self._refresh_tree()
            elif t == "瞄点":
                if not ctx.get("map_id"):
                    messagebox.showwarning("提示", "请先选择地图")
                    return
                new_id = self.svc.create_spot(
                    map_id=ctx["map_id"], name=result["name"],
                    description=result.get("description", ""),
                    image_srcs=result.get("image_srcs"), category_id=ctx.get("category_id"))
                self._reveal_spot(new_id, ctx.get("category_id"))
            self._refresh_display()
            self._update_status()
        except ServiceError as e:
            messagebox.showerror("操作失败", str(e))

    def _reveal_spot(self, spot_id: int, category_id) -> None:
        key = category_id if category_id else DIRECT
        self.expanded.add(key)
        self.selection = ("spot", spot_id)
        self.current_spot = self.svc.get_spot(spot_id)
        self._refresh_tree()

    def _edit_spot(self, spot_id: int) -> None:
        spot = self.svc.get_spot(spot_id)
        if not spot:
            return
        result = add_page.open_edit_spot(self.root, spot, self.ctx.images)
        if not result:
            return
        try:
            self.svc.update_spot(
                spot_id, name=result["name"], description=result["description"],
                image_sources=result.get("image_sources"))
            self._refresh_tree()
            self.current_spot = self.svc.get_spot(spot_id)
            self._show_spot_detail(self.current_spot)
            self._update_status()
        except ServiceError as e:
            messagebox.showerror("编辑失败", str(e))

    def _delete_spot(self, spot_id: int) -> None:
        spot = self.svc.get_spot(spot_id)
        if not spot:
            return
        if not messagebox.askyesno("确认删除", f"确定删除瞄点「{spot['name']}」？此操作不可撤销。"):
            return
        try:
            self.svc.delete_spot(spot_id)
            if self.current_spot and self.current_spot["id"] == spot_id:
                self.current_spot = None
                self.selection = None
            self._refresh_tree()
            self._refresh_display()
            self._update_status()
        except ServiceError as e:
            messagebox.showerror("删除失败", str(e))

    def _rename_category(self, cat_id: int) -> None:
        cat = self.svc.dao.categories.get(cat_id)
        if not cat:
            return
        from .simple_dialog import ask_text
        new_name = ask_text(self.root, "编辑分类", "分类名称", cat["name"])
        if not new_name:
            return
        try:
            self.svc.rename_category(cat_id, new_name)
            self._refresh_tree()
            self._refresh_display()
        except ServiceError as e:
            messagebox.showerror("重命名失败", str(e))

    def _delete_category(self, cat_id: int) -> None:
        cat = self.svc.dao.categories.get(cat_id)
        if not cat:
            return
        n = self.svc.count_category_spots(cat_id)
        if not messagebox.askyesno("确认删除",
                                   f"确定删除分类「{cat['name']}」？\n将同时删除其下 {n} 个瞄点及图片。"):
            return
        try:
            self.svc.delete_category(cat_id)
            if self.current_category_id == cat_id:
                self.current_category_id = None
                self.current_spot = None
            if self.selection == ("cat", cat_id):
                self.selection = None
            self.expanded.discard(cat_id)
            self._refresh_tree()
            self._refresh_display()
            self._update_status()
        except ServiceError as e:
            messagebox.showerror("删除失败", str(e))

    def _rename_map(self, map_id: int) -> None:
        m = self.svc.dao.maps.get(map_id)
        if not m:
            return
        from .simple_dialog import ask_text
        new_name = ask_text(self.root, "重命名地图", "地图名称", m["name"])
        if not new_name:
            return
        try:
            self.svc.rename_map(map_id, new_name)
            self.refresh_maps()
        except ServiceError as e:
            messagebox.showerror("重命名失败", str(e))

    def _delete_map(self, map_id: int) -> None:
        m = self.svc.dao.maps.get(map_id)
        if not m:
            return
        cats, spots = self.svc.count_children(map_id)
        if not messagebox.askyesno("确认删除",
                                   f"确定删除地图「{m['name']}」？\n将同时删除 {cats} 个分类、{spots} 个瞄点及全部图片。"):
            return
        try:
            self.svc.delete_map(map_id)
            if self.current_map and self.current_map["id"] == map_id:
                self.current_map = None
            self.refresh_maps(select_first=True)
        except ServiceError as e:
            messagebox.showerror("删除失败", str(e))

    # ================= 搜索 =================
    def _on_search_key(self, _e=None) -> None:
        if self._search_job:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(300, self._do_search)

    def _do_search(self) -> None:
        kw = self.search_var.get().strip()
        if not kw:
            self._refresh_display()
            return
        scope = self.scope_var.get()
        map_id = cat_id = None
        if scope == "当前地图" and self.current_map:
            map_id = self.current_map["id"]
        elif scope == "当前分类":
            if isinstance(self.current_category_id, int):
                cat_id = self.current_category_id
            elif self.current_map:
                map_id = self.current_map["id"]
        results = self.ctx.search.search(kw, map_id=map_id, category_id=cat_id)
        self._show_search_results(kw, results)

    def _show_search_results(self, kw: str, results: list[dict]) -> None:
        self._clear_display()
        tk.Label(self.disp_inner, text=f"搜索“{kw}” · 命中 {len(results)} 条",
                 bg=T.COLOR_BG, fg=T.COLOR_TEXT, font=("Microsoft YaHei UI", 15, "bold"),
                 anchor="w").pack(fill="x", padx=26, pady=(22, 10))
        if not results:
            tk.Label(self.disp_inner, text="没有匹配的瞄点", bg=T.COLOR_BG,
                     fg=T.COLOR_TEXT_DIM, font=T.FONT_BASE).pack(pady=50)
            return
        for s in results:
            card = tk.Frame(self.disp_inner, bg=T.COLOR_CARD, cursor="hand2",
                            highlightthickness=1, highlightbackground=T.COLOR_BORDER)
            card.pack(fill="x", padx=22, pady=5)
            loc = f"{s.get('map_name', '')} · {s.get('category_name') or '地图直属'}"
            tk.Label(card, text=s["name"], bg=T.COLOR_CARD, fg=T.COLOR_TEXT,
                     font=T.FONT_BOLD, anchor="w").pack(fill="x", padx=16, pady=(12, 0))
            tk.Label(card, text=loc, bg=T.COLOR_CARD, fg=T.COLOR_ACCENT,
                     font=T.FONT_SMALL, anchor="w").pack(fill="x", padx=16)
            desc = (s.get("description") or "").replace("\n", " ")
            if len(desc) > 70:
                desc = desc[:70] + "…"
            tk.Label(card, text=desc or "（无描述）", bg=T.COLOR_CARD, fg=T.COLOR_TEXT_DIM,
                     font=T.FONT_SMALL, anchor="w", wraplength=820,
                     justify="left").pack(fill="x", padx=16, pady=(2, 12))
            for child in card.winfo_children():
                child.bind("<Button-1>", lambda e, sid=s["id"]: self._jump_to_spot(sid))
            card.bind("<Button-1>", lambda e, sid=s["id"]: self._jump_to_spot(sid))

    def _jump_to_spot(self, spot_id: int) -> None:
        spot = self.svc.get_spot(spot_id)
        if not spot:
            return
        self.search_var.set("")
        self._select_map(spot["map_id"])
        key = spot.get("category_id") or DIRECT
        self.expanded.add(key)
        self.selection = ("spot", spot_id)
        self.current_spot = spot
        self._refresh_tree()
        self._show_spot_detail(spot)

    def _refresh_display(self) -> None:
        if self.search_var.get().strip():
            self._do_search()
        elif self.current_spot:
            self._show_spot_detail(self.current_spot)
        elif self.selection and self.selection[0] == "cat":
            self._show_category_grid()
        elif self.current_map:
            # 打开地图默认展示空，由用户从左侧选择分类或瞄点
            self._show_empty("从左侧选择分类或瞄点查看详情")
        else:
            self._show_empty("请先选择或新建地图")

    # ================= 导入 / 导出 / 设置 =================
    def _on_export(self) -> None:
        if not self.svc.list_maps():
            messagebox.showinfo("提示", "暂无数据可导出")
            return
        scope_all = messagebox.askyesno("导出范围", "导出全部地图？\n选择“否”则仅导出当前地图。")
        map_id = None if scope_all or not self.current_map else self.current_map["id"]
        default_name = f"aim_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}.zip"
        path = filedialog.asksaveasfilename(
            title="导出备份", defaultextension=".zip", initialfile=default_name,
            filetypes=[("备份包", "*.zip")])
        if not path:
            return
        try:
            info = self.ctx.backup.export(path, map_id=map_id)
            messagebox.showinfo("导出成功",
                                f"已导出到：\n{info['path']}\n\n地图 {info['maps']} / 分类 {info['categories']} / "
                                f"瞄点 {info['spots']} / 图片 {info['images']}")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("导出失败", str(e))

    def _on_import(self) -> None:
        path = filedialog.askopenfilename(title="导入备份", filetypes=[("备份包", "*.zip")])
        if not path:
            return
        choice = self._ask_conflict_strategy()
        if choice is None:
            return
        try:
            stats = self.ctx.backup.import_zip(path, conflict=choice)
            self.refresh_maps(select_first=True)
            messagebox.showinfo("导入完成",
                                f"新增地图 {stats['maps']} / 分类 {stats['categories']} / 瞄点 {stats['spots']}\n"
                                f"跳过地图 {stats['skipped_maps']}")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("导入失败", str(e))

    def _ask_conflict_strategy(self) -> str | None:
        dlg = tk.Toplevel(self.root)
        dlg.title("导入冲突策略")
        dlg.configure(bg=T.COLOR_PANEL)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text="当导入的地图名与现有地图重复时：", bg=T.COLOR_PANEL,
                 fg=T.COLOR_TEXT, font=T.FONT_BASE).pack(padx=22, pady=(20, 12), anchor="w")
        result = {"v": None}

        def pick(v):
            result["v"] = v
            dlg.destroy()

        ttk.Button(dlg, text="跳过（保留现有，忽略备份中的重复地图）",
                   command=lambda: pick("skip")).pack(fill="x", padx=22, pady=4)
        ttk.Button(dlg, text="覆盖（删除现有同名地图，用备份替换）",
                   command=lambda: pick("overwrite")).pack(fill="x", padx=22, pady=4)
        ttk.Button(dlg, text="合并为副本（导入为“xxx(导入)”新地图）",
                   command=lambda: pick("duplicate")).pack(fill="x", padx=22, pady=4)
        ttk.Button(dlg, text="取消", command=lambda: pick(None)).pack(pady=14)
        self.root.wait_window(dlg)
        return result["v"]

    def _open_settings(self) -> None:
        from .settings_dialog import open_settings
        open_settings(self.root, self.ctx)
        self._refresh_tree()
        self._refresh_display()
        self._update_status()
