"""应用上下文：集中装配数据库与各服务，供 UI 层统一取用。"""
from __future__ import annotations

from .db.database import Database
from .logging_setup import get_logger, setup_logging
from .services.backup_service import BackupService
from .services.image_service import ImageService
from .services.map_service import MapService
from .services.search_service import SearchService

log = get_logger("aim.context")


class AppContext:
    def __init__(self):
        setup_logging()
        self.db = Database()
        self.db.init_schema()
        self.images = ImageService()
        self.maps = MapService(self.db, self.images)
        self.search = SearchService(self.db)
        self.backup = BackupService(self.db, self.images)

    def startup_tasks(self) -> dict:
        """启动自检 + 自动备份，返回摘要供 UI 提示。"""
        info = {"integrity_ok": True, "backup": None}
        info["integrity_ok"] = self.db.integrity_check()
        try:
            bp = self.backup.auto_backup_if_needed()
            info["backup"] = str(bp) if bp else None
        except Exception as e:  # noqa: BLE001
            log.warning("自动备份异常: %s", e)
        return info

    def close(self) -> None:
        self.db.close()
