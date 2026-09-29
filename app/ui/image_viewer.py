"""大图查看器：弹出窗口按适配比例展示原图，单击或 Esc 关闭。"""
from __future__ import annotations

import tkinter as tk

from . import theme as T


def open_image_viewer(master, image_path: str) -> None:
    from PIL import Image, ImageTk

    try:
        img = Image.open(image_path)
    except Exception as ex:  # noqa: BLE001
        from tkinter import messagebox
        messagebox.showerror("打开失败", str(ex), parent=master)
        return

    win = tk.Toplevel(master)
    win.configure(bg=T.COLOR_PANEL)
    win.title("查看大图")
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    max_w, max_h = int(sw * 0.9), int(sh * 0.9)

    im = img.copy()
    im.thumbnail((max_w, max_h), Image.LANCZOS)
    photo = ImageTk.PhotoImage(im)

    lbl = tk.Label(win, image=photo, bg=T.COLOR_PANEL, cursor="hand2")
    lbl.pack(padx=14, pady=14)
    win._photo_ref = photo  # 防 GC

    info = tk.Label(win, text=f"{img.size[0]} × {img.size[1]}", bg=T.COLOR_PANEL,
                    fg=T.COLOR_TEXT_DIM, font=T.FONT_SMALL)
    info.pack(pady=(0, 10))

    win.bind("<Button-1>", lambda e: win.destroy())
    win.bind("<Escape>", lambda e: win.destroy())
    win.geometry(f"+{(sw - win.winfo_reqwidth()) // 2}+{(sh - win.winfo_reqheight()) // 2}")
