"""图片服务：导入、压缩、剪贴板粘贴、去重、删除、缩略图。

图片以 uuid 文件名存入 data/images/，数据库仅保存相对路径。
"""
from __future__ import annotations

import hashlib
import io
import os
import uuid
from pathlib import Path

from PIL import Image, ImageGrab

from .. import config
from ..logging_setup import get_logger

log = get_logger("aim.image")


class ImageServiceError(Exception):
    pass


class ImageService:
    def __init__(self):
        config.ensure_dirs()
        # MD5 -> 相对路径，用于导入去重（进程内缓存）
        self._hash_cache: dict[str, str] = {}
        self._rebuild_hash_cache()

    # ---- 去重缓存 ----
    def _rebuild_hash_cache(self) -> None:
        self._hash_cache.clear()
        for p in config.IMAGES_DIR.glob("*"):
            if p.is_file() and p.suffix.lower() in config.ALLOWED_IMAGE_EXTS:
                try:
                    self._hash_cache[self._file_md5(p)] = config.relpath(p)
                except OSError:
                    continue

    @staticmethod
    def _file_md5(path: Path) -> str:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _bytes_md5(data: bytes) -> str:
        return hashlib.md5(data).hexdigest()

    # ---- 校验 ----
    @staticmethod
    def _validate_ext(ext: str) -> str:
        ext = ext.lower()
        if ext not in config.ALLOWED_IMAGE_EXTS:
            raise ImageServiceError(
                f"不支持的图片格式 {ext}，仅支持: {', '.join(sorted(config.ALLOWED_IMAGE_EXTS))}"
            )
        return ext

    # ---- 导入：从文件路径 ----
    def import_from_file(self, src_path: str | os.PathLike) -> str:
        """从磁盘文件导入，返回入库用的相对路径。"""
        src = Path(src_path)
        if not src.exists():
            raise ImageServiceError(f"图片不存在: {src}")
        ext = self._validate_ext(src.suffix)
        data = src.read_bytes()
        return self._import_bytes(data, ext)

    # ---- 导入：从剪贴板 ----
    def import_from_clipboard(self) -> str | None:
        """尝试从剪贴板抓取图像，成功返回相对路径，无图像返回 None。"""
        img = ImageGrab.grabclipboard()
        if img is None:
            return None
        if not isinstance(img, Image.Image):
            # 剪贴板可能是文件列表
            if isinstance(img, (list, tuple)) and img:
                return self.import_from_file(img[0])
            return None
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        return self._import_bytes(buf.getvalue(), ".png")

    # ---- 剪贴板→临时文件（不入库）----
    def clipboard_to_temp(self) -> str | None:
        """从剪贴板取图保存到系统临时目录，返回临时文件路径。

        与 import_from_clipboard 不同：不写入图库，用于多图编辑时暂存，
        由后续 import_from_file 正式导入。无图返回 None。
        """
        import tempfile

        img = ImageGrab.grabclipboard()
        if img is None:
            return None
        if isinstance(img, (list, tuple)) and img:
            # 剪贴板是文件列表：直接返回首个存在的文件路径
            for p in img:
                if Path(str(p)).exists():
                    return str(p)
            return None
        if not isinstance(img, Image.Image):
            return None
        fd, tmp = tempfile.mkstemp(suffix=".png", prefix="aim_paste_")
        os.close(fd)
        img.convert("RGB").save(tmp, format="PNG")
        return tmp

    # ---- 核心：字节落盘 ----
    def _import_bytes(self, data: bytes, ext: str) -> str:
        if len(data) > config.MAX_IMAGE_BYTES:
            data, ext = self._compress(data, ext)

        md5 = self._bytes_md5(data)
        if md5 in self._hash_cache:
            cached_rel = self._hash_cache[md5]
            cached_abs = config.abspath(cached_rel)
            if cached_abs and cached_abs.exists():
                log.info("图片去重命中: %s", cached_rel)
                return cached_rel
            # 缓存指向的文件已不存在（例如之前被删除），失效并重新落盘
            log.warning("去重缓存失效（文件缺失），重新导入: %s", cached_rel)
            del self._hash_cache[md5]

        name = f"{uuid.uuid4().hex}{ext}"
        dest = config.IMAGES_DIR / name
        dest.write_bytes(data)
        rel = config.relpath(dest)
        self._hash_cache[md5] = rel
        log.info("图片已导入: %s (%d bytes)", rel, len(data))
        return rel

    # ---- 压缩 ----
    def _compress(self, data: bytes, ext: str) -> tuple[bytes, str]:
        """超限图片：长边缩至上限，png 保留 png，其余转 jpeg。返回 (字节, 新扩展名)。"""
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception as e:
            raise ImageServiceError(f"无法解析图片: {e}")

        # 等比缩放
        w, h = img.size
        max_edge = config.IMAGE_MAX_EDGE
        if max(w, h) > max_edge:
            scale = max_edge / float(max(w, h))
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

        out_ext = ext
        buf = io.BytesIO()
        if ext == ".png":
            img.save(buf, format="PNG", optimize=True)
        else:
            img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=config.IMAGE_JPEG_QUALITY, optimize=True)
            out_ext = ".jpg"
        result = buf.getvalue()
        log.info("图片压缩: %d -> %d bytes", len(data), len(result))
        return result, out_ext

    # ---- 缩略图 ----
    def thumbnail_path(self, rel_path: str, size: int = 160) -> Path | None:
        """生成/获取缩略图绝对路径。原图缺失返回 None。"""
        src = config.abspath(rel_path)
        if not src or not src.exists():
            return None
        thumb_dir = config.THUMBS_DIR / str(size)
        thumb_dir.mkdir(parents=True, exist_ok=True)
        thumb = thumb_dir / f"{Path(src).stem}_{size}.jpg"
        if thumb.exists() and thumb.stat().st_mtime >= src.stat().st_mtime:
            return thumb
        try:
            img = Image.open(src)
            img = img.convert("RGB")
            img.thumbnail((size, size), Image.LANCZOS)
            img.save(thumb, format="JPEG", quality=82)
            return thumb
        except Exception as e:
            log.warning("缩略图生成失败 %s: %s", rel_path, e)
            return None

    # ---- 删除 ----
    def delete_image(self, rel_path: str | None) -> None:
        """删除单个图片文件（若仍被引用则由调用方保证不误删）。"""
        if not rel_path:
            return
        p = config.abspath(rel_path)
        if p and p.exists():
            try:
                p.unlink()
                # 同步清理缩略图
                for sub in config.THUMBS_DIR.glob("*"):
                    t = sub / f"{p.stem}_{sub.name}.jpg"
                    if t.exists():
                        t.unlink()
                log.info("图片已删除: %s", rel_path)
            except OSError as e:
                log.warning("删除图片失败 %s: %s", rel_path, e)
        # 无论文件是否存在，都从去重缓存中移除该路径，避免后续导入命中幽灵文件
        self._hash_cache = {k: v for k, v in self._hash_cache.items() if v != rel_path}

    def delete_many(self, rel_paths) -> None:
        for rp in rel_paths:
            self.delete_image(rp)

    def cleanup_orphans(self, referenced: set[str]) -> int:
        """删除 images/ 中未被引用的文件，返回清理数量。"""
        count = 0
        for p in config.IMAGES_DIR.glob("*"):
            if not p.is_file():
                continue
            rel = config.relpath(p)
            if rel not in referenced:
                try:
                    p.unlink()
                    count += 1
                except OSError:
                    continue
        # 清理缩略图缓存目录
        if config.THUMBS_DIR.exists():
            for sub in config.THUMBS_DIR.glob("*"):
                if sub.is_dir():
                    for t in sub.glob("*.jpg"):
                        # 缩略图无引用即删（下次访问会重建）
                        try:
                            t.unlink()
                        except OSError:
                            pass
        log.info("孤儿图片清理完成，删除 %d 个", count)
        return count

