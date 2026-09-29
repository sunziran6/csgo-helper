"""主窗口：顶部导航 + 地图横栏 + 左分类树 + 右展示区 + 右下角悬浮加号。"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import config
from ..context import AppContext
from ..logging_setup import get_logger
from ..services.map_service import ServiceError
from . import add_page, theme as T
from .image_viewer import open_image_viewer

log = get_logger("aim.ui")

DIRECT_NODE = "__direct__"  # 分类树中「地图直属」虚拟节点


class MainWindow:
    def __init__(self, root: tk.Tk, ctx: AppContext):
        self.root = root
        self.ctx = ctx
        self.svc = ctx.maps

        self.current_map: dict | None = None
        self.current_category_id: int | None = None  # None=未选分类, DIRECT_NODE 特殊处理
        self.current_spot: dict | None = None
        self._map_buttons: dict[int, tk.Widget] = {}
        self._thumb_refs: list = []   # 防止缩略图 PhotoImage 被 GC
        self._spot_grid_items: list[dict] = []
        self._search_job = None

        self._setup_window()
        self._build_ui()
        self.refresh_maps(select_first=True)

    # ================= 窗口与骨架 =================
    def _setup_window(self) -> None:
        self.root.title(config.APP_NAME)
        self.root.geometry("1100x720")
        self.root.minsize(880, 560)
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
        nav = tk.Frame(self.root, bg=T.COLOR_NAV, height=56)
        nav.pack(fill="x", side="top")
        nav.pack_propagate(False)

        title = tk.Label(nav, text="⌖ " + config.APP_NAME, bg=T.COLOR_NAV,
                         fg=T.COLOR_ACCENT, font=T.FONT_APP)
        title.pack(side="left", padx=18)

        # 右侧功能
        right = tk.Frame(nav, bg=T.COLOR_NAV)
        right.pack(side="right", padx=14)

        ttk.Button(right, text="设置", command=self._open_settings).pack(side="right", padx=(8, 0))
        ttk.Button(right, text="导入", command=self._on_import).pack(side="right", padx=(8, 0))
        ttk.Button(right, text="导出", command=self._on_export).pack(side="right", padx=(8, 0))

        self.scope_var = tk.StringVar(value="当前地图")
        scope = ttk.Combobox(right, textvariable=self.scope_var, width=9, state="readonly",
                             values=["全部地图", "当前地图", "当前分类"])
        scope.pack(side="right", padx=(8, 0))

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(right, textvariable=self.search_var, width=22)
        search_entry.pack(side="right", padx=(8, 0))
        search_entry.bind("<KeyRelease>", self._on_search_key)
        self.search_entry = search_entry

        self.root.bind("<Control-f>", lambda e: self.search_entry.focus_set())

    # ---------- ② 地图横栏（可横向滑动）----------
    def _build_map_bar(self) -> None:
        bar = tk.Frame(self.root, bg=T.COLOR_PANEL, height=54)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        self.bar_left = tk.Button(bar, text="‹", bg=T.COLOR_PANEL, fg=T.COLOR_TEXT,
                                  relief="flat", font=T.FONT_MAP_TAB, width=2,
                                  command=lambda: self._scroll_maps(-1))
        self.bar_left.pack(side="left", padx=(6, 2))

        self.bar_right = tk.Button(bar, text="›", bg=T.COLOR_PANEL, fg=T.COLOR_TEXT,
                                   relief="flat", font=T.FONT_MAP_TAB, width=2,
                                   command=lambda: self._scroll_maps(1))
        self.bar_right.pack(side="right", padx=(2, 6))

        canvas_wrap = tk.Frame(bar, bg=T.COLOR_PANEL)
        canvas_wrap.pack(side="left", fill="both", expand=True)

        self.map_canvas = tk.Canvas(canvas_wrap, bg=T.COLOR_PANEL, height=50,
                                    highlightthickness=0, bd=0)
        self.map_canvas.pack(side="top", fill="both", expand=True)
        self.map_inner = tk.Frame(self.map_canvas, bg=T.COLOR_PANEL)
        self._map_window = self.map_canvas.create_window((0, 0), window=self.map_inner, anchor="nw")

        self.map_inner.bind("<Configure>", self._on_map_inner_configure)
        self.map_canvas.bind("<Configure>", self._on_map_canvas_configure)
        # 滚轮横向滑动
        self.map_canvas.bind_all("<Shift-MouseWheel>", self._on_map_wheel, add="+")
        self.map_canvas.bind_all("<Control-MouseWheel>", self._on_map_wheel, add="+")

    def _on_map_inner_configure(self, _e=None) -> None:
        self.map_canvas.configure(scrollregion=self.map_canvas.bbox("all"))

    def _on_map_canvas_configure(self, e) -> None:
        self.map_canvas.itemconfigure(self._map_window, width=e.width)

    def _on_map_wheel(self, event) -> None:
        delta = -event.delta
        self.map_canvas.xview_scroll(int(delta / 60) or (1 if delta > 0 else -1), "units")

    def _scroll_maps(self, direction: int) -> None:
        self.map_canvas.xview_scroll(direction, "pages")

    # ---------- ③ 主内容区（左分类树 + 右展示）----------
    def _build_main_area(self) -> None:
        main = tk.Frame(self.root, bg=T.COLOR_BG)
        main.pack(fill="both", expand=True, side="top")

        # 左：分类栏
        left = tk.Frame(main, bg=T.COLOR_PANEL, width=240)
        left.pack(side="left", fill="y", padx=(0, 1))
        left.pack_propagate(False)

        head = tk.Label(left, text="分类", bg=T.COLOR_PANEL, fg=T.COLOR_TEXT_DIM,
                        font=T.FONT_BOLD, anchor="w")
        head.pack(fill="x", padx=12, pady=(10, 4))

        tree_wrap = tk.Frame(left, bg=T.COLOR_PANEL)
        tree_wrap.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        self.tree = ttk.Treeview(tree_wrap, show="tree", selectmode="browse")
        vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Button-3>", self._on_tree_right_click)

        # 右：展示区（滚动容器）
        self.right = tk.Frame(main, bg=T.COLOR_BG)
        self.right.pack(side="left", fill="both", expand=True)
        self._build_display_area()

    def _build_display_area(self) -> None:
        # 使用 Canvas + 内嵌 Frame 实现垂直滚动
        self.disp_canvas = tk.Canvas(self.right, bg=T.COLOR_BG, highlightthickness=0, bd=0)
        self.disp_vsb = ttk.Scrollbar(self.right, orient="vertical", command=self.disp_canvas.yview)
        self.disp_canvas.configure(yscrollcommand=self.disp_vsb.set)
        self.disp_vsb.pack(side="right", fill="y")
        self.disp_canvas.pack(side="left", fill="both", expand=True)

        self.disp_inner = tk.Frame(self.disp_canvas, bg=T.COLOR_BG)
        self._disp_window = self.disp_canvas.create_window((0, 0), window=self.disp_inner, anchor="nw")
        self.disp_inner.bind("<Configure>",
                             lambda e: self.disp_canvas.configure(scrollregion=self.disp_canvas.bbox("all")))
        self.disp_canvas.bind("<Configure>",
                              lambda e: self.disp_canvas.itemconfigure(self._disp_window, width=e.width))
        self.disp_canvas.bind_all("<MouseWheel>", self._on_display_wheel, add="+")

    def _on_display_wheel(self, event) -> None:
        # 仅在展示区滚动（避免与地图横栏冲突）
        if not self.disp_canvas.bbox("all"):
            return
        self.disp_canvas.yview_scroll(int(-event.delta / 120) or (1 if event.delta > 0 else -1), "units")

    # ---------- 状态栏 ----------
    def _build_statusbar(self) -> None:
        self.status = tk.Label(self.root, text="", bg=T.COLOR_NAV, fg=T.COLOR_TEXT_DIM,
                               font=T.FONT_SMALL, anchor="w", padx=14, height=1)
        self.status.pack(fill="x", side="bottom")

    def _update_status(self) -> None:
        try:
            s = self.svc.stats()
            extra = ""
            if self.current_spot:
                extra = f"  |  当前: {self.current_spot['name']}"
            self.status.configure(
                text=f"共 {s['maps']} 张地图 / {s['categories']} 个分类 / {s['spots']} 个瞄点{extra}")
        except Exception:  # noqa: BLE001
            pass

    # ---------- ④ 右下角悬浮加号 ----------
    def _build_fab(self) -> None:
        size = 56
        self.fab = tk.Canvas(self.root, width=size, height=size, bg=T.COLOR_BG,
                             highlightthickness=0, bd=0)
        self.fab.place(relx=1.0, rely=1.0, x=-30, y=-46, anchor="se")
        self.fab.create_oval(4, 4, size - 4, size - 4, fill=T.COLOR_FAB, outline=T.COLOR_ACCENT_DARK, width=2)
        self.fab.create_text(size // 2, size // 2 - 1, text="＋", font=T.FONT_FAB, fill="#1a1a1a")
        self.fab.bind("<Button-1>", lambda e: self._open_add())
        self.fab.configure(cursor="hand2")
        self.fab.bind("<Enter>", lambda e: self.fab.configure(bg=T.COLOR_BG))
        self._fab_size = size

    def _reposition_fab(self) -> None:
        try:
            self.fab.place(relx=1.0, rely=1.0, x=-30, y=-46, anchor="se")
            self.fab.lift()
        except Exception:  # noqa: BLE001
            pass

    # ================= 地图横栏渲染 =================
    def refresh_maps(self, select_first: bool = False) -> None:
        for w in self.map_inner.winfo_children():
            w.destroy()
        self._map_buttons.clear()

        maps = self.svc.list_maps()
        if not maps:
            tk.Label(self.map_inner, text="暂无地图，点击右下角 ＋ 新建地图",
                     bg=T.COLOR_PANEL, fg=T.COLOR_TEXT_DIM, font=T.FONT_BASE).pack(padx=16, pady=12)
            self.current_map = None
            self._refresh_tree()
            self._refresh_display()
            self._update_status()
            return

        for m in maps:
            btn = tk.Button(self.map_inner, text=m["name"], relief="flat",
                            font=T.FONT_MAP_TAB, padx=16, pady=6, cursor="hand2",
                            bd=0, activebackground=T.COLOR_PANEL)
            btn.configure(command=lambda mid=m["id"]: self._select_map(mid))
            btn.bind("<Button-3>", lambda e, mid=m["id"]: self._on_map_right_click(e, mid))
            btn.pack(side="left", padx=3, pady=8)
            self._map_buttons[m["id"]] = btn

        if select_first or (self.current_map and self.current_map["id"] not in self._map_buttons):
            self._select_map(maps[0]["id"])
        else:
            self._select_map(self.current_map["id"])

    def _select_map(self, map_id: int) -> None:
        self.current_map = self.svc.dao.maps.get(map_id)
        self.current_category_id = None
        self.current_spot = None
        # 高亮
        for mid, btn in self._map_buttons.items():
            if mid == map_id:
                btn.configure(bg=T.COLOR_ACCENT, fg="#1a1a1a", activeforeground="#1a1a1a")
            else:
                btn.configure(bg=T.COLOR_PANEL, fg=T.COLOR_TEXT, activeforeground=T.COLOR_TEXT)
        self._refresh_tree()
        self._refresh_display()
        self._update_status()

    def _on_map_right_click(self, event, map_id: int) -> None:
        self._select_map(map_id)
        menu = tk.Menu(self.root, tearoff=0, bg=T.COLOR_CARD, fg=T.COLOR_TEXT,
                       activebackground=T.COLOR_ACCENT, activeforeground="#1a1a1a")
        menu.add_command(label="重命名地图", command=lambda: self._rename_map(map_id))
        menu.add_command(label="导出此地图", command=lambda: self._export_single_map(map_id))
        menu.add_separator()
        menu.add_command(label="删除地图", command=lambda: self._delete_map(map_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _export_single_map(self, map_id: int) -> None:
        import datetime
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

    # ================= 分类树 =================
    def _refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        if not self.current_map:
            return
        map_id = self.current_map["id"]
        cats = self.svc.list_categories(map_id)
        for c in cats:
            node = self.tree.insert("", "end", iid=f"cat_{c['id']}", text=f"▸ {c['name']}", open=False)
            # 懒加载：展开时再填充瞄点
            self.tree.insert(node, "end", iid=f"ph_{c['id']}", text="加载中…")
        # 地图直属虚拟节点
        direct = self.tree.insert("", "end", iid=DIRECT_NODE, text="▸ (地图直属)", open=False)
        self.tree.insert(direct, "end", iid="ph_direct", text="加载中…")

        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open, add="+")

    def _on_tree_open(self, event) -> None:
        node = self.tree.focus()
        children = self.tree.get_children(node)
        # 若只有占位节点，填充真实瞄点
        if len(children) == 1 and children[0].startswith("ph_"):
            self.tree.delete(children[0])
            self._populate_spots(node)

    def _populate_spots(self, node: str) -> None:
        if node == DIRECT_NODE:
            spots = self.svc.list_map_direct_spots(self.current_map["id"])
        elif node.startswith("cat_"):
            cat_id = int(node[4:])
            spots = self.svc.list_spots_by_category(cat_id)
        else:
            return
        for s in spots:
            self.tree.insert(node, "end", iid=f"spot_{s['id']}", text=f"· {s['name']}")

    def _on_tree_select(self, _e=None) -> None:
        sel = self.tree.focus()
        if not sel:
            return
        if sel.startswith("spot_"):
            spot_id = int(sel[5:])
            self.current_spot = self.svc.get_spot(spot_id)
            # 同步当前分类上下文
            self._sync_category_from_spot(self.current_spot)
            self._show_spot_detail(self.current_spot)
        elif sel.startswith("cat_"):
            self.current_category_id = int(sel[4:])
            self.current_spot = None
            self._show_category_grid()
        elif sel == DIRECT_NODE:
            self.current_category_id = DIRECT_NODE
            self.current_spot = None
            self._show_category_grid()
        self._update_status()

    def _sync_category_from_spot(self, spot: dict | None) -> None:
        if not spot:
            return
        self.current_category_id = spot.get("category_id") or DIRECT_NODE

    def _on_tree_right_click(self, event) -> None:
        node = self.tree.identify_row(event.y)
        if not node:
            return
        self.tree.selection_set(node)
        self.tree.focus(node)
        menu = tk.Menu(self.root, tearoff=0, bg=T.COLOR_CARD, fg=T.COLOR_TEXT,
                       activebackground=T.COLOR_ACCENT, activeforeground="#1a1a1a")
        if node.startswith("cat_"):
            cat_id = int(node[4:])
            menu.add_command(label="在此分类下新建瞄点", command=lambda: self._open_add("瞄点", cat_id))
            menu.add_command(label="重命名分类", command=lambda: self._rename_category(cat_id))
            menu.add_separator()
            menu.add_command(label="删除分类", command=lambda: self._delete_category(cat_id))
        elif node == DIRECT_NODE:
            menu.add_command(label="新建地图直属瞄点", command=lambda: self._open_add("瞄点", None))
        elif node.startswith("spot_"):
            spot_id = int(node[5:])
            menu.add_command(label="编辑瞄点", command=lambda: self._edit_spot(spot_id))
            menu.add_separator()
            menu.add_command(label="删除瞄点", command=lambda: self._delete_spot(spot_id))
        else:
            return
        menu.tk_popup(event.x_root, event.y_root)

    # ================= 右侧展示区 =================
    def _clear_display(self) -> None:
        for w in self.disp_inner.winfo_children():
            w.destroy()
        self._thumb_refs.clear()
        self._spot_grid_items.clear()
        self.disp_canvas.yview_moveto(0)

    def _show_empty(self, text: str) -> None:
        self._clear_display()
        tk.Label(self.disp_inner, text=text, bg=T.COLOR_BG, fg=T.COLOR_TEXT_DIM,
                 font=T.FONT_BASE).pack(pady=60)

    def _show_category_grid(self) -> None:
        if not self.current_map:
            self._show_empty("请先选择地图")
            return
        if self.current_category_id == DIRECT_NODE:
            spots = self.svc.list_map_direct_spots(self.current_map["id"])
            title = f"{self.current_map['name']} / 地图直属"
        elif isinstance(self.current_category_id, int):
            cat = self.svc.dao.categories.get(self.current_category_id)
            spots = self.svc.list_spots_by_category(self.current_category_id)
            title = f"{self.current_map['name']} / {cat['name'] if cat else ''}"
        else:
            spots = self.svc.list_spots_by_map(self.current_map["id"])
            title = f"{self.current_map['name']} / 全部瞄点"

        self._render_grid(title, spots)

    def _render_grid(self, title: str, spots: list[dict]) -> None:
        self._clear_display()
        header = tk.Label(self.disp_inner, text=title, bg=T.COLOR_BG, fg=T.COLOR_TEXT,
                          font=("Microsoft YaHei UI", 13, "bold"), anchor="w")
        header.pack(fill="x", padx=20, pady=(16, 8))

        if not spots:
            tk.Label(self.disp_inner, text="暂无瞄点，点击右下角 ＋ 添加",
                     bg=T.COLOR_BG, fg=T.COLOR_TEXT_DIM, font=T.FONT_BASE).pack(pady=40)
            return

        grid = tk.Frame(self.disp_inner, bg=T.COLOR_BG)
        grid.pack(fill="x", padx=14, pady=6)
        cols = 4
        for i, s in enumerate(spots):
            r, c = divmod(i, cols)
            self._make_spot_card(grid, s).grid(row=r, column=c, padx=8, pady=8, sticky="nsew")
            grid.columnconfigure(c, weight=1, uniform="card")

    def _make_spot_card(self, parent, spot: dict) -> tk.Frame:
        card = tk.Frame(parent, bg=T.COLOR_CARD, bd=0, highlightthickness=1,
                        highlightbackground=T.COLOR_BORDER, cursor="hand2")
        img_lbl = tk.Label(card, bg=T.COLOR_CARD, fg=T.COLOR_TEXT_DIM, text="无图片",
                           font=T.FONT_SMALL, width=22, height=7)
        thumb = self.svc.images.thumbnail_path(spot.get("image_path"), size=160)
        if thumb and thumb.exists():
            try:
                from PIL import Image, ImageTk
                im = Image.open(thumb)
                im.thumbnail((160, 110), Image.LANCZOS)
                photo = ImageTk.PhotoImage(im)
                img_lbl.configure(image=photo, text="")
                self._thumb_refs.append(photo)
            except Exception:  # noqa: BLE001
                pass
        img_lbl.pack(padx=6, pady=(8, 2))

        name_lbl = tk.Label(card, text=spot["name"], bg=T.COLOR_CARD, fg=T.COLOR_TEXT,
                            font=T.FONT_BOLD, wraplength=160, justify="center")
        name_lbl.pack(padx=6, pady=(0, 8))

        for w in (card, img_lbl, name_lbl):
            w.bind("<Button-1>", lambda e, sid=spot["id"]: self._on_card_click(sid))
        return card

    def _on_card_click(self, spot_id: int) -> None:
        spot = self.svc.get_spot(spot_id)
        self.current_spot = spot
        # 在树中选中对应节点
        iid = f"spot_{spot_id}"
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)
        self._show_spot_detail(spot)
        self._update_status()

    def _show_spot_detail(self, spot: dict | None) -> None:
        if not spot:
            return
        self._clear_display()
        wrap = tk.Frame(self.disp_inner, bg=T.COLOR_BG)
        wrap.pack(fill="both", expand=True, padx=20, pady=16)

        # 顶部操作行
        top = tk.Frame(wrap, bg=T.COLOR_BG)
        top.pack(fill="x")
        tk.Label(top, text=spot["name"], bg=T.COLOR_BG, fg=T.COLOR_TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(side="left")
        ttk.Button(top, text="删除", style="Danger.TButton",
                   command=lambda: self._delete_spot(spot["id"])).pack(side="right", padx=(8, 0))
        ttk.Button(top, text="编辑",
                   command=lambda: self._edit_spot(spot["id"])).pack(side="right")

        cat_txt = "地图直属"
        if spot.get("category_id"):
            cat = self.svc.dao.categories.get(spot["category_id"])
            cat_txt = cat["name"] if cat else "地图直属"
        tk.Label(wrap, text=f"地图: {self.current_map['name'] if self.current_map else '?'}   分类: {cat_txt}",
                 bg=T.COLOR_BG, fg=T.COLOR_TEXT_DIM, font=T.FONT_SMALL, anchor="w").pack(fill="x", pady=(4, 10))

        # 大图
        img_box = tk.Label(wrap, bg=T.COLOR_CARD, fg=T.COLOR_TEXT_DIM, text="无图片",
                           font=T.FONT_BASE)
        img_box.pack(fill="x", pady=6)
        abs_p = config.abspath(spot.get("image_path"))
        if abs_p and abs_p.exists():
            try:
                from PIL import Image, ImageTk
                im = Image.open(abs_p)
                im.thumbnail((720, 420), Image.LANCZOS)
                photo = ImageTk.PhotoImage(im)
                img_box.configure(image=photo, text="", cursor="hand2")
                img_box.bind("<Button-1>", lambda e, p=str(abs_p): open_image_viewer(self.root, p))
                self._thumb_refs.append(photo)
            except Exception as ex:  # noqa: BLE001
                img_box.configure(text=f"图片加载失败: {ex}", image="")
        img_box.pack(pady=6)

        # 描述
        tk.Label(wrap, text="描述：", bg=T.COLOR_BG, fg=T.COLOR_TEXT_DIM,
                 font=T.FONT_BOLD, anchor="w").pack(fill="x", pady=(10, 2))
        desc = tk.Label(wrap, text=spot.get("description") or "（无描述）",
                        bg=T.COLOR_BG, fg=T.COLOR_TEXT, font=T.FONT_BASE,
                        wraplength=760, justify="left", anchor="nw")
        desc.pack(fill="x")

    # ================= 新增 / 编辑 / 删除 =================
    def _open_add(self, default_type: str = None, force_category=None) -> None:
        if default_type is None:
            default_type = "瞄点" if self.current_map else "地图"
        if not self.current_map and default_type in ("瞄点", "分类"):
            default_type = "地图"

        cat_id = force_category
        cat_name = None
        if cat_id == DIRECT_NODE:
            cat_id = None
        if isinstance(cat_id, int):
            cat = self.svc.dao.categories.get(cat_id)
            cat_name = cat["name"] if cat else None
        elif self.current_category_id == DIRECT_NODE:
            cat_id, cat_name = None, None
        elif isinstance(self.current_category_id, int) and cat_id is None:
            cat_id = self.current_category_id
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
                    map_id=ctx["map_id"],
                    name=result["name"],
                    description=result.get("description", ""),
                    image_src=result.get("image_src"),
                    category_id=ctx.get("category_id"),
                )
                self._refresh_tree()
                # 展开并选中新瞄点
                self._reveal_spot(new_id, ctx.get("category_id"))
            self._refresh_display()
            self._update_status()
        except ServiceError as e:
            messagebox.showerror("操作失败", str(e))

    def _reveal_spot(self, spot_id: int, category_id: int | None) -> None:
        parent = f"cat_{category_id}" if category_id else DIRECT_NODE
        if self.tree.exists(parent):
            self.tree.item(parent, open=True)
            self._populate_if_placeholder(parent)
            iid = f"spot_{spot_id}"
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
                self.tree.see(iid)

    def _populate_if_placeholder(self, node: str) -> None:
        children = self.tree.get_children(node)
        if len(children) == 1 and children[0].startswith("ph_"):
            self.tree.delete(children[0])
            self._populate_spots(node)

    def _edit_spot(self, spot_id: int) -> None:
        spot = self.svc.get_spot(spot_id)
        if not spot:
            return
        result = add_page.open_edit_spot(self.root, spot, self.ctx.images)
        if not result:
            return
        try:
            self.svc.update_spot(
                spot_id,
                name=result["name"],
                description=result["description"],
                new_image_src=result.get("image_src"),
                remove_image=result.get("remove_image", False),
            )
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
        new_name = ask_text(self.root, "重命名分类", "分类名称：", cat["name"])
        if not new_name:
            return
        try:
            self.svc.rename_category(cat_id, new_name)
            self._refresh_tree()
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
        new_name = ask_text(self.root, "重命名地图", "地图名称：", m["name"])
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
        map_id = None
        cat_id = None
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
        tk.Label(self.disp_inner, text=f"搜索“{kw}” — 命中 {len(results)} 条",
                 bg=T.COLOR_BG, fg=T.COLOR_TEXT, font=("Microsoft YaHei UI", 13, "bold"),
                 anchor="w").pack(fill="x", padx=20, pady=(16, 8))
        if not results:
            tk.Label(self.disp_inner, text="没有匹配的瞄点", bg=T.COLOR_BG,
                     fg=T.COLOR_TEXT_DIM, font=T.FONT_BASE).pack(pady=40)
            return
        for s in results:
            row = tk.Frame(self.disp_inner, bg=T.COLOR_CARD, cursor="hand2",
                           highlightthickness=1, highlightbackground=T.COLOR_BORDER)
            row.pack(fill="x", padx=16, pady=4)
            loc = f"{s.get('map_name', '')} / {s.get('category_name') or '地图直属'}"
            tk.Label(row, text=s["name"], bg=T.COLOR_CARD, fg=T.COLOR_TEXT,
                     font=T.FONT_BOLD, anchor="w").pack(fill="x", padx=12, pady=(8, 0))
            tk.Label(row, text=loc, bg=T.COLOR_CARD, fg=T.COLOR_ACCENT,
                     font=T.FONT_SMALL, anchor="w").pack(fill="x", padx=12)
            desc = (s.get("description") or "").replace("\n", " ")
            if len(desc) > 60:
                desc = desc[:60] + "…"
            tk.Label(row, text=desc or "（无描述）", bg=T.COLOR_CARD, fg=T.COLOR_TEXT_DIM,
                     font=T.FONT_SMALL, anchor="w", wraplength=820, justify="left").pack(fill="x", padx=12, pady=(0, 8))
            for child in row.winfo_children():
                child.bind("<Button-1>", lambda e, sid=s["id"]: self._jump_to_spot(sid))
            row.bind("<Button-1>", lambda e, sid=s["id"]: self._jump_to_spot(sid))

    def _jump_to_spot(self, spot_id: int) -> None:
        spot = self.svc.get_spot(spot_id)
        if not spot:
            return
        self.search_var.set("")
        self._select_map(spot["map_id"])
        self.current_spot = spot
        self._sync_category_from_spot(spot)
        parent = f"cat_{spot['category_id']}" if spot.get("category_id") else DIRECT_NODE
        if self.tree.exists(parent):
            self.tree.item(parent, open=True)
            self._populate_if_placeholder(parent)
            iid = f"spot_{spot_id}"
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
                self.tree.see(iid)
        self._show_spot_detail(spot)

    def _refresh_display(self) -> None:
        if self.search_var.get().strip():
            self._do_search()
        elif self.current_spot:
            self._show_spot_detail(self.current_spot)
        elif self.current_category_id is not None:
            self._show_category_grid()
        elif self.current_map:
            # 显示整张地图的所有瞄点
            spots = self.svc.list_spots_by_map(self.current_map["id"])
            self._render_grid(f"{self.current_map['name']} / 全部瞄点", spots)
        else:
            self._show_empty("请先选择或新建地图")

    # ================= 导入 / 导出 / 设置 =================
    def _on_export(self) -> None:
        if not self.svc.list_maps():
            messagebox.showinfo("提示", "暂无数据可导出")
            return
        scope_all = messagebox.askyesno("导出范围", "导出全部地图？\n选择“否”则仅导出当前地图。")
        map_id = None if scope_all or not self.current_map else self.current_map["id"]
        default_name = f"aim_backup_{__import__('datetime').datetime.now():%Y%m%d_%H%M%S}.zip"
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
        # 冲突策略
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
                 fg=T.COLOR_TEXT, font=T.FONT_BASE).pack(padx=20, pady=(18, 10), anchor="w")
        result = {"v": None}

        def pick(v):
            result["v"] = v
            dlg.destroy()

        ttk.Button(dlg, text="跳过（保留现有，忽略备份中的重复地图）",
                   command=lambda: pick("skip")).pack(fill="x", padx=20, pady=4)
        ttk.Button(dlg, text="覆盖（删除现有同名地图，用备份替换）",
                   command=lambda: pick("overwrite")).pack(fill="x", padx=20, pady=4)
        ttk.Button(dlg, text="合并为副本（导入为“xxx(导入)”新地图）",
                   command=lambda: pick("duplicate")).pack(fill="x", padx=20, pady=4)
        ttk.Button(dlg, text="取消", command=lambda: pick(None)).pack(pady=12)
        self.root.wait_window(dlg)
        return result["v"]

    def _open_settings(self) -> None:
        from .settings_dialog import open_settings
        open_settings(self.root, self.ctx)
        self._refresh_tree()
        self._refresh_display()
        self._update_status()
