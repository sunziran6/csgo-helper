"""地图/分类/瞄点业务服务：编排 DAO 与图片服务，处理级联与补偿。"""
from __future__ import annotations

from ..db.dao import Dao, DaoError
from ..db.database import Database
from ..logging_setup import get_logger
from .image_service import ImageService

log = get_logger("aim.service")


class ServiceError(Exception):
    pass


class MapService:
    def __init__(self, db: Database, image_service: ImageService | None = None):
        self.db = db
        self.dao = Dao(db)
        self.images = image_service or ImageService()

    # ================= 地图 =================
    def list_maps(self) -> list[dict]:
        return self.dao.maps.list_all()

    def create_map(self, name: str) -> int:
        try:
            return self.dao.maps.create(name)
        except DaoError as e:
            raise ServiceError(str(e))

    def rename_map(self, map_id: int, new_name: str) -> None:
        try:
            self.dao.maps.rename(map_id, new_name)
        except DaoError as e:
            raise ServiceError(str(e))

    def delete_map(self, map_id: int) -> None:
        """级联删除地图及其分类/瞄点，并清理图片文件。"""
        # 先收集待删图片路径（多图）
        paths: list[str] = []
        for s in self.dao.spots.list_by_map(map_id):
            paths.extend(s.get("images") or [])
        try:
            self.dao.maps.delete(map_id)
        except DaoError as e:
            raise ServiceError(str(e))
        self._delete_unreferenced(paths)
        log.info("地图已删除 id=%s，清理图片 %d 张", map_id, len(paths))

    def count_children(self, map_id: int) -> tuple[int, int]:
        """返回 (分类数, 瞄点数)，用于删除确认提示。"""
        cats = len(self.dao.categories.list_by_map(map_id))
        spots = len(self.dao.spots.list_by_map(map_id))
        return cats, spots

    # ================= 分类 =================
    def list_categories(self, map_id: int) -> list[dict]:
        return self.dao.categories.list_by_map(map_id)

    def create_category(self, map_id: int, name: str) -> int:
        try:
            return self.dao.categories.create(map_id, name)
        except DaoError as e:
            raise ServiceError(str(e))

    def rename_category(self, cat_id: int, new_name: str) -> None:
        try:
            self.dao.categories.rename(cat_id, new_name)
        except DaoError as e:
            raise ServiceError(str(e))

    def delete_category(self, cat_id: int) -> None:
        paths: list[str] = []
        for s in self.dao.spots.list_by_category(cat_id):
            paths.extend(s.get("images") or [])
        try:
            self.dao.categories.delete(cat_id)
        except DaoError as e:
            raise ServiceError(str(e))
        self._delete_unreferenced(paths)
        log.info("分类已删除 id=%s，清理图片 %d 张", cat_id, len(paths))

    def count_category_spots(self, cat_id: int) -> int:
        return len(self.dao.spots.list_by_category(cat_id))

    # ================= 瞄点 =================
    def list_spots_by_map(self, map_id: int) -> list[dict]:
        return self.dao.spots.list_by_map(map_id)

    def list_spots_by_category(self, cat_id: int) -> list[dict]:
        return self.dao.spots.list_by_category(cat_id)

    def list_map_direct_spots(self, map_id: int) -> list[dict]:
        return self.dao.spots.list_map_direct(map_id)

    def get_spot(self, spot_id: int) -> dict | None:
        return self.dao.spots.get(spot_id)

    def create_spot(
        self,
        map_id: int,
        name: str,
        description: str = "",
        image_srcs: list[str] | None = None,
        category_id: int | None = None,
    ) -> int:
        """新建瞄点（支持多图）。image_srcs 为磁盘图片路径列表（可选）。

        失败时补偿删除本次已落盘的图片。
        """
        rels: list[str] = []
        try:
            for src in (image_srcs or []):
                if src:
                    rels.append(self.images.import_from_file(src))
            return self.dao.spots.create(
                map_id=map_id,
                name=name,
                description=description,
                image_paths=rels,
                category_id=category_id,
            )
        except (DaoError, ServiceError) as e:
            self._rollback_new_images(rels)
            raise ServiceError(str(e))
        except Exception as e:
            self._rollback_new_images(rels)
            raise ServiceError(f"新建瞄点失败: {e}")

    def create_spot_with_clipboard(
        self,
        map_id: int,
        name: str,
        description: str = "",
        category_id: int | None = None,
    ) -> int:
        """新建瞄点并从剪贴板取一张图（无图也允许）。"""
        rels: list[str] = []
        try:
            rel = self.images.import_from_clipboard()
            if rel:
                rels.append(rel)
            return self.dao.spots.create(
                map_id=map_id,
                name=name,
                description=description,
                image_paths=rels,
                category_id=category_id,
            )
        except DaoError as e:
            self._rollback_new_images(rels)
            raise ServiceError(str(e))

    def update_spot(
        self,
        spot_id: int,
        name: str | None = None,
        description: str | None = None,
        image_sources: list[str] | None = None,
    ) -> None:
        """编辑瞄点。

        image_sources 为最终的有序图片列表，每项要么是已存在的相对路径
        （保留），要么是新的磁盘文件路径（导入）。传 None 表示不改图片。
        完成后删除不再被任何瞄点引用的旧图。
        """
        old = self.dao.spots.get(spot_id)
        if not old:
            raise ServiceError("瞄点不存在")
        old_images = list(old.get("images") or [])
        imported: list[str] = []
        try:
            if name is not None or description is not None:
                self.dao.spots.update(spot_id, name=name, description=description)
            if image_sources is not None:
                new_rels: list[str] = []
                for src in image_sources:
                    if not src:
                        continue
                    if src in old_images:
                        new_rels.append(src)  # 已有图，保留
                    else:
                        rel = self.images.import_from_file(src)  # 新磁盘文件
                        new_rels.append(rel)
                        imported.append(rel)
                self.dao.spots.set_images(spot_id, new_rels)
        except (DaoError, ServiceError) as e:
            self._rollback_new_images(imported)
            raise ServiceError(str(e))
        except Exception as e:
            self._rollback_new_images(imported)
            raise ServiceError(f"编辑瞄点失败: {e}")
        # 删除被移除且不再被引用的旧图
        if image_sources is not None:
            kept = set(self.dao.spots.list_images(spot_id))
            removed = [p for p in old_images if p not in kept]
            self._delete_unreferenced(removed)

    def delete_spot(self, spot_id: int) -> None:
        spot = self.dao.spots.get(spot_id)
        if not spot:
            return
        paths = list(spot.get("images") or [])
        try:
            self.dao.spots.delete(spot_id)
        except DaoError as e:
            raise ServiceError(str(e))
        self._delete_unreferenced(paths)

    def _rollback_new_image(self, rel: str | None) -> None:
        """补偿：删除本次刚落盘、但记录未成功写入的图片。"""
        if not rel:
            return
        # 仅当没有任何记录引用它时才删（避免误删去重复用的图）
        referenced = set(self.dao.spots.all_image_paths())
        if rel not in referenced:
            self.images.delete_image(rel)

    def _rollback_new_images(self, rels: list[str]) -> None:
        for rel in rels:
            self._rollback_new_image(rel)

    def _delete_unreferenced(self, paths: list[str]) -> None:
        """删除不再被任何瞄点引用的图片（去重共享场景下安全）。"""
        candidates = [p for p in paths if p]
        if not candidates:
            return
        referenced = set(self.dao.spots.all_image_paths())
        to_del = [p for p in candidates if p not in referenced]
        if to_del:
            self.images.delete_many(to_del)

    # ================= 统计 / 维护 =================
    def stats(self) -> dict:
        maps = self.dao.maps.list_all()
        cat_count = 0
        spot_count = 0
        for m in maps:
            cat_count += len(self.dao.categories.list_by_map(m["id"]))
            spot_count += len(self.dao.spots.list_by_map(m["id"]))
        return {"maps": len(maps), "categories": cat_count, "spots": spot_count}

    def cleanup_orphan_images(self) -> int:
        referenced = set(self.dao.spots.all_image_paths())
        return self.images.cleanup_orphans(referenced)
