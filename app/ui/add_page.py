"""添加/编辑对话框。

统一入口 open_add_dialog(...) / open_edit_spot(...)，返回结果 dict 或 None。
瞄点支持多张图片：可从磁盘多选、Ctrl+V 多次粘贴，缩略图可单张移除。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import config
from ..services.image_service import ImageService
from . import theme as T

ADD_TYPES = ("瞄点", "分类", "地图")


class _ThumbGallery(ttk.Frame):
    """多图缩略图画廊：自动换行网格，每张带「× 移除」。

    item = {"value": 提交用的值, "load": 加载缩略图的路径, "kind": "disk"|"existing"}
    - 新建：value 为磁盘绝对路径（含粘贴生成的临时文件）
    - 编辑：已存在图 value 为相对路径，新增图 value 为磁盘绝对路径
    """

    THUMB_W, THUMB_H = 100, 68
    PER_ROW = 4

    def __init__(self, master, on_change=None):
        super().__init__(master, style="Panel.TFrame")
        self._items: list[dict] = []
        self._photos: list = []          # 保持 PhotoImage 引用，防止被回收
        self._on_change = on_change
        self._grid = ttk.Frame(self, style="Panel.TFrame")
        self._grid.pack(fill="x")
        self._empty = ttk.Label(self, text="（无图片）", style="PanelDim.TLabel")
        self._empty.pack(anchor="w")

    # ---- 数据操作 ----
    def add_disk(self, path: str) -> None:
        if not path:
            return
        self._items.append({"value": path, "load": path, "kind": "disk"})
        self._refresh()

    def add_existing(self, rel: str) -> None:
        if not rel:
            return
        p = config.abspath(rel)
        self._items.append({"value": rel, "load": str(p) if p else None, "kind": "existing"})
        self._refresh()

    def remove(self, idx: int) -> None:
        if 0 <= idx < len(self._items):
            self._items.pop(idx)
            self._refresh()

    def values(self) -> list[str]:
        return [it["value"] for it in self._items]

    def count(self) -> int:
        return len(self._items)

    # ---- 渲染 ----
    def _refresh(self) -> None:
        for w in self._grid.winfo_children():
            w.destroy()
        self._photos.clear()
        if self._items:
            self._empty.pack_forget()
        else:
            self._empty.pack(anchor="w")

        for i, it in enumerate(self._items):
            r, c = divmod(i, self.PER_ROW)
            cell = tk.Frame(self._grid, bg=T.COLOR_PANEL, bd=0)
            cell.grid(row=r, column=c, padx=4, pady=4, sticky="n")

            photo = self._make_thumb(it.get("load"))
            if photo is not None:
                self._photos.append(photo)
                lbl = tk.Label(cell, image=photo, bg=T.COLOR_PANEL, bd=0)
            else:
                lbl = tk.Label(cell, text="预览失败", bg=T.COLOR_PANEL, fg=T.COLOR_TEXT_DIM,
                               width=13, height=4, font=T.FONT_SMALL)
            lbl.pack()

            rm = tk.Label(cell, text="× 移除", bg=T.COLOR_PANEL, fg=T.COLOR_DANGER,
                          font=T.FONT_SMALL, cursor="hand2")
            rm.pack(pady=(2, 0))
            rm.bind("<Button-1>", lambda e, idx=i: self.remove(idx))

        if self._on_change:
            self._on_change()

    def _make_thumb(self, path: str | None):
        if not path:
            return None
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail((self.THUMB_W, self.THUMB_H), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:  # noqa: BLE001
            return None


class _AddDialog(tk.Toplevel):
    """新增对象模态对话框。根据 type 与上下文动态渲染表单。"""

    def __init__(self, master, obj_type: str, ctx: dict, image_service: ImageService):
        super().__init__(master)
        self.obj_type = obj_type
        self.ctx = ctx  # {map_id, map_name, category_id, category_name, allow_type_switch}
        self.images = image_service
        self.result: dict | None = None

        self.title(f"新建{obj_type}")
        self.configure(bg=T.COLOR_PANEL)
        self.resizable(False, True)
        self.transient(master)
        self.grab_set()

        self._build()
        self._center(master)
        self.bind("<Control-v>", self._on_paste)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    # ---- 布局 ----
    def _build(self) -> None:
        pad = {"padx": 16, "pady": 8}
        top = ttk.Frame(self, style="Panel.TFrame")
        top.pack(fill="x", **pad)

        if self.ctx.get("allow_type_switch", True):
            ttk.Label(top, text="类型：", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
            self.type_var = tk.StringVar(value=self.obj_type)
            box = ttk.Combobox(top, textvariable=self.type_var, values=list(ADD_TYPES),
                               state="readonly", width=10)
            box.grid(row=0, column=1, sticky="w")
            box.bind("<<ComboboxSelected>>", self._on_type_change)
        else:
            self.type_var = tk.StringVar(value=self.obj_type)

        self.body = ttk.Frame(self, style="Panel.TFrame")
        self.body.pack(fill="both", expand=True, padx=16, pady=4)
        self._render_body()

        btns = ttk.Frame(self, style="Panel.TFrame")
        btns.pack(fill="x", padx=16, pady=14)
        ttk.Button(btns, text="取消", command=self._on_cancel).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="保存", style="Accent.TButton", command=self._on_submit).pack(side="right")

    def _render_body(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        t = self.type_var.get()

        row = ttk.Frame(self.body, style="Panel.TFrame")
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="名称：", style="Panel.TLabel").pack(side="left")
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(row, textvariable=self.name_var, width=36)
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.name_entry.focus_set()

        if t == "分类":
            map_name = self.ctx.get("map_name") or "（未选择地图）"
            ttk.Label(self.body, text=f"归属地图：{map_name}",
                      style="PanelDim.TLabel").pack(anchor="w", pady=(2, 6))
        if t == "瞄点":
            self._render_spot_extra()

    def _render_spot_extra(self) -> None:
        map_name = self.ctx.get("map_name") or "（未选择地图）"
        cat_name = self.ctx.get("category_name") or "地图直属"
        ttk.Label(self.body, text=f"归属：{map_name} / {cat_name}",
                  style="PanelDim.TLabel").pack(anchor="w", pady=(2, 6))

        # 图片区（多图）
        img_frame = ttk.Frame(self.body, style="Panel.TFrame")
        img_frame.pack(fill="x", pady=6)
        ttk.Label(img_frame, text="图片：", style="Panel.TLabel").pack(side="left", anchor="n")
        right = ttk.Frame(img_frame, style="Panel.TFrame")
        right.pack(side="left", fill="x", expand=True, padx=(6, 0))

        btns = ttk.Frame(right, style="Panel.TFrame")
        btns.pack(fill="x")
        ttk.Button(btns, text="添加图片…", command=self._on_choose_images).pack(side="left")
        ttk.Button(btns, text="粘贴(Ctrl+V)", command=self._on_paste).pack(side="left", padx=8)
        ttk.Label(btns, text="可添加多张", style="PanelDim.TLabel").pack(side="left", padx=(4, 0))

        self.gallery = _ThumbGallery(right)
        self.gallery.pack(fill="x", pady=(8, 0))

        # 描述
        ttk.Label(self.body, text="描述：", style="Panel.TLabel").pack(anchor="w", pady=(6, 2))
        self.desc_text = tk.Text(self.body, height=5, width=44, bg=T.COLOR_PANEL,
                                 fg=T.COLOR_TEXT, insertbackground=T.COLOR_TEXT,
                                 relief="flat", bd=0, highlightthickness=1,
                                 highlightbackground=T.COLOR_INPUT_BORDER,
                                 highlightcolor=T.COLOR_INPUT_BORDER,
                                 font=T.FONT_BASE, wrap="word")
        self.desc_text.pack(fill="x")

    def _on_type_change(self, _e=None) -> None:
        new_type = self.type_var.get()
        if new_type in ("分类", "瞄点") and not self.ctx.get("map_id"):
            messagebox.showwarning("提示", "请先在地图横栏选择一个地图", parent=self)
            self.type_var.set("地图")
            new_type = "地图"
        self.obj_type = new_type
        self.title(f"新建{new_type}")
        self._render_body()

    # ---- 图片操作 ----
    def _on_choose_images(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self, title="选择图片（可多选）",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.webp"), ("所有文件", "*.*")],
        )
        for p in paths:
            self.gallery.add_disk(p)

    def _on_paste(self, _e=None) -> None:
        if self.type_var.get() != "瞄点":
            return
        try:
            tmp = self.images.clipboard_to_temp()
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("粘贴失败", str(ex), parent=self)
            return
        if not tmp:
            messagebox.showinfo("提示", "剪贴板中没有图片", parent=self)
            return
        self.gallery.add_disk(tmp)

    # ---- 提交/取消 ----
    def _on_submit(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "名称不能为空", parent=self)
            return
        t = self.type_var.get()
        payload = {"type": t, "name": name}
        if t == "瞄点":
            payload["description"] = self.desc_text.get("1.0", "end").strip()
            payload["image_srcs"] = self.gallery.values()
        self.result = payload
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()

    def _center(self, master) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        try:
            mx = master.winfo_rootx() + (master.winfo_width() - w) // 2
            my = master.winfo_rooty() + (master.winfo_height() - h) // 2
        except Exception:
            mx, my = 200, 200
        self.geometry(f"+{max(0, mx)}+{max(0, my)}")


class _EditSpotDialog(tk.Toplevel):
    """编辑瞄点：名称 / 描述 / 多图（增删）。"""

    def __init__(self, master, spot: dict, image_service: ImageService):
        super().__init__(master)
        self.spot = spot
        self.images = image_service
        self.result: dict | None = None

        self.title("编辑瞄点")
        self.configure(bg=T.COLOR_PANEL)
        self.resizable(False, True)
        self.transient(master)
        self.grab_set()
        self._build()
        self._center(master)
        self.bind("<Control-v>", self._on_paste)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _build(self) -> None:
        body = ttk.Frame(self, style="Panel.TFrame")
        body.pack(fill="both", expand=True, padx=16, pady=14)

        row = ttk.Frame(body, style="Panel.TFrame")
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="名称：", style="Panel.TLabel").pack(side="left")
        self.name_var = tk.StringVar(value=self.spot.get("name", ""))
        ttk.Entry(row, textvariable=self.name_var, width=36).pack(side="left", fill="x", expand=True, padx=(6, 0))

        img_frame = ttk.Frame(body, style="Panel.TFrame")
        img_frame.pack(fill="x", pady=6)
        ttk.Label(img_frame, text="图片：", style="Panel.TLabel").pack(side="left", anchor="n")
        right = ttk.Frame(img_frame, style="Panel.TFrame")
        right.pack(side="left", fill="x", expand=True, padx=(6, 0))
        btns = ttk.Frame(right, style="Panel.TFrame")
        btns.pack(fill="x")
        ttk.Button(btns, text="添加图片…", command=self._on_choose_images).pack(side="left")
        ttk.Button(btns, text="粘贴(Ctrl+V)", command=self._on_paste).pack(side="left", padx=8)
        ttk.Label(btns, text="点缩略图下「× 移除」删图", style="PanelDim.TLabel").pack(side="left", padx=(4, 0))

        self.gallery = _ThumbGallery(right)
        self.gallery.pack(fill="x", pady=(8, 0))
        # 载入已有图片
        for rel in (self.spot.get("images") or []):
            self.gallery.add_existing(rel)

        ttk.Label(body, text="描述：", style="Panel.TLabel").pack(anchor="w", pady=(6, 2))
        self.desc_text = tk.Text(body, height=5, width=44, bg=T.COLOR_PANEL, fg=T.COLOR_TEXT,
                                 insertbackground=T.COLOR_TEXT, relief="flat", bd=0,
                                 highlightthickness=1, highlightbackground=T.COLOR_INPUT_BORDER,
                                 highlightcolor=T.COLOR_INPUT_BORDER,
                                 font=T.FONT_BASE, wrap="word")
        self.desc_text.insert("1.0", self.spot.get("description", ""))
        self.desc_text.pack(fill="x")

        btns2 = ttk.Frame(self, style="Panel.TFrame")
        btns2.pack(fill="x", padx=16, pady=14)
        ttk.Button(btns2, text="取消", command=self._on_cancel).pack(side="right", padx=(8, 0))
        ttk.Button(btns2, text="保存", style="Accent.TButton", command=self._on_submit).pack(side="right")

    def _on_choose_images(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self, title="选择图片（可多选）",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.webp"), ("所有文件", "*.*")])
        for p in paths:
            self.gallery.add_disk(p)

    def _on_paste(self, _e=None) -> None:
        try:
            tmp = self.images.clipboard_to_temp()
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("粘贴失败", str(ex), parent=self)
            return
        if not tmp:
            messagebox.showinfo("提示", "剪贴板中没有图片", parent=self)
            return
        self.gallery.add_disk(tmp)

    def _on_submit(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "名称不能为空", parent=self)
            return
        self.result = {
            "name": name,
            "description": self.desc_text.get("1.0", "end").strip(),
            "image_sources": self.gallery.values(),
        }
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()

    def _center(self, master) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        try:
            mx = master.winfo_rootx() + (master.winfo_width() - w) // 2
            my = master.winfo_rooty() + (master.winfo_height() - h) // 2
        except Exception:
            mx, my = 200, 200
        self.geometry(f"+{max(0, mx)}+{max(0, my)}")


def open_add_dialog(master, ctx: dict, image_service: ImageService,
                    default_type: str = "瞄点") -> dict | None:
    dlg = _AddDialog(master, default_type, ctx, image_service)
    master.wait_window(dlg)
    return dlg.result


def open_edit_spot(master, spot: dict, image_service: ImageService) -> dict | None:
    dlg = _EditSpotDialog(master, spot, image_service)
    master.wait_window(dlg)
    return dlg.result
