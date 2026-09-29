"""应用级配置与路径管理。

所有用户数据集中在程序目录下的 data/ 文件夹内，整体拷贝即可迁移/备份。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "CS:GO 瞄点记录"
APP_VERSION = "0.1.0"

# 数据库结构版本号（user_version），字段扩展时递增并写迁移逻辑
DB_SCHEMA_VERSION = 1

# 图片导入约束
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 单张图片上限 10MB
IMAGE_MAX_EDGE = 1920               # 超过此长边则等比缩放
IMAGE_JPEG_QUALITY = 85
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# 自动备份策略
AUTO_BACKUP_INTERVAL_DAYS = 7
AUTO_BACKUP_KEEP = 5


def _frozen_base_dir() -> Path:
    """返回程序根目录，兼容 PyInstaller 打包（sys.frozen）与源码运行。"""
    if getattr(sys, "frozen", False):
        # 打包后：exe 同级目录
        return Path(sys.executable).resolve().parent
    # 源码运行：项目根（本文件位于 app/ 下）
    return Path(__file__).resolve().parent.parent


BASE_DIR = _frozen_base_dir()
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
THUMBS_DIR = IMAGES_DIR / "thumbs"
BACKUPS_DIR = DATA_DIR / "backups"
DB_PATH = DATA_DIR / "data.db"
LOG_PATH = DATA_DIR / "app.log"


def ensure_dirs() -> None:
    """确保数据目录结构存在。"""
    for d in (DATA_DIR, IMAGES_DIR, THUMBS_DIR, BACKUPS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def abspath(rel: str | os.PathLike | None) -> Path | None:
    """把数据库中存储的相对路径转换为绝对路径。None 安全。"""
    if rel is None or str(rel).strip() == "":
        return None
    return (DATA_DIR / str(rel)).resolve()


def relpath(abs_path: str | os.PathLike) -> str:
    """把绝对路径转换为相对 DATA_DIR 的 POSIX 风格相对路径，用于入库。"""
    p = Path(abs_path).resolve()
    try:
        rel = p.relative_to(DATA_DIR.resolve())
    except ValueError:
        # 不在数据目录内，退化为文件名放 images/
        rel = Path("images") / p.name
    return rel.as_posix()
