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

-- 瞄点图片（多图）：一个瞄点可关联多张图片
CREATE TABLE IF NOT EXISTS spot_images (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    spot_id    INTEGER NOT NULL REFERENCES spots(id) ON DELETE CASCADE,
    image_path TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_spot_images_spot ON spot_images(spot_id);
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
        """轻量迁移。按版本递增逐步升级，幂等安全。"""
        log.info("执行迁移 %s -> %s", from_ver, to_ver)
        if from_ver < 2 <= to_ver:
            self._migrate_v1_to_v2()

    def _migrate_v1_to_v2(self) -> None:
        """v1→v2：将旧 spots.image_path 单图数据迁入 spot_images 多图表。

        - spot_images 表已由 init_schema 创建；
        - 仅迁移尚未在 spot_images 中出现的图片，保证幂等；
        - 保留 spots.image_path 列（不删）作为首图快照，向后兼容。
        """
        with self.transaction() as cur:
            rows = cur.execute(
                "SELECT id, image_path FROM spots WHERE image_path IS NOT NULL AND image_path <> ''"
            ).fetchall()
            inserted = 0
            for r in rows:
                exists = cur.execute(
                    "SELECT 1 FROM spot_images WHERE spot_id=? AND image_path=? LIMIT 1",
                    (r["id"], r["image_path"]),
                ).fetchone()
                if not exists:
                    cur.execute(
                        "INSERT INTO spot_images(spot_id, image_path, sort_order) VALUES(?, ?, 0)",
                        (r["id"], r["image_path"]),
                    )
                    inserted += 1
            log.info("v1→v2 迁移：将 %d 个瞄点的图片迁入 spot_images", inserted)

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
