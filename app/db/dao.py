"""数据访问对象：封装地图/分类/瞄点的 SQL 操作。

所有写操作通过 Database.transaction() 保证事务性。返回值为 dict 或 dict 列表，
便于 UI/Service 层直接消费。
"""
from __future__ import annotations

import sqlite3

from .database import Database
from ..logging_setup import get_logger

log = get_logger("aim.dao")


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


class DaoError(Exception):
    """数据访问层业务异常。"""


class MapDao:
    def __init__(self, db: Database):
        self.db = db

    def list_all(self) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM maps ORDER BY sort_order, name COLLATE NOCASE"
        )
        return [dict(r) for r in rows]

    def get(self, map_id: int) -> dict | None:
        return _row_to_dict(self.db.query_one("SELECT * FROM maps WHERE id=?", (map_id,)))

    def get_by_name(self, name: str) -> dict | None:
        return _row_to_dict(
            self.db.query_one("SELECT * FROM maps WHERE name=?", (name,))
        )

    def create(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise DaoError("地图名称不能为空")
        if self.get_by_name(name):
            raise DaoError(f"地图「{name}」已存在")
        next_order = self._next_order("maps")
        return self.db.execute(
            "INSERT INTO maps(name, sort_order) VALUES(?, ?)", (name, next_order)
        )

    def rename(self, map_id: int, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            raise DaoError("地图名称不能为空")
        dup = self.db.query_one(
            "SELECT id FROM maps WHERE name=? AND id<>?", (new_name, map_id)
        )
        if dup:
            raise DaoError(f"地图「{new_name}」已存在")
        self.db.execute(
            "UPDATE maps SET name=?, updated_at=datetime('now','localtime') WHERE id=?",
            (new_name, map_id),
        )

    def delete(self, map_id: int) -> None:
        # 外键级联会删除 categories 与 spots；图片文件由 service 层清理
        self.db.execute("DELETE FROM maps WHERE id=?", (map_id,))

    def _next_order(self, table: str) -> int:
        row = self.db.query_one(f"SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM {table}")
        return int(row["n"]) if row else 0


class CategoryDao:
    def __init__(self, db: Database):
        self.db = db

    def list_by_map(self, map_id: int) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM categories WHERE map_id=? ORDER BY sort_order, name COLLATE NOCASE",
            (map_id,),
        )
        return [dict(r) for r in rows]

    def get(self, cat_id: int) -> dict | None:
        return _row_to_dict(
            self.db.query_one("SELECT * FROM categories WHERE id=?", (cat_id,))
        )

    def get_by_name(self, map_id: int, name: str) -> dict | None:
        return _row_to_dict(
            self.db.query_one(
                "SELECT * FROM categories WHERE map_id=? AND name=?", (map_id, name)
            )
        )

    def create(self, map_id: int, name: str) -> int:
        name = name.strip()
        if not name:
            raise DaoError("分类名称不能为空")
        if self.get_by_name(map_id, name):
            raise DaoError(f"该地图下分类「{name}」已存在")
        next_order = self._next_order(map_id)
        return self.db.execute(
            "INSERT INTO categories(map_id, name, sort_order) VALUES(?, ?, ?)",
            (map_id, name, next_order),
        )

    def rename(self, cat_id: int, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            raise DaoError("分类名称不能为空")
        cat = self.get(cat_id)
        if not cat:
            raise DaoError("分类不存在")
        dup = self.db.query_one(
            "SELECT id FROM categories WHERE map_id=? AND name=? AND id<>?",
            (cat["map_id"], new_name, cat_id),
        )
        if dup:
            raise DaoError(f"该地图下分类「{new_name}」已存在")
        self.db.execute(
            "UPDATE categories SET name=?, updated_at=datetime('now','localtime') WHERE id=?",
            (new_name, cat_id),
        )

    def delete(self, cat_id: int) -> None:
        self.db.execute("DELETE FROM categories WHERE id=?", (cat_id,))

    def _next_order(self, map_id: int) -> int:
        row = self.db.query_one(
            "SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM categories WHERE map_id=?",
            (map_id,),
        )
        return int(row["n"]) if row else 0


class SpotDao:
    def __init__(self, db: Database):
        self.db = db

    def list_by_map(self, map_id: int) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM spots WHERE map_id=? ORDER BY sort_order, name COLLATE NOCASE",
            (map_id,),
        )
        return [dict(r) for r in rows]

    def list_by_category(self, cat_id: int) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM spots WHERE category_id=? ORDER BY sort_order, name COLLATE NOCASE",
            (cat_id,),
        )
        return [dict(r) for r in rows]

    def list_map_direct(self, map_id: int) -> list[dict]:
        """地图直属瞄点（category_id IS NULL）。"""
        rows = self.db.query(
            "SELECT * FROM spots WHERE map_id=? AND category_id IS NULL "
            "ORDER BY sort_order, name COLLATE NOCASE",
            (map_id,),
        )
        return [dict(r) for r in rows]

    def get(self, spot_id: int) -> dict | None:
        return _row_to_dict(self.db.query_one("SELECT * FROM spots WHERE id=?", (spot_id,)))

    def create(
        self,
        map_id: int,
        name: str,
        description: str = "",
        image_path: str | None = None,
        category_id: int | None = None,
    ) -> int:
        name = name.strip()
        if not name:
            raise DaoError("瞄点名称不能为空")
        # 校验归属：分类必须属于同一地图
        if category_id is not None:
            cat = self.db.query_one(
                "SELECT map_id FROM categories WHERE id=?", (category_id,)
            )
            if not cat:
                raise DaoError("所属分类不存在")
            if cat["map_id"] != map_id:
                raise DaoError("分类与地图不匹配")
        next_order = self._next_order(map_id)
        return self.db.execute(
            "INSERT INTO spots(map_id, category_id, name, description, image_path, sort_order) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (map_id, category_id, name, description or "", image_path, next_order),
        )

    def update(
        self,
        spot_id: int,
        name: str | None = None,
        description: str | None = None,
        image_path: str | None = None,
        clear_image: bool = False,
        category_id: int | None = ...,  # 省略号表示不修改
    ) -> None:
        spot = self.get(spot_id)
        if not spot:
            raise DaoError("瞄点不存在")
        fields = []
        params: list = []
        if name is not None:
            name = name.strip()
            if not name:
                raise DaoError("瞄点名称不能为空")
            fields.append("name=?")
            params.append(name)
        if description is not None:
            fields.append("description=?")
            params.append(description)
        if clear_image:
            fields.append("image_path=NULL")
        elif image_path is not None:
            fields.append("image_path=?")
            params.append(image_path)
        if category_id is not ...:
            fields.append("category_id=?")
            params.append(category_id)
        if not fields:
            return
        fields.append("updated_at=datetime('now','localtime')")
        params.append(spot_id)
        self.db.execute(
            f"UPDATE spots SET {', '.join(fields)} WHERE id=?", tuple(params)
        )

    def delete(self, spot_id: int) -> None:
        self.db.execute("DELETE FROM spots WHERE id=?", (spot_id,))

    def all_image_paths(self) -> list[str]:
        rows = self.db.query("SELECT image_path FROM spots WHERE image_path IS NOT NULL")
        return [r["image_path"] for r in rows]

    def _next_order(self, map_id: int) -> int:
        row = self.db.query_one(
            "SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM spots WHERE map_id=?",
            (map_id,),
        )
        return int(row["n"]) if row else 0


class Dao:
    """聚合入口，方便上层一次性拿到三个 DAO。"""

    def __init__(self, db: Database):
        self.db = db
        self.maps = MapDao(db)
        self.categories = CategoryDao(db)
        self.spots = SpotDao(db)
