"""大图查看窗口。

支持单张或多张图片：
    open_image_viewer(root, "path.png")           # 单张
    open_image_viewer(root, ["a.png","b.png"], 1)  # 多张，从索引 1 开始，可左右切换
Esc 关闭，多图时 ←/→ 或底部按钮切换。
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path

from . import theme as T


class ImageViewer(tk.Toplevel):
    def __init__(self, master, paths: list[str], index: int = 0):
        super().__init__(master)
        self.paths = [p for p in paths if p]
        self.index = max(0, min(index, len(self.paths) - 1)) if self.paths else 0
        self._photo = None

        self.title("查看图片")
        self.configure(bg=T.COLOR_PANEL)
        self.transient(master)
        self.geometry("920x660")
        self.minsize(520, 400)

        self._build()
        self._show()

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Left>", lambda e: self._prev())
        self.bind("<Right>", lambda e: self._next())

    def _build(self) -> None:
        # 顶部信息 + 关闭
        top = tk.Frame(self, bg=T.COLOR_PANEL)
        top.pack(fill="x", padx=14, pady=(12, 4))
        self.info_lbl = tk.Label(top, text="", bg=T.COLOR_PANEL, fg=T.COLOR_TEXT_DIM, font=T.FONT_SMALL)
        self.info_lbl.pack(side="left")
        tk.Label(top, text="Esc 关闭", bg=T.COLOR_PANEL, fg=T.COLOR_TEXT_DIM,
                 font=T.FONT_SMALL).pack(side="right")

        # 图片区
        self.canvas = tk.Canvas(self, bg=T.COLOR_PANEL, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=10, pady=6)
        self.canvas.bind("<Configure>", lambda e: self._show())
        self.canvas.bind("<Button-1>", lambda e: self._next() if len(self.paths) > 1 else None)

        # 底部切换按钮（仅多图时显示）
        self.nav = tk.Frame(self, bg=T.COLOR_PANEL)
        self.prev_btn = tk.Label(self.nav, text="← 上一张", bg=T.COLOR_BUTTON_SOFT, fg=T.COLOR_TEXT,
                                 font=T.FONT_BASE, padx=16, pady=6, cursor="hand2",
                                 highlightthickness=1, highlightbackground=T.COLOR_INPUT_BORDER)
        self.next_btn = tk.Label(self.nav, text="下一张 →", bg=T.COLOR_BUTTON_SOFT, fg=T.COLOR_TEXT,
                                 font=T.FONT_BASE, padx=16, pady=6, cursor="hand2",
                                 highlightthickness=1, highlightbackground=T.COLOR_INPUT_BORDER)
        self.prev_btn.pack(side="left", padx=8)
        self.next_btn.pack(side="right", padx=8)
        self.prev_btn.bind("<Button-1>", lambda e: self._prev())
        self.next_btn.bind("<Button-1>", lambda e: self._next())
        self.counter_lbl = tk.Label(self.nav, text="", bg=T.COLOR_PANEL, fg=T.COLOR_TEXT, font=T.FONT_BASE)

    def _show(self) -> None:
        self.canvas.delete("all")
        if not self.paths:
            return
        path = self.paths[self.index]
        try:
            from PIL import Image, ImageTk
            cw = max(self.canvas.winfo_width(), 100)
            ch = max(self.canvas.winfo_height(), 100)
            im = Image.open(path)
            im.thumbnail((cw - 20, ch - 20), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(im)
            self.canvas.create_image(cw // 2, ch // 2, image=self._photo)
            name = Path(path).name
            self.canvas.create_text(cw // 2, ch - 8, text=name, fill=T.COLOR_TEXT_DIM,
                                    font=T.FONT_SMALL)
        except Exception as e:  # noqa: BLE001
            self.canvas.create_text(self.canvas.winfo_width() // 2, 40,
                                    text=f"无法加载: {e}", fill="#ef4444", font=T.FONT_BASE)

        n = len(self.paths)
        self.info_lbl.configure(text=f"{n} 张图片" if n > 1 else "1 张图片")
        if n > 1:
            self.counter_lbl.configure(text=f"{self.index + 1} / {n}")
            self.counter_lbl.pack(side="left", expand=True)
            if not self.nav.winfo_manager():
                self.nav.pack(fill="x", padx=14, pady=(0, 12))
        else:
            self.nav.pack_forget()

    def _prev(self) -> None:
        if len(self.paths) > 1:
            self.index = (self.index - 1) % len(self.paths)
            self._show()

    def _next(self) -> None:
        if len(self.paths) > 1:
            self.index = (self.index + 1) % len(self.paths)
            self._show()


def open_image_viewer(master, path, index: int = 0) -> ImageViewer | None:
    """兼容单张（str）与多张（list）两种调用。"""
    if isinstance(path, (list, tuple)):
        paths = list(path)
    else:
        paths = [path] if path else []
    if not paths:
        return None
    v = ImageViewer(master, paths, index)
    return v
