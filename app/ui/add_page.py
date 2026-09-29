"""添加/编辑对话框。

统一入口 open_add_dialog(...) / open_edit_spot(...)，返回结果 dict 或 None。
支持从磁盘选择图片或 Ctrl+V 粘贴剪贴板截图。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import config
from ..services.image_service import ImageService
from . import theme as T

ADD_TYPES = ("瞄点", "分类", "地图")


class _AddDialog(tk.Toplevel):
    """新增对象模态对话框。根据 type 与上下文动态渲染表单。"""

    def __init__(self, master, obj_type: str, ctx: dict, image_service: ImageService):
        super().__init__(master)
        self.obj_type = obj_type
        self.ctx = ctx  # {map_id, map_name, category_id, category_name, allow_type_switch}
        self.images = image_service
        self.result: dict | None = None
        self._image_src: str | None = None   # 待提交的磁盘图片路径
        self._preview = None

        self.title(f"新建{obj_type}")
        self.configure(bg=T.COLOR_PANEL)
        self.resizable(False, False)
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

        # 类型切换（仅当允许时）
        if self.ctx.get("allow_type_switch", True):
            ttk.Label(top, text="类型：", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
            self.type_var = tk.StringVar(value=self.obj_type)
            types = list(ADD_TYPES)
            box = ttk.Combobox(top, textvariable=self.type_var, values=types,
                               state="readonly", width=10)
            box.grid(row=0, column=1, sticky="w")
            box.bind("<<ComboboxSelected>>", self._on_type_change)
        else:
            self.type_var = tk.StringVar(value=self.obj_type)

        self.body = ttk.Frame(self, style="Panel.TFrame")
        self.body.pack(fill="both", expand=True, padx=16, pady=4)
        self._render_body()

        # 底部按钮
        btns = ttk.Frame(self, style="Panel.TFrame")
        btns.pack(fill="x", padx=16, pady=14)
        ttk.Button(btns, text="取消", command=self._on_cancel).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="保存", style="Accent.TButton", command=self._on_submit).pack(side="right")

    def _render_body(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        t = self.type_var.get()

        # 名称（三种类型都有）
        row = ttk.Frame(self.body, style="Panel.TFrame")
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="名称：", style="Panel.TLabel").pack(side="left")
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(row, textvariable=self.name_var, width=36)
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.name_entry.focus_set()

        # 归属提示
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

        # 图片区
        img_frame = ttk.Frame(self.body, style="Panel.TFrame")
        img_frame.pack(fill="x", pady=6)
        ttk.Label(img_frame, text="图片：", style="Panel.TLabel").pack(side="left", anchor="n")
        right = ttk.Frame(img_frame, style="Panel.TFrame")
        right.pack(side="left", fill="x", expand=True, padx=(6, 0))

        btns = ttk.Frame(right, style="Panel.TFrame")
        btns.pack(fill="x")
        ttk.Button(btns, text="选择图片…", command=self._on_choose_image).pack(side="left")
        ttk.Button(btns, text="粘贴(Ctrl+V)", command=self._on_paste).pack(side="left", padx=8)
        self.clear_img_btn = ttk.Button(btns, text="移除", command=self._on_clear_image, state="disabled")
        self.clear_img_btn.pack(side="left")

        self.preview_label = tk.Label(right, text="（无图片）", bg=T.COLOR_CARD, fg=T.COLOR_TEXT_DIM,
                                      width=36, height=6, font=T.FONT_SMALL)
        self.preview_label.pack(fill="x", pady=(8, 0))

        # 描述
        ttk.Label(self.body, text="描述：", style="Panel.TLabel").pack(anchor="w", pady=(6, 2))
        self.desc_text = tk.Text(self.body, height=5, width=44, bg=T.COLOR_CARD,
                                 fg=T.COLOR_TEXT, insertbackground=T.COLOR_TEXT,
                                 relief="flat", font=T.FONT_BASE, wrap="word")
        self.desc_text.pack(fill="x")

    def _on_type_change(self, _e=None) -> None:
        new_type = self.type_var.get()
        # 切换类型时校验上下文（分类/瞄点必须有选中地图）
        if new_type in ("分类", "瞄点") and not self.ctx.get("map_id"):
            messagebox.showwarning("提示", "请先在地图横栏选择一个地图", parent=self)
            self.type_var.set("地图")
            new_type = "地图"
        self.obj_type = new_type
        self.title(f"新建{new_type}")
        self._render_body()

    # ---- 图片操作 ----
    def _on_choose_image(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.webp"), ("所有文件", "*.*")],
        )
        if path:
            self._image_src = path
            self._show_preview_from_file(path)

    def _on_paste(self, _e=None) -> None:
        if self.type_var.get() != "瞄点":
            return
        try:
            rel = self.images.import_from_clipboard()
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("粘贴失败", str(ex), parent=self)
            return
        if not rel:
            messagebox.showinfo("提示", "剪贴板中没有图片", parent=self)
            return
        # 粘贴会立即落盘，这里记录绝对路径以便预览与提交
        abs_p = config.abspath(rel)
        self._image_src = str(abs_p)
        self._pasted_rel = rel
        self._show_preview_from_file(abs_p)

    def _show_preview_from_file(self, path) -> None:
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail((280, 140), Image.LANCZOS)
            self._preview = ImageTk.PhotoImage(img)
            self.preview_label.configure(image=self._preview, text="")
            self.clear_img_btn.configure(state="normal")
        except Exception as ex:  # noqa: BLE001
            self.preview_label.configure(text=f"预览失败: {ex}", image="")

    def _on_clear_image(self) -> None:
        self._image_src = None
        self._preview = None
        self.preview_label.configure(image="", text="（无图片）")
        self.clear_img_btn.configure(state="disabled")

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
            payload["image_src"] = self._image_src
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
    """编辑瞄点：名称 / 描述 / 图片（替换或移除）。"""

    def __init__(self, master, spot: dict, image_service: ImageService):
        super().__init__(master)
        self.spot = spot
        self.images = image_service
        self.result: dict | None = None
        self._image_src: str | None = None
        self._remove_image = False
        self._preview = None

        self.title("编辑瞄点")
        self.configure(bg=T.COLOR_PANEL)
        self.resizable(False, False)
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
        ttk.Button(btns, text="替换…", command=self._on_choose_image).pack(side="left")
        ttk.Button(btns, text="粘贴(Ctrl+V)", command=self._on_paste).pack(side="left", padx=8)
        ttk.Button(btns, text="移除图片", command=self._on_remove_image).pack(side="left")

        self.preview_label = tk.Label(right, bg=T.COLOR_CARD, fg=T.COLOR_TEXT_DIM,
                                      width=36, height=6, font=T.FONT_SMALL)
        self.preview_label.pack(fill="x", pady=(8, 0))
        self._load_current_preview()

        ttk.Label(body, text="描述：", style="Panel.TLabel").pack(anchor="w", pady=(6, 2))
        self.desc_text = tk.Text(body, height=5, width=44, bg=T.COLOR_CARD, fg=T.COLOR_TEXT,
                                 insertbackground=T.COLOR_TEXT, relief="flat",
                                 font=T.FONT_BASE, wrap="word")
        self.desc_text.insert("1.0", self.spot.get("description", ""))
        self.desc_text.pack(fill="x")

        btns2 = ttk.Frame(self, style="Panel.TFrame")
        btns2.pack(fill="x", padx=16, pady=14)
        ttk.Button(btns2, text="取消", command=self._on_cancel).pack(side="right", padx=(8, 0))
        ttk.Button(btns2, text="保存", style="Accent.TButton", command=self._on_submit).pack(side="right")

    def _load_current_preview(self) -> None:
        rel = self.spot.get("image_path")
        if rel:
            p = config.abspath(rel)
            if p and p.exists():
                self._show_preview(p)
                return
        self.preview_label.configure(text="（无图片）", image="")

    def _on_choose_image(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.webp"), ("所有文件", "*.*")])
        if path:
            self._image_src = path
            self._remove_image = False
            self._show_preview(path)

    def _on_paste(self, _e=None) -> None:
        try:
            rel = self.images.import_from_clipboard()
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("粘贴失败", str(ex), parent=self)
            return
        if not rel:
            messagebox.showinfo("提示", "剪贴板中没有图片", parent=self)
            return
        self._image_src = str(config.abspath(rel))
        self._remove_image = False
        self._show_preview(self._image_src)

    def _on_remove_image(self) -> None:
        self._image_src = None
        self._remove_image = True
        self._preview = None
        self.preview_label.configure(image="", text="（无图片）")

    def _show_preview(self, path) -> None:
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail((280, 140), Image.LANCZOS)
            self._preview = ImageTk.PhotoImage(img)
            self.preview_label.configure(image=self._preview, text="")
        except Exception as ex:  # noqa: BLE001
            self.preview_label.configure(text=f"预览失败: {ex}", image="")

    def _on_submit(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "名称不能为空", parent=self)
            return
        self.result = {
            "name": name,
            "description": self.desc_text.get("1.0", "end").strip(),
            "image_src": self._image_src,
            "remove_image": self._remove_image,
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
