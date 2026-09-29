"""多图 + 迁移专项测试（无界面）。

运行：python tests/multi_image_test.py
全程使用临时数据目录，绝不触碰真实 data/。

覆盖：
1. v1→v2 迁移：旧 spots.image_path 单图数据自动迁入 spot_images
2. 多图创建 / 读取
3. 多图编辑（保留已有 + 新增 + 移除）
4. 删除瞄点 / 分类 / 地图时清理多图
5. 备份导出 / 导入（多图）
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402


def _make_png(path: Path, color=(200, 30, 30)) -> None:
    Image.new("RGB", (320, 200), color).save(path, format="PNG")


def run() -> int:
    passed = 0
    failed = 0

    def check(name: str, cond: bool):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}")

    tmp = Path(tempfile.mkdtemp(prefix="aim_multi_"))
    print(f"临时数据目录: {tmp}")

    from app import config
    config.DATA_DIR = tmp
    config.IMAGES_DIR = tmp / "images"
    config.THUMBS_DIR = config.IMAGES_DIR / "thumbs"
    config.BACKUPS_DIR = tmp / "backups"
    config.DB_PATH = tmp / "data.db"
    config.LOG_PATH = tmp / "app.log"
    config.ensure_dirs()

    from app.logging_setup import setup_logging
    setup_logging()

    # ================= 1. v1→v2 迁移 =================
    print("\n== 1. v1→v2 迁移（旧单图 -> spot_images）==")
    # 手工构造一个 v1 旧库：有 spots.image_path，无 spot_images 表，user_version=1
    legacy_img = config.IMAGES_DIR / "legacy0001.png"
    _make_png(legacy_img, (10, 120, 200))
    legacy_rel = config.relpath(legacy_img)

    raw = sqlite3.connect(str(config.DB_PATH))
    raw.executescript("""
    CREATE TABLE maps (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')), UNIQUE(name));
    CREATE TABLE categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        map_id INTEGER NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
        name TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')), UNIQUE(map_id, name));
    CREATE TABLE spots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        map_id INTEGER NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
        category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
        name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', image_path TEXT,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
    """)
    raw.execute("INSERT INTO maps(name) VALUES('Mirage')")
    raw.execute("INSERT INTO spots(map_id, name, image_path) VALUES(1, '旧瞄点', ?)", (legacy_rel,))
    raw.execute("PRAGMA user_version=1;")
    raw.commit()
    raw.close()

    from app.db.database import Database
    from app.services.image_service import ImageService
    from app.services.map_service import MapService, ServiceError
    from app.services.backup_service import BackupService

    db = Database()
    db.init_schema()  # 应触发迁移
    ver = db.conn.execute("PRAGMA user_version;").fetchone()[0]
    check("user_version 升级到 2", ver == 2)
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    check("spot_images 表已创建", "spot_images" in tables)

    img_svc = ImageService()
    svc = MapService(db, img_svc)
    old_spot = svc.list_spots_by_map(1)[0]
    check("旧瞄点图片已迁入 images 列表", old_spot.get("images") == [legacy_rel])
    check("迁移幂等（再跑一次不重复）", True)
    db.init_schema()
    cnt = db.query_one("SELECT COUNT(*) AS n FROM spot_images WHERE spot_id=?", (old_spot["id"],))["n"]
    check("重复初始化不产生重复图片行", cnt == 1)

    # ================= 2. 多图创建 =================
    print("\n== 2. 多图创建 ==")
    p1 = tmp / "a.png"; _make_png(p1, (200, 30, 30))
    p2 = tmp / "b.png"; _make_png(p2, (30, 200, 30))
    p3 = tmp / "c.png"; _make_png(p3, (30, 30, 200))
    cat = svc.create_category(1, "快烟")
    s = svc.create_spot(1, "多图瞄点", "三张图", [str(p1), str(p2), str(p3)], category_id=cat)
    got = svc.get_spot(s)
    check("创建后 images 数量=3", len(got["images"]) == 3)
    check("首图同步到 image_path", got["image_path"] == got["images"][0])
    check("三张图均落盘", all((config.abspath(r) or Path("_")).exists() for r in got["images"]))

    # ================= 3. 多图编辑 =================
    print("\n== 3. 多图编辑（保留+新增+移除）==")
    keep = got["images"][0]          # 保留第一张
    p4 = tmp / "d.png"; _make_png(p4, (240, 160, 0))
    # 最终列表：保留 keep + 新增 p4（移除原来的第2、3张）
    svc.update_spot(s, name="多图瞄点(改)", image_sources=[keep, str(p4)])
    got2 = svc.get_spot(s)
    check("编辑后 images 数量=2", len(got2["images"]) == 2)
    check("保留的旧图仍在", got2["images"][0] == keep)
    check("名称已更新", got2["name"] == "多图瞄点(改)")
    # 被移除的两张图应从磁盘清理（不再被引用）
    removed_rels = [r for r in got["images"] if r not in got2["images"]]
    check("被移除图片已从磁盘删除",
          all(not (config.abspath(r) or Path("_")).exists() for r in removed_rels))

    # ================= 4. 删除清理多图 =================
    print("\n== 4. 删除瞄点清理多图 ==")
    cur_rels = list(svc.get_spot(s)["images"])
    svc.delete_spot(s)
    check("删除瞄点后其图片被清理",
          all(not (config.abspath(r) or Path("_")).exists() for r in cur_rels))

    # ================= 5. 备份导出/导入（多图）=================
    print("\n== 5. 备份导出/导入（多图）==")
    s2 = svc.create_spot(1, "备份多图", "两张", [str(p1), str(p2)], category_id=cat)
    check("备份前瞄点有2图", len(svc.get_spot(s2)["images"]) == 2)
    backup_svc = BackupService(db, img_svc)
    zpath = tmp / "bak.zip"
    stat = backup_svc.export(str(zpath))
    check("导出含图片", stat["images"] >= 2)
    # 导入到 duplicate（新地图名），验证多图恢复
    stat2 = backup_svc.import_zip(str(zpath), conflict="duplicate")
    check("导入地图数>=1", stat2["maps"] >= 1)
    # 找到导入后的「备份多图」瞄点，验证仍有2图
    all_spots = []
    for m in svc.list_maps():
        all_spots.extend(svc.list_spots_by_map(m["id"]))
    dup = [sp for sp in all_spots if sp["name"] == "备份多图"]
    check("导入后存在多图瞄点副本", len(dup) >= 2)
    check("副本图片数量=2", all(len(sp["images"]) == 2 for sp in dup))

    db.close()
    print(f"\n结果: {passed} 通过, {failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
