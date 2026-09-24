"""导出 YOLO 数据集：边打包边下载（流式 zip），大数据集也不占内存。"""
from __future__ import annotations

import io
import json
import random
import re
import zipfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import labels, storage
from ..db import get_db
from ..deps import get_current_user, load_task_manager
from ..models import Image, Task, TaskMember, User

router = APIRouter(prefix="/api", tags=["export"])

_SAFE = re.compile(r"[^\w.\-]+")


class _ZipSink(io.RawIOBase):
    """zipfile 写入的不可 seek 缓冲区，写完一段就交给 StreamingResponse。"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def writable(self) -> bool:
        return True

    def write(self, b: Any) -> int:  # type: ignore[override]
        self._buf += b
        return len(b)

    def take(self) -> bytes:
        out = bytes(self._buf)
        self._buf.clear()
        return out


def _yaml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _data_yaml(task: Task, fmt: str, order: str, has_val: bool) -> str:
    names = "\n".join(f"  {i}: {_yaml_str(c['name'])}" for i, c in enumerate(task.classes))
    lines = [
        f"# 华南虎一起标 导出：{task.name}",
        "# 建议把 path 改成本文件夹的绝对路径",
        "# path: /abs/path/to/this/folder",
        "train: images/train",
        f"val: images/{'val' if has_val else 'train'}",
        "",
    ]
    if fmt == "yolo_pose":
        lines += [
            "# 4 个关键点，每点 (x, y)；点序见 README.txt",
            "kpt_shape: [4, 2]",
            f"flip_idx: {labels.flip_idx(order)}",
            "",
        ]
    lines += [f"nc: {len(task.classes)}", "names:", names, ""]
    return "\n".join(lines)


def _readme(task: Task, fmt: str, order: str, n_train: int, n_val: int, scope: str) -> str:
    f = next(x for x in labels.EXPORT_FORMATS if x["key"] == fmt)
    lines = [
        f"任务：{task.name}",
        f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"导出范围：{ {'approved': '审核通过', 'done': '已完成', 'all': '全部图片'}[scope] }",
        f"格式：{f['name']}",
        f"每行：{f['line']}",
        f"坐标：归一化到 [0, 1]（x 除以图宽，y 除以图高）",
        f"点序：{labels.POINT_ORDERS[order]['name']}",
        f"训练集：{n_train} 张，验证集：{n_val} 张",
        "",
        "类别（class id: 名称）：",
    ]
    for i, c in enumerate(task.classes):
        lines.append(f"  {i}: {c['name']}")
    if fmt == "sjtu":
        lines += ["", "双标签格式颜色编号："]
        lines += [f"  {c['sjtu']}: {c['key']}（{c['name']}）" for c in labels.ARMOR_COLORS]
        lines += ["双标签格式装甲板编号："]
        lines += [f"  {t['sjtu']}: {t['key']}（{t['name']}）" for t in labels.ARMOR_TAGS]
    if fmt == "yolo_pose":
        lines += [
            "",
            "Ultralytics 训练示例：",
            "  yolo pose train data=data.yaml model=yolo11n-pose.pt imgsz=640 fliplr=0.0",
            "  （装甲板数字左右翻转后含义会变，建议关闭水平翻转 fliplr=0.0）",
        ]
    return "\n".join(lines) + "\n"


@router.get("/tasks/{task_id}/export", response_model=None)
def export_dataset(
    task_id: int,
    fmt: str = "yolo_pose",
    scope: Literal["approved", "done", "all"] = "done",
    val_ratio: float = Query(0.1, ge=0, le=0.9),
    include_images: bool = True,
    include_empty: bool = True,
    point_order: str = labels.DEFAULT_POINT_ORDER,
    seed: int = 0,
    preview: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse | JSONResponse:
    task, _ = load_task_manager(db, task_id, user)
    if fmt not in labels.EXPORT_FORMAT_KEYS:
        raise HTTPException(400, "未知的导出格式")
    if point_order not in labels.POINT_ORDERS:
        raise HTTPException(400, "未知的点序")
    if fmt == "sjtu" and task.label_config.get("mode") != "armor":
        raise HTTPException(400, "双标签格式只适用于装甲板类别模式")

    conds = [Image.task_id == task_id]
    if scope == "approved":
        approved = select(TaskMember.user_id).where(TaskMember.task_id == task_id, TaskMember.status == "approved")
        conds.append(Image.assignee_id.in_(approved))
    elif scope == "done":
        conds.append(Image.status == "done")
    if not include_empty:
        conds.append(Image.ann_count > 0)
    rows = db.execute(
        select(Image.id, Image.filename, Image.sha1, Image.ext, Image.width, Image.height, Image.annotations)
        .where(*conds)
        .order_by(Image.sort_key, Image.id)
    ).all()
    if preview:
        n = len(rows)
        n_val_preview = int(round(n * val_ratio)) if n > 1 and fmt != "json" else 0
        return JSONResponse(
            {
                "images": n,
                "annotations": sum(len(r.annotations or []) for r in rows),
                "empty": sum(1 for r in rows if not r.annotations),
                "train": n - n_val_preview,
                "val": n_val_preview,
            }
        )
    if not rows:
        raise HTTPException(404, "没有符合条件的图片可以导出")

    # 输出文件名：原文件名，重名时加上图片 id
    used: set[str] = set()
    items = []
    for r in rows:
        stem = _SAFE.sub("_", PurePosixPath(r.filename).stem)[:120] or "img"
        if stem.lower() in used:
            stem = f"{stem}_{r.id}"
        used.add(stem.lower())
        items.append((r, stem))

    order = list(range(len(items)))
    random.Random(seed).shuffle(order)
    n_val = int(round(len(items) * val_ratio)) if len(items) > 1 else 0
    val_set = set(order[:n_val])
    classes = task.classes
    task_snapshot = Task(name=task.name, classes=classes, label_config=task.label_config)
    db.close()

    def generate() -> Iterator[bytes]:
        sink = _ZipSink()
        with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as zf:

            def text(name: str, content: str) -> None:
                zf.writestr(name, content)

            text("README.txt", _readme(task_snapshot, fmt, point_order, len(items) - n_val, n_val, scope))
            yield sink.take()
            if fmt == "json":
                data = {
                    "task": task_snapshot.name,
                    "classes": [c["name"] for c in classes],
                    "point_order": "左上, 左下, 右下, 右上（像素坐标）",
                    "images": [
                        {
                            "file": f"images/{stem}{r.ext}",
                            "source": r.filename,
                            "width": r.width,
                            "height": r.height,
                            "annotations": [
                                {"cls": a["cls"], "name": classes[a["cls"]]["name"], "pts": a["pts"]}
                                for a in (r.annotations or [])
                            ],
                        }
                        for r, stem in items
                    ],
                }
                text("annotations.json", json.dumps(data, ensure_ascii=False, indent=1))
                yield sink.take()
            else:
                text("data.yaml", _data_yaml(task_snapshot, fmt, point_order, n_val > 0))
                text("classes.txt", "\n".join(c["name"] for c in classes) + "\n")
                yield sink.take()

            for idx, (r, stem) in enumerate(items):
                split = "val" if idx in val_set else "train"
                if fmt != "json":
                    lines = labels.format_label_lines(r.annotations or [], r.width, r.height, fmt, point_order, classes)
                    zf.writestr(f"labels/{split}/{stem}.txt", "\n".join(lines) + ("\n" if lines else ""))
                if include_images:
                    arc = f"images/{stem}{r.ext}" if fmt == "json" else f"images/{split}/{stem}{r.ext}"
                    src = storage.image_path(task_id, r.sha1, r.ext)
                    try:
                        fh = open(src, "rb")
                    except FileNotFoundError:
                        continue
                    info = zipfile.ZipInfo(arc, date_time=datetime.now().timetuple()[:6])
                    info.compress_type = zipfile.ZIP_STORED  # 图片本身已压缩，直接存储最快
                    with fh, zf.open(info, "w", force_zip64=True) as dest:
                        while True:
                            chunk = fh.read(1 << 20)
                            if not chunk:
                                break
                            dest.write(chunk)
                            yield sink.take()
                else:
                    if idx % 200 == 0:
                        yield sink.take()
        yield sink.take()

    filename = f"{task.name}_{fmt}_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    return StreamingResponse(
        generate(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"tigercali_{task_id}_{fmt}.zip\"; filename*=UTF-8''{quote(filename)}"
        },
    )
