from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.orm import Session

from .. import labels, storage
from ..db import get_db, iso, utcnow
from ..deps import get_current_user, is_manager, load_task, load_task_manager, member_can_view
from ..models import Image, Task, TaskMember, User

router = APIRouter(prefix="/api", tags=["tasks"])

DEFAULT_SETTINGS = {"auto_sort": True}

_done = func.sum(case((Image.status == "done", 1), else_=0))


class TaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field("", max_length=50000)
    label_config: dict[str, Any]
    settings: dict[str, Any] = {}


class TaskPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=50000)
    label_config: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None
    status: Literal["active", "finished"] | None = None


def _clean_settings(raw: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    out.update(base or {})
    if "auto_sort" in raw:
        out["auto_sort"] = bool(raw["auto_sort"])
    return out


def _user_brief(u: User | None) -> dict | None:
    if u is None:
        return None
    return {"id": u.id, "username": u.username, "school": u.school}


def task_out(task: Task, member: TaskMember, owner: User | None) -> dict:
    return {
        "id": task.id,
        "name": task.name,
        "description": task.description,
        "task_type": task.task_type,
        "label_config": task.label_config,
        "classes": task.classes,
        "settings": {**DEFAULT_SETTINGS, **(task.settings or {})},
        "status": task.status,
        "created_at": iso(task.created_at),
        "updated_at": iso(task.updated_at),
        "owner": _user_brief(owner),
        "my_role": member.role,
        "my_status": member.status,
        "my_review_comment": member.review_comment,
        "is_manager": is_manager(member),
    }


def today_start_utc() -> datetime:
    """服务器本地时区的今天 0 点，转成 naive UTC。"""
    local_now = datetime.now().astimezone()
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (start - (local_now.utcoffset() or timedelta())).replace(tzinfo=None)


@router.get("/tasks")
def list_tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(Task, TaskMember)
        .join(TaskMember, TaskMember.task_id == Task.id)
        .where(TaskMember.user_id == user.id)
        .order_by(Task.status, Task.created_at.desc())
    ).all()
    if not rows:
        return []
    ids = [t.id for t, _ in rows]
    totals = {
        tid: (n, d or 0)
        for tid, n, d in db.execute(
            select(Image.task_id, func.count(), _done).where(Image.task_id.in_(ids)).group_by(Image.task_id)
        )
    }
    mine = {
        tid: (n, d or 0)
        for tid, n, d in db.execute(
            select(Image.task_id, func.count(), _done)
            .where(Image.task_id.in_(ids), Image.assignee_id == user.id)
            .group_by(Image.task_id)
        )
    }
    members = dict(
        db.execute(
            select(TaskMember.task_id, func.count()).where(TaskMember.task_id.in_(ids)).group_by(TaskMember.task_id)
        ).all()
    )
    owner_ids = {t.owner_id for t, _ in rows}
    owners = {u.id: u for u in db.scalars(select(User).where(User.id.in_(owner_ids)))}
    out = []
    for t, m in rows:
        total, done = totals.get(t.id, (0, 0))
        my_total, my_done = mine.get(t.id, (0, 0))
        out.append(
            {
                "id": t.id,
                "name": t.name,
                "status": t.status,
                "created_at": iso(t.created_at),
                "owner": _user_brief(owners.get(t.owner_id)),
                "my_role": m.role,
                "my_status": m.status,
                "is_manager": is_manager(m),
                "total": total,
                "done": done,
                "my_assigned": my_total,
                "my_done": my_done,
                "members": members.get(t.id, 0),
                "class_count": len(t.classes or []),
            }
        )
    return out


