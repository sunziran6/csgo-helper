"""备份服务：导出/导入 zip 备份包，启动自动备份。

备份包结构：
    aim_backup_YYYYmmdd_HHMMSS.zip
    ├── meta.json     版本号、导出时间、程序版本
    ├── data.json     maps/categories/spots 全字段（含相对图片路径）
    └── images/...    图片文件
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from .. import config
from ..db.database import Database
from ..logging_setup import get_logger
from .image_service import ImageService

log = get_logger("aim.backup")

BACKUP_FORMAT_VERSION = 2


class BackupError(Exception):
    pass


class BackupService:
    def __init__(self, db: Database, image_service: ImageService | None = None):
        self.db = db
        self.images = image_service or ImageService()

    # ================= 导出 =================
    def export(self, dest_zip: str, map_id: int | None = None) -> dict:
        """导出全部或指定地图为 zip。返回统计信息。"""
        dest = Path(dest_zip)
        if map_id is not None:
            maps = [dict(r) for r in self.db.query("SELECT * FROM maps WHERE id=?", (map_id,))]
        else:
            maps = [dict(r) for r in self.db.query("SELECT * FROM maps ORDER BY sort_order, name")]

        map_ids = [m["id"] for m in maps]
        categories: list[dict] = []
        spots: list[dict] = []
        spot_images: list[dict] = []
        if map_ids:
            qmarks = ",".join("?" * len(map_ids))
            categories = [dict(r) for r in self.db.query(
                f"SELECT * FROM categories WHERE map_id IN ({qmarks})", tuple(map_ids))]
            spots = [dict(r) for r in self.db.query(
                f"SELECT * FROM spots WHERE map_id IN ({qmarks})", tuple(map_ids))]
            spot_ids = [s["id"] for s in spots]
            if spot_ids:
                sq = ",".join("?" * len(spot_ids))
                spot_images = [dict(r) for r in self.db.query(
                    f"SELECT * FROM spot_images WHERE spot_id IN ({sq}) ORDER BY spot_id, sort_order, id",
                    tuple(spot_ids))]

        data = {"maps": maps, "categories": categories,
                "spots": spots, "spot_images": spot_images}
        meta = {
            "format_version": BACKUP_FORMAT_VERSION,
            "app_version": config.APP_VERSION,
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 收集图片（来自 spot_images）
        image_rels = sorted({si["image_path"] for si in spot_images if si["image_path"]})

        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
            zf.writestr("data.json", json.dumps(data, ensure_ascii=False, indent=2))
            for rel in image_rels:
                src = config.abspath(rel)
                if src and src.exists():
                    # zip 内统一用 images/<文件名>
                    zf.write(src, arcname=f"images/{Path(rel).name}")

        log.info("导出完成: %s (地图%d/分类%d/瞄点%d/图片%d)",
                 dest, len(maps), len(categories), len(spots), len(image_rels))
        return {
            "maps": len(maps), "categories": len(categories),
            "spots": len(spots), "images": len(image_rels), "path": str(dest),
        }

    # ================= 导入 =================
    def import_zip(self, src_zip: str, conflict: str = "skip") -> dict:
        """从 zip 恢复。conflict: skip | overwrite | duplicate（按地图名冲突策略）。"""
        src = Path(src_zip)
        if not src.exists():
            raise BackupError("备份文件不存在")
        if conflict not in ("skip", "overwrite", "duplicate"):
            raise BackupError("未知冲突策略")

        with zipfile.ZipFile(src, "r") as zf:
            names = set(zf.namelist())
            if "data.json" not in names:
                raise BackupError("备份包格式不正确（缺少 data.json）")
            meta = {}
            if "meta.json" in names:
                meta = json.loads(zf.read("meta.json").decode("utf-8"))
                fv = meta.get("format_version", 1)
                if fv > BACKUP_FORMAT_VERSION:
                    raise BackupError(f"备份包版本({fv})高于当前程序支持({BACKUP_FORMAT_VERSION})")
            data = json.loads(zf.read("data.json").decode("utf-8"))

            maps = data.get("maps", [])
            categories = data.get("categories", [])
            spots = data.get("spots", [])
            spot_images_data = data.get("spot_images", [])

            # 旧 spot_id -> 按顺序的图片相对路径列表（新格式）
            spot_img_map: dict[int, list[str]] = {}
            for si in sorted(spot_images_data, key=lambda x: (x.get("sort_order", 0), x.get("id", 0))):
                spot_img_map.setdefault(si["spot_id"], []).append(si["image_path"])

            stats = {"maps": 0, "categories": 0, "spots": 0, "skipped_maps": 0}

            for m in maps:
                existing = self.db.query_one("SELECT id FROM maps WHERE name=?", (m["name"],))
                if existing:
                    if conflict == "skip":
                        stats["skipped_maps"] += 1
                        continue
                    if conflict == "overwrite":
                        # 删除旧地图（级联），再作为新地图导入
                        old_paths = [r["image_path"] for r in self.db.query(
                            "SELECT si.image_path FROM spot_images si "
                            "JOIN spots s ON si.spot_id=s.id WHERE s.map_id=?",
                            (existing["id"],))]
                        self.db.execute("DELETE FROM maps WHERE id=?", (existing["id"],))
                        referenced = {r["image_path"] for r in self.db.query(
                            "SELECT image_path FROM spot_images")}
                        self.images.delete_many([p for p in old_paths if p not in referenced])
                    # duplicate：不改名，导入时地图名追加后缀
                target_name = m["name"]
                if conflict == "duplicate" and existing:
                    target_name = f"{m['name']}(导入)"
                    # 若仍重名，追加序号
                    base = target_name
                    i = 2
                    while self.db.query_one("SELECT id FROM maps WHERE name=?", (target_name,)):
                        target_name = f"{base}{i}"
                        i += 1

                new_map_id = self.db.execute(
                    "INSERT INTO maps(name, sort_order) VALUES(?, ?)",
                    (target_name, m.get("sort_order", 0)),
                )
                stats["maps"] += 1

                # 旧分类id -> 新分类id
                cat_id_map: dict[int, int] = {}
                for c in [c for c in categories if c["map_id"] == m["id"]]:
                    new_cat_id = self.db.execute(
                        "INSERT INTO categories(map_id, name, sort_order) VALUES(?, ?, ?)",
                        (new_map_id, c["name"], c.get("sort_order", 0)),
                    )
                    cat_id_map[c["id"]] = new_cat_id
                    stats["categories"] += 1

                for s in [s for s in spots if s["map_id"] == m["id"]]:
                    # 确定该瞄点的图片源列表：新格式用 spot_images，旧 v1 备份回退到 image_path
                    src_rels = spot_img_map.get(s["id"])
                    if src_rels is None:
                        src_rels = [s["image_path"]] if s.get("image_path") else []
                    new_rels: list[str] = []
                    for rel in src_rels:
                        nr = self._import_image_from_zip(zf, rel)
                        if nr:
                            new_rels.append(nr)
                    first = new_rels[0] if new_rels else None
                    new_cat = cat_id_map.get(s["category_id"]) if s.get("category_id") else None
                    new_spot_id = self.db.execute(
                        "INSERT INTO spots(map_id, category_id, name, description, image_path, sort_order) "
                        "VALUES(?, ?, ?, ?, ?, ?)",
                        (new_map_id, new_cat, s["name"], s.get("description", ""),
                         first, s.get("sort_order", 0)),
                    )
                    for idx, nr in enumerate(new_rels):
                        self.db.execute(
                            "INSERT INTO spot_images(spot_id, image_path, sort_order) VALUES(?, ?, ?)",
                            (new_spot_id, nr, idx),
                        )
                    stats["spots"] += 1

        log.info("导入完成: %s", stats)
        return stats

    def _import_image_from_zip(self, zf: zipfile.ZipFile, rel_path: str | None) -> str | None:
        """把 zip 内图片解出并以新 uuid 落盘，返回新相对路径。"""
        if not rel_path:
            return None
        arc = f"images/{Path(rel_path).name}"
        if arc not in zf.namelist():
            return None
        data = zf.read(arc)
        ext = Path(rel_path).suffix.lower()
        if ext not in config.ALLOWED_IMAGE_EXTS:
            ext = ".png"
        dest = config.IMAGES_DIR / f"{uuid.uuid4().hex}{ext}"
        dest.write_bytes(data)
        return config.relpath(dest)

    # ================= 自动备份 =================
    def auto_backup_if_needed(self) -> Path | None:
        """启动时若距上次备份超过阈值天数，则复制 db 到 backups/，保留最近 N 份。"""
        db_path = config.DB_PATH
        if not db_path.exists():
            return None
        latest = self._latest_backup()
        if latest:
            age_days = (time.time() - latest.stat().st_mtime) / 86400.0
            if age_days < config.AUTO_BACKUP_INTERVAL_DAYS:
                return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = config.BACKUPS_DIR / f"data_{stamp}.db"
        try:
            shutil.copy2(db_path, dest)
        except OSError as e:
            log.warning("自动备份失败: %s", e)
            return None
        self._prune_backups()
        log.info("已自动备份数据库: %s", dest.name)
        return dest

    def _latest_backup(self) -> Path | None:
        if not config.BACKUPS_DIR.exists():
            return None
        backups = sorted(config.BACKUPS_DIR.glob("data_*.db"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        return backups[0] if backups else None

    def _prune_backups(self) -> None:
        backups = sorted(config.BACKUPS_DIR.glob("data_*.db"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[config.AUTO_BACKUP_KEEP:]:
            try:
                old.unlink()
            except OSError:
                continue
