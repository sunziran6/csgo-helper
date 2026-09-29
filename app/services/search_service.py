"""搜索服务：按关键字在瞄点名称/描述中模糊匹配，支持范围筛选。"""
from __future__ import annotations

from ..db.database import Database
from ..logging_setup import get_logger

log = get_logger("aim.search")


class SearchService:
    def __init__(self, db: Database):
        self.db = db

    def search(
        self,
        keyword: str,
        map_id: int | None = None,
        category_id: int | None = None,
    ) -> list[dict]:
        """返回匹配的瞄点列表（含地图名、分类名便于展示）。

        - keyword 为空返回空列表；
        - map_id 限定地图；category_id 限定分类（自动隐含其地图）。
        """
        kw = (keyword or "").strip()
        if not kw:
            return []

        sql = (
            "SELECT s.*, m.name AS map_name, c.name AS category_name "
            "FROM spots s "
            "JOIN maps m ON m.id = s.map_id "
            "LEFT JOIN categories c ON c.id = s.category_id "
            "WHERE (s.name LIKE ? OR s.description LIKE ?)"
        )
        like = f"%{kw}%"
        params: list = [like, like]

        if category_id is not None:
            sql += " AND s.category_id = ?"
            params.append(category_id)
        elif map_id is not None:
            sql += " AND s.map_id = ?"
            params.append(map_id)

        sql += " ORDER BY m.name COLLATE NOCASE, s.name COLLATE NOCASE"
        rows = self.db.query(sql, tuple(params))
        results = [dict(r) for r in rows]
        log.info("搜索 '%s' 命中 %d 条", kw, len(results))
        return results
