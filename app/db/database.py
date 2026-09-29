"""SQLite 连接管理、建表与迁移。

约定：
- 启用 WAL 模式，异常退出后数据不易损坏；
- 开启外键约束，级联删除生效；
- user_version 记录结构版本，为后续字段扩展预留轻量迁移。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from .. import config
from ..logging_setup import get_logger

log = get_logger("aim.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS maps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    map_id     INTEGER NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(map_id, name)
);

CREATE TABLE IF NOT EXISTS spots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    map_id      INTEGER NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    image_path  TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_spots_map      ON spots(map_id);
CREATE INDEX IF NOT EXISTS idx_spots_category ON spots(category_id);
CREATE INDEX IF NOT EXISTS idx_spots_name     ON spots(name);
CREATE INDEX IF NOT EXISTS idx_categories_map ON categories(map_id);
"""


class Database:
    """轻量数据库封装：单连接 + 事务上下文管理器。"""

    def __init__(self, db_path=None):
        config.ensure_dirs()
        self.db_path = str(db_path or config.DB_PATH)
        self._conn: sqlite3.Connection | None = None

    # ---- 连接管理 ----
    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    # ---- 初始化与迁移 ----
    def init_schema(self) -> None:
        with self.transaction() as cur:
            cur.executescript(_SCHEMA)
        # 版本标记
        current = self.conn.execute("PRAGMA user_version;").fetchone()[0]
        if current < config.DB_SCHEMA_VERSION:
            self._migrate(current, config.DB_SCHEMA_VERSION)
            self.conn.execute(f"PRAGMA user_version={config.DB_SCHEMA_VERSION};")
            self.conn.commit()
        log.info("数据库初始化完成: %s (schema v%s)", self.db_path, config.DB_SCHEMA_VERSION)

    def _migrate(self, from_ver: int, to_ver: int) -> None:
        """预留迁移钩子。当前 v1 为首版，无需迁移。"""
        log.info("执行迁移 %s -> %s", from_ver, to_ver)

    def integrity_check(self) -> bool:
        """db 损坏自检。"""
        try:
            row = self.conn.execute("PRAGMA integrity_check;").fetchone()
            ok = bool(row and row[0] == "ok")
            if not ok:
                log.error("数据库完整性检查失败: %s", row[0] if row else "无结果")
            return ok
        except sqlite3.Error as e:
            log.error("完整性检查异常: %s", e)
            return False

    # ---- 事务 ----
    @contextmanager
    def transaction(self):
        """事务上下文：正常退出提交，异常回滚。yield 一个 cursor。"""
        conn = self.conn
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    # ---- 便捷查询 ----
    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        cur = self.conn.execute(sql, params)
        try:
            return cur.fetchall()
        finally:
            cur.close()

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        cur = self.conn.execute(sql, params)
        try:
            return cur.fetchone()
        finally:
            cur.close()

    def execute(self, sql: str, params: tuple = ()) -> int:
        """在事务中执行写操作，返回 lastrowid。"""
        with self.transaction() as cur:
            cur.execute(sql, params)
            return cur.lastrowid
