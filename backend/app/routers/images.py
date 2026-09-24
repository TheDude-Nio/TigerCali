from __future__ import annotations

import zipfile
from collections import defaultdict
from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from .. import labels, storage
from ..config import settings
from ..db import get_db, iso, utcnow
from ..deps import get_current_user, is_manager, load_image, load_task, load_task_manager, member_can_view
from ..models import Image, Task, User

router = APIRouter(prefix="/api", tags=["images"])

CHUNK = 500
PROCESS_BATCH = 32
CACHE_HEADERS = {"Cache-Control": "private, max-age=31536000, immutable"}


class AnnIn(BaseModel):
    cls: int
    pts: list[list[float]]


class SaveIn(BaseModel):
    annotations: list[AnnIn] = Field(max_length=labels.MAX_ANNOTATIONS_PER_IMAGE)
    version: int
    # 标注员确认完成这张图（“保存并下一张”）
    done: bool = False


class FlagIn(BaseModel):
    flagged: bool
    note: str = Field("", max_length=500)


class IdsIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100000)


def image_out(img: Image) -> dict[str, Any]:
    return {
        "id": img.id,
        "task_id": img.task_id,
        "filename": img.filename,
        "width": img.width,
        "height": img.height,
        "status": img.status,
        "annotations": img.annotations or [],
        "ann_count": img.ann_count,
        "flagged": img.flagged,
        "review_note": img.review_note,
        "version": img.version,
        "assignee_id": img.assignee_id,
        "updated_at": iso(img.updated_at),
        "updated_by": img.updated_by,
    }


# ---------------------------------------------------------------- 上传


def _iter_uploads(files: list[UploadFile], label_texts: dict[str, str], skipped: list[str]) -> Iterator[tuple[str, bytes]]:
    max_bytes = settings.max_image_mb * 1024 * 1024
    for f in files:
        name = storage.clean_filename(f.filename or "image")
        suffix = PurePosixPath(name).suffix.lower()
        if suffix == ".zip":
            try:
                zf = zipfile.ZipFile(f.file)
            except zipfile.BadZipFile:
                skipped.append(f"{name}: 不是有效的 zip 文件")
                continue
            with zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    inner = storage.clean_filename(info.filename)
                    base = PurePosixPath(inner).name
                    if inner.startswith("__MACOSX/") or base.startswith("."):
                        continue
                    if storage.is_image_name(inner):
                        if info.file_size > max_bytes:
                            skipped.append(f"{inner}: 超过 {settings.max_image_mb}MB")
                            continue
                        yield inner, zf.read(info)
                    elif inner.lower().endswith(".txt") and base.lower() != "classes.txt":
                        label_texts[inner] = zf.read(info).decode("utf-8", "ignore")
        elif storage.is_image_name(name):
            yield name, f.file.read()
        elif suffix == ".txt":
            label_texts[name] = f.file.read().decode("utf-8", "ignore")
        else:
            skipped.append(f"{name}: 不支持的文件类型")


