"""程序入口：初始化上下文、应用主题、启动主窗口。

运行：python main.py
打包：pyinstaller -w -F -n CSGO瞄点记录 main.py
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox


def _add_project_root_to_path() -> None:
    """保证以源码方式运行时可 import app 包。"""
    import os
    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> int:
    _add_project_root_to_path()
    from app.context import AppContext
    from app.logging_setup import get_logger, setup_logging
    from app.ui.main_window import MainWindow
    from app.ui.theme import apply_theme

    setup_logging()
    log = get_logger("aim.main")

    try:
        ctx = AppContext()
    except Exception as e:  # noqa: BLE001
        log.exception("初始化失败")
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("启动失败", f"无法初始化数据：\n{e}")
        return 1

    root = tk.Tk()
    apply_theme(root)

    # 启动自检提示
    info = ctx.startup_tasks()
    if not info.get("integrity_ok", True):
        messagebox.showwarning(
            "数据库自检异常",
            "数据库完整性检查未通过，建议从 data/backups/ 恢复备份。", parent=root)

    win = MainWindow(root, ctx)

    def on_close() -> None:
        try:
            ctx.close()
        finally:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    log.info("应用启动")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
