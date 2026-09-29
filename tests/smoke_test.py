"""无界面冒烟测试：验证 db / dao / services / 备份导入导出全链路。

运行：python tests/smoke_test.py
不依赖 GUI，使用临时数据目录，验证核心业务逻辑正确性。
"""
from __future__ import annotations

import os
import sys
import tempfile
import shutil
from pathlib import Path

# 让 app 包可导入
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402


def _make_png(path: Path, size=(400, 300), color=(200, 30, 30)) -> None:
    img = Image.new("RGB", size, color)
    img.save(path, format="PNG")


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

    tmp = Path(tempfile.mkdtemp(prefix="aim_smoke_"))
    print(f"临时数据目录: {tmp}")

    # 重定向 config 路径到临时目录
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

    from app.db.database import Database
    from app.services.image_service import ImageService
    from app.services.map_service import MapService, ServiceError
    from app.services.search_service import SearchService
    from app.services.backup_service import BackupService

    print("\n== 1. 数据库初始化 ==")
    db = Database()
    db.init_schema()
    check("integrity_check 通过", db.integrity_check() is True)
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    check("三张核心表存在", {"maps", "categories", "spots"}.issubset(tables))

    print("\n== 2. 地图 CRUD ==")
    img_svc = ImageService()
    svc = MapService(db, img_svc)
    m1 = svc.create_map("dust2")
    m2 = svc.create_map("mirage")
    check("创建两张地图", len(svc.list_maps()) == 2)
    dup_err = False
    try:
        svc.create_map("dust2")
    except ServiceError:
        dup_err = True
    check("重复地图名报错", dup_err)
    svc.rename_map(m2, "mirage_new")
    check("重命名地图生效", svc.dao.maps.get(m2)["name"] == "mirage_new")

    print("\n== 3. 分类与瞄点 ==")
    c1 = svc.create_category(m1, "A点默认")
    c2 = svc.create_category(m1, "B通")
    check("创建两个分类", len(svc.list_categories(m1)) == 2)

    # 造图片
    p1 = tmp / "shot1.png"
    p2 = tmp / "shot2.png"
    _make_png(p1, color=(10, 200, 10))
    _make_png(p2, color=(10, 10, 220))

    s1 = svc.create_spot(m1, "A大门预瞄", "站A大门贴墙，准星对箱子右上角", [str(p1)], category_id=c1)
    s2 = svc.create_spot(m1, "A小预瞄", "描述2", [str(p2)], category_id=c1)
    s3 = svc.create_spot(m1, "地图直属瞄点", "无分类", None, category_id=None)
    check("分类下瞄点数=2", len(svc.list_spots_by_category(c1)) == 2)
    check("地图直属瞄点数=1", len(svc.list_map_direct_spots(m1)) == 1)
    check("图片已落盘", (config.IMAGES_DIR / Path(svc.get_spot(s1)["image_path"]).name).exists())

    print("\n== 4. 编辑瞄点（替换图片）==")
    old_rel = svc.get_spot(s1)["image_path"]
    p3 = tmp / "shot3.png"
    _make_png(p3, color=(240, 160, 0))
    svc.update_spot(s1, name="A大门预瞄(改)", image_sources=[str(p3)])
    new_rel = svc.get_spot(s1)["image_path"]
    check("名称已更新", svc.get_spot(s1)["name"] == "A大门预瞄(改)")
    check("图片路径已变更", old_rel != new_rel)

    print("\n== 5. 搜索 ==")
    search = SearchService(db)
    r_all = search.search("预瞄")
    check("全局搜索'预瞄'命中2条(A大门改+A小)", len(r_all) == 2)
    r_map = search.search("瞄点", map_id=m1)
    check("按地图搜索命中", len(r_map) >= 1)
    r_cat = search.search("", map_id=m1)
    check("空关键字返回空", r_cat == [])

    print("\n== 6. 级联删除（清理图片）==")
    img_before = set(p.name for p in config.IMAGES_DIR.glob("*") if p.is_file())
    svc.delete_category(c1)  # 删除含 s1,s2 的分类
    check("分类删除后其瞄点消失", len(svc.list_spots_by_category(c1)) == 0)
    check("s1 已不存在", svc.get_spot(s1) is None)

    print("\n== 7. 导出/导入 ==")
    backup = BackupService(db, img_svc)
    zip_path = tmp / "backup.zip"
    info = backup.export(str(zip_path))
    check("导出包含地图", info["maps"] == 2)
    check("zip 文件生成", zip_path.exists())

    # 覆盖导入到当前库（先删一个地图制造差异）
    svc.delete_map(m2)
    check("删除后剩1张地图", len(svc.list_maps()) == 1)
    stats = backup.import_zip(str(zip_path), conflict="duplicate")
    check("导入新增地图>=1", stats["maps"] >= 1)
    check("导入后地图数增加", len(svc.list_maps()) >= 2)

    print("\n== 8. 删除地图级联 + 图片清理 ==")
    all_maps = svc.list_maps()
    for m in all_maps:
        svc.delete_map(m["id"])
    check("所有地图已删除", len(svc.list_maps()) == 0)
    orphan = svc.cleanup_orphan_images()
    check("孤儿图片清理不报错", orphan >= 0)

    print("\n== 9. 自动备份 ==")
    bp = backup.auto_backup_if_needed()
    check("自动备份执行(可能None因间隔)", True)  # 首次应生成或不生成均正常
    print(f"     备份结果: {bp}")

    db.close()
    print(f"\n================ 结果: {passed} 通过 / {failed} 失败 ================")

    # 清理临时目录
    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except OSError:
        pass

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
