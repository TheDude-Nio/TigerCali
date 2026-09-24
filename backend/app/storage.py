"""图片存储：按内容哈希落盘，上传时并行生成缩略图。"""
from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageOps

from .config import settings

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_FORMAT_EXT = {"JPEG": ".jpg", "PNG": ".png", "BMP": ".bmp", "WEBP": ".webp"}
MEDIA_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".bmp": "image/bmp", ".webp": "image/webp"}

# Pillow 解码时会释放 GIL，线程池能明显加快批量上传
executor = ThreadPoolExecutor(max_workers=settings.upload_workers, thread_name_prefix="img")

_DIGITS = re.compile(r"\d+")


def natural_key(name: str) -> str:
    return _DIGITS.sub(lambda m: m.group(0).lstrip("0").zfill(12), name.lower())[:512]


def is_image_name(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_EXTS


def clean_filename(name: str) -> str:
    name = name.replace("\\", "/").lstrip("/")
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)[-255:] or "image"


def image_path(task_id: int, sha1: str, ext: str) -> Path:
    return settings.images_dir / str(task_id) / sha1[:2] / f"{sha1}{ext}"


def thumb_path(task_id: int, sha1: str) -> Path:
    return settings.thumbs_dir / str(task_id) / sha1[:2] / f"{sha1}.jpg"


def attachment_dir(task_id: int) -> Path:
    return settings.attachments_dir / str(task_id)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


@dataclass
class StoredImage:
    filename: str
    sha1: str
    ext: str
    width: int
    height: int
    size: int


class ImageRejected(Exception):
    pass


def _save_thumb(im: PILImage.Image, dest: Path) -> None:
    size = settings.thumb_size
    if im.format == "JPEG":
        im.draft("RGB", (size, size))  # JPEG 直接按 1/2、1/4、1/8 缩放解码，快很多
    thumb = im.copy() if im.mode in ("RGB", "L") else im.convert("RGBA").convert("RGB")
    thumb.thumbnail((size, size), PILImage.Resampling.BILINEAR)
    buf = io.BytesIO()
    thumb.save(buf, "JPEG", quality=80, optimize=False)
    _atomic_write(dest, buf.getvalue())


def process_image(task_id: int, filename: str, data: bytes) -> StoredImage:
    """校验图片、落盘并生成缩略图。在线程池里执行。"""
    if len(data) > settings.max_image_mb * 1024 * 1024:
        raise ImageRejected(f"{filename}: 超过 {settings.max_image_mb}MB")
    sha1 = hashlib.sha1(data).hexdigest()
    try:
        im = PILImage.open(io.BytesIO(data))
        fmt = im.format
        if fmt not in _FORMAT_EXT:
            raise ImageRejected(f"{filename}: 不支持的图片格式 {fmt}")
        ext = _FORMAT_EXT[fmt]
        orientation = im.getexif().get(0x0112, 1) if fmt in ("JPEG", "WEBP") else 1
        if orientation not in (0, 1):
            # 手机照片带 EXIF 旋转：直接转正后保存，保证浏览器和训练时看到的一致
            im = ImageOps.exif_transpose(im)
            buf = io.BytesIO()
            if ext == ".jpg":
                im.convert("RGB").save(buf, "JPEG", quality=95)
            else:
                im.save(buf, fmt)
            data = buf.getvalue()
            im = PILImage.open(io.BytesIO(data))
        width, height = im.size
        dest = image_path(task_id, sha1, ext)
        if not dest.exists():
            _atomic_write(dest, data)
        tdest = thumb_path(task_id, sha1)
        if not tdest.exists():
            try:
                _save_thumb(im, tdest)
            except Exception:  # 缩略图失败不影响主流程，读取时会回退到原图
                pass
    except ImageRejected:
        raise
    except Exception as e:  # noqa: BLE001
        raise ImageRejected(f"{filename}: 无法识别的图片 ({e.__class__.__name__})") from e
    return StoredImage(clean_filename(filename), sha1, ext, width, height, len(data))


def ensure_thumb(task_id: int, sha1: str, ext: str) -> Path | None:
    tdest = thumb_path(task_id, sha1)
    if tdest.exists():
        return tdest
    src = image_path(task_id, sha1, ext)
    try:
        with PILImage.open(src) as im:
            _save_thumb(im, tdest)
        return tdest
    except Exception:  # noqa: BLE001
        return None


def delete_image_files(task_id: int, sha1: str, ext: str) -> None:
    for p in (image_path(task_id, sha1, ext), thumb_path(task_id, sha1)):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def delete_task_files(task_id: int) -> None:
    for base in (settings.images_dir, settings.thumbs_dir, settings.attachments_dir):
        shutil.rmtree(base / str(task_id), ignore_errors=True)


def save_attachment(task_id: int, filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in IMAGE_EXTS:
        raise ImageRejected("只支持图片附件")
    if len(data) > 20 * 1024 * 1024:
        raise ImageRejected("附件不能超过 20MB")
    try:
        with PILImage.open(io.BytesIO(data)) as im:
            ext = _FORMAT_EXT.get(im.format or "", "")
    except Exception as e:  # noqa: BLE001
        raise ImageRejected("无法识别的图片") from e
    if not ext:
        raise ImageRejected("不支持的图片格式")
    name = f"{hashlib.sha1(data).hexdigest()}{ext}"
    dest = attachment_dir(task_id) / name
    if not dest.exists():
        _atomic_write(dest, data)
    return name