@router.post("/tasks/{task_id}/images")
def upload_images(
    task_id: int,
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    task, _ = load_task_manager(db, task_id, user)
    existing = set(db.scalars(select(Image.sha1).where(Image.task_id == task_id)))
    label_texts: dict[str, str] = {}
    errors: list[str] = []
    added = duplicates = 0

    def flush(batch: list[tuple[str, bytes]]) -> None:
        nonlocal added, duplicates
        futures = []
        for name, data in batch:
            futures.append(storage.executor.submit(storage.process_image, task_id, name, data))
        rows = []
        for fut in futures:
            try:
                s = fut.result()
            except storage.ImageRejected as e:
                errors.append(str(e))
                continue
            if s.sha1 in existing:
                duplicates += 1
                continue
            existing.add(s.sha1)
            rows.append(
                {
                    "task_id": task_id,
                    "filename": s.filename,
                    "sort_key": storage.natural_key(s.filename),
                    "sha1": s.sha1,
                    "ext": s.ext,
                    "width": s.width,
                    "height": s.height,
                    "size": s.size,
                    "annotations": [],
                }
            )
        if rows:
            db.execute(insert(Image), rows)
            db.commit()
            added += len(rows)

    batch: list[tuple[str, bytes]] = []
    for item in _iter_uploads(files, label_texts, errors):
        batch.append(item)
        if len(batch) >= PROCESS_BATCH:
            flush(batch)
            batch = []
    if batch:
        flush(batch)

    label_result = None
    if label_texts:
        label_result = import_label_texts(db, task, label_texts, "auto", labels.DEFAULT_POINT_ORDER, False)
    return {"added": added, "duplicates": duplicates, "errors": errors[:50], "error_count": len(errors), "labels": label_result}


def _strip_ext(path: str) -> str:
    p = PurePosixPath(path.lower())
    return str(p.with_suffix(""))


def import_label_texts(
    db: Session, task: Task, texts: dict[str, str], fmt: str, order: str, overwrite: bool
) -> dict[str, int]:
    rows = db.execute(
        select(Image.id, Image.filename, Image.width, Image.height, Image.ann_count).where(Image.task_id == task.id)
    ).all()
    by_stem: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        by_stem[PurePosixPath(r.filename.lower()).stem].append(r)

    matched = unmatched = kept = bad_lines = 0
    updates = []
    for path, text in texts.items():
        cands = by_stem.get(PurePosixPath(path.lower()).stem, [])
        if len(cands) > 1:
            # 同名文件在不同文件夹：优先匹配 labels/xxx ↔ images/xxx 结构，其次匹配父目录名
            key = _strip_ext(path).replace("labels/", "images/")
            exact = [c for c in cands if _strip_ext(c.filename).endswith(key) or key.endswith(_strip_ext(c.filename))]
            if len(exact) != 1:
                parent = PurePosixPath(path.lower()).parent.name
                exact = [c for c in cands if PurePosixPath(c.filename.lower()).parent.name == parent]
            cands = exact
        if len(cands) != 1:
            unmatched += 1
            continue
        r = cands[0]
        if r.ann_count > 0 and not overwrite:
            kept += 1
            continue
        anns, bad = labels.parse_label_text(text, r.width, r.height, task.classes, fmt, order)
        bad_lines += bad
        updates.append({"id": r.id, "annotations": anns, "ann_count": len(anns)})
        matched += 1
    for i in range(0, len(updates), CHUNK):
        part = updates[i : i + CHUNK]
        db.execute(update(Image), part)
        db.execute(update(Image).where(Image.id.in_([u["id"] for u in part])).values(version=Image.version + 1))
    db.commit()
    return {"matched": matched, "unmatched": unmatched, "kept": kept, "bad_lines": bad_lines}


@router.post("/tasks/{task_id}/labels")
def import_labels(
    task_id: int,
    files: list[UploadFile] = File(...),
    fmt: str = Form("auto"),
    point_order: str = Form(labels.DEFAULT_POINT_ORDER),
    overwrite: bool = Form(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    task, _ = load_task_manager(db, task_id, user)
    if fmt not in ("auto", "rm4", "sjtu", "yolo_pose"):
        raise HTTPException(400, "不支持的标签格式")
    if point_order not in labels.POINT_ORDERS:
        raise HTTPException(400, "未知的点序")
    texts: dict[str, str] = {}
    skipped: list[str] = []
    for _ in _iter_uploads(files, texts, skipped):
        pass  # 只关心 txt，图片忽略
    return import_label_texts(db, task, texts, fmt, point_order, overwrite)


# ---------------------------------------------------------------- 列表与详情


def _assignee_filter(assignee: str | None, user: User, manager: bool) -> Any:
    if assignee in (None, "", "me"):
        if not manager or assignee == "me":
            return Image.assignee_id == user.id
        return None
    if not manager:
        raise HTTPException(403, "只能查看分配给自己的图片")
    if assignee == "all":
        return None
    if assignee == "none":
        return Image.assignee_id.is_(None)
    try:
        return Image.assignee_id == int(assignee)
    except ValueError as e:
        raise HTTPException(400, "assignee 参数错误") from e


@router.get("/tasks/{task_id}/image-list")
def image_list(
    task_id: int,
    assignee: str = "me",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """标注界面用的完整紧凑列表（不含标注内容）。"""
    _, member = load_task(db, task_id, user)
    cond = _assignee_filter(assignee, user, is_manager(member))
    stmt = select(Image.id, Image.filename, Image.status, Image.ann_count, Image.flagged).where(Image.task_id == task_id)
    if cond is not None:
        stmt = stmt.where(cond)
    rows = db.execute(stmt.order_by(Image.sort_key, Image.id)).all()
    return JSONResponse(
        {"items": [{"id": i, "filename": f, "status": s, "ann_count": n, "flagged": fl} for i, f, s, n, fl in rows]}
    )


@router.get("/tasks/{task_id}/images")
def list_images(
    task_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=500),
    assignee: str | None = None,
    status: Literal["todo", "done", "rework"] | None = None,
    flagged: bool | None = None,
    has_ann: bool | None = None,
    q: str = "",
    order: Literal["name", "random", "recent"] = "name",
    seed: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """分页列表（含标注，用于缩略图网格与审核）。"""
    _, member = load_task(db, task_id, user)
    conds = [Image.task_id == task_id]
    cond = _assignee_filter(assignee, user, is_manager(member))
    if cond is not None:
        conds.append(cond)
    if status:
        conds.append(Image.status == status)
    if flagged is not None:
        conds.append(Image.flagged.is_(flagged))
    if has_ann is not None:
        conds.append(Image.ann_count > 0 if has_ann else Image.ann_count == 0)
    if q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conds.append(Image.filename.ilike(f"%{escaped}%", escape="\\"))
    total = db.scalar(select(func.count()).select_from(Image).where(*conds)) or 0
    stmt = select(Image).where(*conds)
    if order == "random":
        # 确定性的伪随机顺序，翻页稳定
        stmt = stmt.order_by((Image.id * 2654435761 + seed * 97 + 12345) % 4294967291)
    elif order == "recent":
        stmt = stmt.order_by(Image.updated_at.desc().nulls_last(), Image.id.desc())
    else:
        stmt = stmt.order_by(Image.sort_key, Image.id)
    items = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return JSONResponse({"total": total, "page": page, "page_size": page_size, "items": [image_out(i) for i in items]})


@router.get("/tasks/{task_id}/images/batch")
def batch_details(
    task_id: int,
    ids: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    load_task(db, task_id, user)
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()][:100]
    except ValueError as e:
        raise HTTPException(400, "ids 参数错误") from e
    items = db.scalars(select(Image).where(Image.task_id == task_id, Image.id.in_(id_list))).all()
    return JSONResponse({"items": [image_out(i) for i in items]})


@router.get("/images/{image_id}")
def get_image(image_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JSONResponse:
    img, _, _ = load_image(db, image_id, user)
    return JSONResponse(image_out(img))


@router.put("/images/{image_id}/annotations")
def save_annotations(
    image_id: int, body: SaveIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    img, task, member = load_image(db, image_id, user)
    manager = is_manager(member)
    is_assignee = img.assignee_id == user.id
    if not manager:
        if not is_assignee:
            raise HTTPException(403, "这张图片没有分配给你")
        # 状态类的拒绝用 403，409 专门留给版本冲突，前端据此决定是否重新加载
        if task.status != "active":
            raise HTTPException(403, "任务已结束，不能再修改")
        if member.status == "submitted":
            raise HTTPException(403, "你已提交审核，如需修改请先撤回提交")
        if member.status == "approved":
            raise HTTPException(403, "已审核通过，不能再修改")
    try:
        anns = labels.clean_annotations(
            [a.model_dump() for a in body.annotations], len(task.classes), img.width, img.height
        )
    except labels.LabelError as e:
        raise HTTPException(400, str(e)) from e
    now = utcnow()
    values: dict[str, Any] = {
        "annotations": anns,
        "ann_count": len(anns),
        "version": img.version + 1,
        "updated_at": now,
        "updated_by": user.id,
    }
    status = img.status
    if is_assignee and body.done and img.status != "done":
        status = "done"
        values["status"] = "done"
        values["done_at"] = now
    # 乐观锁：版本号不一致说明别处（另一个标签页 / 管理员）改过
    res = db.execute(update(Image).where(Image.id == image_id, Image.version == body.version).values(**values))
    if res.rowcount == 0:
        db.rollback()
        raise HTTPException(409, "这张图片已在别处被修改，已为你加载最新版本")
    db.commit()
    return {"version": values["version"], "status": status, "ann_count": len(anns)}


@router.post("/images/{image_id}/done")
def mark_done(image_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """不改标注，只确认完成（比如确认这张图里没有装甲板）。"""
    img, task, member = load_image(db, image_id, user)
    if img.assignee_id != user.id:
        raise HTTPException(403, "这张图片没有分配给你")
    if task.status != "active" or member.status in ("submitted", "approved"):
        raise HTTPException(403, "当前状态不能修改")
    if img.status != "done":
        img.status = "done"
        img.done_at = utcnow()
        db.commit()
    return {"version": img.version, "status": img.status, "ann_count": img.ann_count}


@router.post("/images/{image_id}/flag")
def flag_image(
    image_id: int, body: FlagIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    img, _, member = load_image(db, image_id, user)
    if not is_manager(member):
        raise HTTPException(403, "需要该任务的管理员权限")
    img.flagged = body.flagged
    img.review_note = body.note.strip() if body.flagged else ""
    db.commit()
    return {"flagged": img.flagged, "review_note": img.review_note}


@router.post("/tasks/{task_id}/images/delete")
def delete_images(
    task_id: int, body: IdsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    load_task_manager(db, task_id, user)
    removed = []
    for i in range(0, len(body.ids), CHUNK):
        part = body.ids[i : i + CHUNK]
        rows = db.execute(
            select(Image.id, Image.sha1, Image.ext).where(Image.task_id == task_id, Image.id.in_(part))
        ).all()
        if rows:
            db.execute(delete(Image).where(Image.id.in_([r[0] for r in rows])))
            removed.extend(rows)
    db.commit()
    for _, sha1, ext in removed:
        storage.delete_image_files(task_id, sha1, ext)
    return {"deleted": len(removed)}


# ---------------------------------------------------------------- 文件


def _file_row(db: Session, image_id: int, user: User) -> tuple[int, str, str]:
    row = db.execute(select(Image.task_id, Image.sha1, Image.ext).where(Image.id == image_id)).first()
    if row is None or not member_can_view(db, row[0], user.id):
        raise HTTPException(404, "图片不存在")
    return row[0], row[1], row[2]


@router.get("/images/{image_id}/file")
def image_file(image_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    task_id, sha1, ext = _file_row(db, image_id, user)
    db.close()
    return FileResponse(
        storage.image_path(task_id, sha1, ext), media_type=storage.MEDIA_TYPES.get(ext), headers=CACHE_HEADERS
    )


@router.get("/images/{image_id}/thumb")
def image_thumb(image_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    task_id, sha1, ext = _file_row(db, image_id, user)
    db.close()
    path = storage.ensure_thumb(task_id, sha1, ext)
    if path is None:
        return FileResponse(
            storage.image_path(task_id, sha1, ext), media_type=storage.MEDIA_TYPES.get(ext), headers=CACHE_HEADERS
        )
    return FileResponse(path, media_type="image/jpeg", headers=CACHE_HEADERS)
