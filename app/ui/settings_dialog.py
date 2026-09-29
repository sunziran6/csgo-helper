"""设置对话框：数据目录信息、孤儿图片清理、数据库自检、手动备份。"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import config
from . import theme as T


def open_settings(master, ctx) -> None:
    dlg = tk.Toplevel(master)
    dlg.title("设置")
    dlg.configure(bg=T.COLOR_PANEL)
    dlg.transient(master)
    dlg.grab_set()
    dlg.resizable(False, False)

    wrap = ttk.Frame(dlg, style="Panel.TFrame")
    wrap.pack(fill="both", expand=True, padx=20, pady=18)

    ttk.Label(wrap, text="数据目录", style="Panel.TLabel",
              font=T.FONT_BOLD).pack(anchor="w")
    path_lbl = tk.Label(wrap, text=str(config.DATA_DIR), bg=T.COLOR_CARD, fg=T.COLOR_TEXT_DIM,
                        font=T.FONT_SMALL, anchor="w", padx=8, pady=6, wraplength=420, justify="left")
    path_lbl.pack(fill="x", pady=(4, 6))

    ttk.Button(wrap, text="打开数据目录", command=lambda: _open_dir(config.DATA_DIR)).pack(anchor="w", pady=(0, 12))

    ttk.Separator(wrap).pack(fill="x", pady=8)

    # 统计
    s = ctx.maps.stats()
    ttk.Label(wrap, text=f"当前数据：{s['maps']} 张地图 / {s['categories']} 个分类 / {s['spots']} 个瞄点",
              style="PanelDim.TLabel").pack(anchor="w", pady=(8, 8))

    ttk.Button(wrap, text="清理无用图片（孤儿文件）",
               command=lambda: _cleanup(ctx, dlg)).pack(anchor="w", pady=4)
    ttk.Button(wrap, text="数据库完整性自检",
               command=lambda: _integrity(ctx, dlg)).pack(anchor="w", pady=4)
    ttk.Button(wrap, text="立即备份数据库到 backups/",
               command=lambda: _manual_backup(ctx, dlg)).pack(anchor="w", pady=4)

    ttk.Separator(wrap).pack(fill="x", pady=10)
    ttk.Label(wrap, text=f"版本 {config.APP_VERSION}", style="PanelDim.TLabel").pack(anchor="w")

    ttk.Button(wrap, text="关闭", command=dlg.destroy).pack(anchor="e", pady=(12, 0))


def _open_dir(path) -> None:
    import os
    import subprocess
    import sys
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as ex:  # noqa: BLE001
        messagebox.showerror("打开失败", str(ex))


def _cleanup(ctx, parent) -> None:
    if not messagebox.askyesno("确认", "将删除未被任何瞄点引用的图片文件，是否继续？", parent=parent):
        return
    n = ctx.maps.cleanup_orphan_images()
    messagebox.showinfo("完成", f"已清理 {n} 个无用图片文件。", parent=parent)


def _integrity(ctx, parent) -> None:
    ok = ctx.db.integrity_check()
    if ok:
        messagebox.showinfo("自检通过", "数据库完整性正常。", parent=parent)
    else:
        messagebox.showerror("自检失败", "数据库可能已损坏，请从 data/backups/ 恢复。", parent=parent)


def _manual_backup(ctx, parent) -> None:
    path = filedialog.asksaveasfilename(
        title="另存数据库备份", defaultextension=".db",
        initialfile="data_manual.db", filetypes=[("SQLite 数据库", "*.db")])
    if not path:
        return
    import shutil
    try:
        shutil.copy2(config.DB_PATH, path)
        messagebox.showinfo("完成", f"已备份到：\n{path}", parent=parent)
    except Exception as ex:  # noqa: BLE001
        messagebox.showerror("备份失败", str(ex), parent=parent)