@router.post("/tasks")
def create_task(body: TaskIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        cfg, classes = labels.build_classes(body.label_config)
    except labels.LabelError as e:
        raise HTTPException(400, str(e)) from e
    task = Task(
        owner_id=user.id,
        name=body.name.strip(),
        description=body.description,
        task_type="armor4",
        label_config=cfg,
        classes=classes,
        settings=_clean_settings(body.settings),
    )
    db.add(task)
    db.flush()
    member = TaskMember(task_id=task.id, user_id=user.id, role="owner")
    db.add(member)
    db.commit()
    return task_out(task, member, user)


@router.get("/tasks/{task_id}")
def get_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task, member = load_task(db, task_id, user)
    return task_out(task, member, db.get(User, task.owner_id))


def _remap_classes(db: Session, task: Task, new_classes: list[dict]) -> None:
    """类别变化时按类别名把已有标注的 class id 重新映射；被删掉的类别如果已被使用则拒绝。"""
    old_names = [c["name"] for c in task.classes]
    new_index = {c["name"]: i for i, c in enumerate(new_classes)}
    mapping = {i: new_index.get(n) for i, n in enumerate(old_names)}
    if all(mapping[i] == i for i in mapping) and len(new_classes) >= len(old_names):
        return
    rows = db.execute(
        select(Image.id, Image.annotations).where(Image.task_id == task.id, Image.ann_count > 0)
    ).all()
    used_missing: set[str] = set()
    updates = []
    for image_id, anns in rows:
        new_anns = []
        for a in anns:
            ni = mapping.get(a["cls"])
            if ni is None:
                used_missing.add(old_names[a["cls"]] if a["cls"] < len(old_names) else str(a["cls"]))
            else:
                new_anns.append({**a, "cls": ni})
        updates.append({"id": image_id, "annotations": new_anns})
    if used_missing:
        raise HTTPException(400, f"以下类别已有标注，不能删除：{', '.join(sorted(used_missing))}")
    if updates:
        db.execute(update(Image), updates)
        db.execute(update(Image).where(Image.task_id == task.id, Image.ann_count > 0).values(version=Image.version + 1))


@router.patch("/tasks/{task_id}")
def patch_task(
    task_id: int, body: TaskPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    task, member = load_task_manager(db, task_id, user)
    if body.name is not None:
        task.name = body.name.strip()
    if body.description is not None:
        task.description = body.description
    if body.label_config is not None:
        try:
            cfg, classes = labels.build_classes(body.label_config)
        except labels.LabelError as e:
            raise HTTPException(400, str(e)) from e
        _remap_classes(db, task, classes)
        task.label_config = cfg
        task.classes = classes
    if body.settings is not None:
        task.settings = _clean_settings(body.settings, task.settings)
    if body.status is not None:
        task.status = body.status
    task.updated_at = utcnow()
    db.commit()
    return task_out(task, member, db.get(User, task.owner_id))


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task, member = load_task(db, task_id, user)
    if member.role != "owner":
        raise HTTPException(403, "只有任务创建者可以删除任务")
    db.execute(delete(Image).where(Image.task_id == task_id))
    db.execute(delete(TaskMember).where(TaskMember.task_id == task_id))
    db.delete(task)
    db.commit()
    storage.delete_task_files(task_id)
    return {"ok": True}


def member_stats(db: Session, task_id: int) -> dict[int, dict[str, int]]:
    today = today_start_utc()
    stats: dict[int, dict[str, int]] = {}
    for uid, status, n, anns, flagged, today_n in db.execute(
        select(
            Image.assignee_id,
            Image.status,
            func.count(),
            func.sum(Image.ann_count),
            func.sum(case((Image.flagged.is_(True), 1), else_=0)),
            func.sum(case((Image.done_at >= today, 1), else_=0)),
        )
        .where(Image.task_id == task_id)
        .group_by(Image.assignee_id, Image.status)
    ):
        s = stats.setdefault(
            uid if uid is not None else -1,
            {"assigned": 0, "done": 0, "todo": 0, "rework": 0, "ann_count": 0, "flagged": 0, "done_today": 0},
        )
        s["assigned"] += n
        s[status] = s.get(status, 0) + n
        s["ann_count"] += anns or 0
        s["flagged"] += flagged or 0
        s["done_today"] += today_n or 0
    return stats


@router.get("/tasks/{task_id}/stats")
def task_stats(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    load_task_manager(db, task_id, user)
    stats = member_stats(db, task_id)
    totals = {"total": 0, "done": 0, "todo": 0, "rework": 0, "ann_count": 0, "flagged": 0, "done_today": 0}
    for s in stats.values():
        totals["total"] += s["assigned"]
        for k in ("done", "todo", "rework", "ann_count", "flagged", "done_today"):
            totals[k] += s[k]
    totals["unassigned"] = stats.get(-1, {}).get("assigned", 0)
    members = []
    for m, u in db.execute(
        select(TaskMember, User)
        .join(User, User.id == TaskMember.user_id)
        .where(TaskMember.task_id == task_id)
        .order_by(TaskMember.joined_at)
    ):
        s = stats.get(u.id, {"assigned": 0, "done": 0, "todo": 0, "rework": 0, "ann_count": 0, "flagged": 0, "done_today": 0})
        members.append(
            {
                "user_id": u.id,
                "username": u.username,
                "school": u.school,
                "role": m.role,
                "status": m.status,
                "review_comment": m.review_comment,
                "submitted_at": iso(m.submitted_at),
                "reviewed_at": iso(m.reviewed_at),
                "joined_at": iso(m.joined_at),
                **s,
            }
        )
    return {**totals, "members": members}


@router.get("/tasks/{task_id}/my-progress")
def my_progress(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task, member = load_task(db, task_id, user)
    today = today_start_utc()
    out = {"assigned": 0, "done": 0, "todo": 0, "rework": 0, "ann_count": 0, "flagged": 0, "done_today": 0}
    for status, n, anns, flagged, today_n in db.execute(
        select(
            Image.status,
            func.count(),
            func.sum(Image.ann_count),
            func.sum(case((Image.flagged.is_(True), 1), else_=0)),
            func.sum(case((Image.done_at >= today, 1), else_=0)),
        )
        .where(Image.task_id == task_id, Image.assignee_id == user.id)
        .group_by(Image.status)
    ):
        out["assigned"] += n
        out[status] = n
        out["ann_count"] += anns or 0
        out["flagged"] += flagged or 0
        out["done_today"] += today_n or 0
    return {
        **out,
        "status": member.status,
        "review_comment": member.review_comment,
        "submitted_at": iso(member.submitted_at),
        "reviewed_at": iso(member.reviewed_at),
    }


@router.post("/tasks/{task_id}/submit")
def submit(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task, member = load_task(db, task_id, user)
    if task.status != "active":
        raise HTTPException(409, "任务已结束")
    if member.status not in ("labeling", "rejected"):
        raise HTTPException(409, "当前状态不能提交")
    total, done = db.execute(
        select(func.count(), _done).where(Image.task_id == task_id, Image.assignee_id == user.id)
    ).one()
    if not total:
        raise HTTPException(409, "你还没有被分配图片")
    if (done or 0) < total:
        raise HTTPException(409, f"还有 {total - (done or 0)} 张图片未完成，全部完成后才能提交")
    member.status = "submitted"
    member.submitted_at = utcnow()
    db.commit()
    return {"status": member.status}


@router.post("/tasks/{task_id}/withdraw")
def withdraw(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task, member = load_task(db, task_id, user)
    if member.status != "submitted":
        raise HTTPException(409, "只有待审核状态可以撤回")
    member.status = "labeling"
    db.commit()
    return {"status": member.status}


@router.post("/tasks/{task_id}/attachments")
def upload_attachment(
    task_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    load_task_manager(db, task_id, user)
    try:
        name = storage.save_attachment(task_id, file.filename or "image.png", file.file.read())
    except storage.ImageRejected as e:
        raise HTTPException(400, str(e)) from e
    return {"url": f"/api/tasks/{task_id}/attachments/{name}"}


@router.get("/tasks/{task_id}/attachments/{name}")
def get_attachment(
    task_id: int, name: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> FileResponse:
    if not member_can_view(db, task_id, user.id):
        raise HTTPException(404, "附件不存在")
    path = (storage.attachment_dir(task_id) / name).resolve()
    if path.parent != storage.attachment_dir(task_id).resolve() or not path.is_file():
        raise HTTPException(404, "附件不存在")
    return FileResponse(
        path,
        media_type=storage.MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
