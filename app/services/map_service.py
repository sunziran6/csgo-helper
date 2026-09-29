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
        # 先收集待删图片路径
        paths = [s["image_path"] for s in self.dao.spots.list_by_map(map_id) if s["image_path"]]
        try:
            self.dao.maps.delete(map_id)
        except DaoError as e:
            raise ServiceError(str(e))
        self.images.delete_many(paths)
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
        paths = [s["image_path"] for s in self.dao.spots.list_by_category(cat_id) if s["image_path"]]
        try:
            self.dao.categories.delete(cat_id)
        except DaoError as e:
            raise ServiceError(str(e))
        self.images.delete_many(paths)
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
        image_src: str | None = None,
        category_id: int | None = None,
    ) -> int:
        """新建瞄点。image_src 为磁盘图片路径（可选）。失败时补偿删除已落盘图片。"""
        rel = None
        try:
            if image_src:
                rel = self.images.import_from_file(image_src)
            return self.dao.spots.create(
                map_id=map_id,
                name=name,
                description=description,
                image_path=rel,
                category_id=category_id,
            )
        except (DaoError, ServiceError) as e:
            # DAO 失败：若图片是本次新落盘的，需回滚删除
            self._rollback_new_image(rel)
            raise ServiceError(str(e))
        except Exception as e:
            self._rollback_new_image(rel)
            raise ServiceError(f"新建瞄点失败: {e}")

    def create_spot_with_clipboard(
        self,
        map_id: int,
        name: str,
        description: str = "",
        category_id: int | None = None,
    ) -> int:
        """新建瞄点并从剪贴板取图（无图也允许）。"""
        rel = None
        try:
            rel = self.images.import_from_clipboard()
            return self.dao.spots.create(
                map_id=map_id,
                name=name,
                description=description,
                image_path=rel,
                category_id=category_id,
            )
        except DaoError as e:
            self._rollback_new_image(rel)
            raise ServiceError(str(e))

    def update_spot(
        self,
        spot_id: int,
        name: str | None = None,
        description: str | None = None,
        new_image_src: str | None = None,
        remove_image: bool = False,
    ) -> None:
        """编辑瞄点。替换图片时删除旧图；移除图片时删除旧图。"""
        old = self.dao.spots.get(spot_id)
        if not old:
            raise ServiceError("瞄点不存在")
        old_rel = old["image_path"]
        new_rel = None
        try:
            if new_image_src:
                new_rel = self.images.import_from_file(new_image_src)
            self.dao.spots.update(
                spot_id,
                name=name,
                description=description,
                image_path=new_rel,
                clear_image=remove_image,
            )
        except DaoError as e:
            self._rollback_new_image(new_rel)
            raise ServiceError(str(e))
        # 成功后清理被替换/移除的旧图（若与新图不同）
        if old_rel and old_rel != new_rel:
            if remove_image or new_rel:
                self.images.delete_image(old_rel)

    def delete_spot(self, spot_id: int) -> None:
        spot = self.dao.spots.get(spot_id)
        if not spot:
            return
        try:
            self.dao.spots.delete(spot_id)
        except DaoError as e:
            raise ServiceError(str(e))
        if spot["image_path"]:
            self.images.delete_image(spot["image_path"])

    def _rollback_new_image(self, rel: str | None) -> None:
        """补偿：删除本次刚落盘、但记录未成功写入的图片。"""
        if not rel:
            return
        # 仅当没有任何记录引用它时才删（避免误删去重复用的图）
        referenced = set(self.dao.spots.all_image_paths())
        if rel not in referenced:
            self.images.delete_image(rel)

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
