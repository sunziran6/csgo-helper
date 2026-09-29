"""全局日志配置：写入 data/app.log，单文件 1MB 轮转。"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from . import config

_configured = False


def setup_logging() -> logging.Logger:
    """初始化并返回应用根 logger（幂等）。"""
    global _configured
    logger = logging.getLogger("aim")
    if _configured:
        return logger

    config.ensure_dirs()
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    fh = RotatingFileHandler(
        config.LOG_PATH, maxBytes=1 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    _configured = True
    return logger


def get_logger(name: str = "aim") -> logging.Logger:
    return logging.getLogger(name)
