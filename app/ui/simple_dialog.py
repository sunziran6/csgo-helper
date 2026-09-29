"""通用文本输入对话框（重命名等场景）。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as T


def ask_text(master, title: str, prompt: str, initial: str = "") -> str | None:
    """弹出一个单行输入框，返回用户输入（去空格）或 None（取消/空）。"""
    dlg = tk.Toplevel(master)
    dlg.title(title)
    dlg.configure(bg=T.COLOR_PANEL)
    dlg.transient(master)
    dlg.grab_set()
    dlg.resizable(False, False)

    ttk.Label(dlg, text=prompt, style="Panel.TLabel").pack(anchor="w", padx=18, pady=(16, 4))
    var = tk.StringVar(value=initial)
    entry = ttk.Entry(dlg, textvariable=var, width=34)
    entry.pack(fill="x", padx=18)
    entry.focus_set()
    entry.select_range(0, "end")

    result = {"v": None}

    def ok(_e=None):
        v = var.get().strip()
        result["v"] = v or None
        dlg.destroy()

    def cancel(_e=None):
        result["v"] = None
        dlg.destroy()

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.pack(fill="x", padx=18, pady=16)
    ttk.Button(btns, text="取消", command=cancel).pack(side="right", padx=(8, 0))
    ttk.Button(btns, text="确定", style="Accent.TButton", command=ok).pack(side="right")

    entry.bind("<Return>", ok)
    entry.bind("<Escape>", cancel)
    dlg.protocol("WM_DELETE_WINDOW", cancel)

    dlg.update_idletasks()
    try:
        x = master.winfo_rootx() + (master.winfo_width() - dlg.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
    except Exception:
        pass

    master.wait_window(dlg)
    return result["v"]
