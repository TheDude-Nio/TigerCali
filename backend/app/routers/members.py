from __future__ import annotations

import math
import random
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import get_current_user, load_task_manager
from ..models import Image, Task, TaskMember, User

router = APIRouter(prefix="/api/tasks/{task_id}", tags=["members"])

CHUNK = 500


class AddMembersIn(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=500)
    role: Literal["annotator", "manager"] = "annotator"


class RoleIn(BaseModel):
    role: Literal["annotator", "manager"]


class AssignEntry(BaseModel):
    user_id: int
    value: float = 0


class AssignIn(BaseModel):
    # even=一键均分, count=按张数, ratio=按百分比
    mode: Literal["even", "count", "ratio"]
    entries: list[AssignEntry] = Field(min_length=1)
    # sequential=按文件名连续分块（适合视频序列），random=随机打散
    order: Literal["sequential", "random"] = "sequential"
    # 先回收所有人未完成(todo)的图片再一起分配
    reclaim: bool = False


class ReviewIn(BaseModel):
    action: Literal["approve", "reject"]
    comment: str = Field("", max_length=5000)


def _get_member(db: Session, task_id: int, user_id: int) -> TaskMember:
    m = db.scalar(select(TaskMember).where(TaskMember.task_id == task_id, TaskMember.user_id == user_id))
    if m is None:
        raise HTTPException(404, "该用户不是任务成员")
    return m


def _set_assignee(db: Session, ids: list[int], user_id: int | None) -> None:
    for i in range(0, len(ids), CHUNK):
        db.execute(update(Image).where(Image.id.in_(ids[i : i + CHUNK])).values(assignee_id=user_id))


@router.post("/members")
def add_members(
    task_id: int, body: AddMembersIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    load_task_manager(db, task_id, user)
    wanted = set(body.user_ids)
    existing = set(
        db.scalars(select(TaskMember.user_id).where(TaskMember.task_id == task_id, TaskMember.user_id.in_(wanted)))
    )
    valid = set(db.scalars(select(User.id).where(User.id.in_(wanted - existing))))
    for uid in sorted(valid):
        db.add(TaskMember(task_id=task_id, user_id=uid, role=body.role))
    db.commit()
    return {"added": len(valid), "already": len(existing)}


@router.patch("/members/{user_id}")
def set_role(
    task_id: int, user_id: int, body: RoleIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    load_task_manager(db, task_id, user)
    m = _get_member(db, task_id, user_id)
    if m.role == "owner":
        raise HTTPException(400, "不能修改创建者的角色")
    m.role = body.role
    db.commit()
    return {"role": m.role}


@router.delete("/members/{user_id}")
def remove_member(
    task_id: int, user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    load_task_manager(db, task_id, user)
    m = _get_member(db, task_id, user_id)
    if m.role == "owner":
        raise HTTPException(400, "不能移除任务创建者")
    # 已完成的标注保留在图片上，图片回到未分配池
    released = db.execute(
        update(Image).where(Image.task_id == task_id, Image.assignee_id == user_id).values(assignee_id=None)
    ).rowcount
    db.delete(m)
    db.commit()
    return {"released": released}


def _split_counts(n: int, body: AssignIn) -> list[int]:
    k = len(body.entries)
    if body.mode == "even":
        base, extra = divmod(n, k)
        return [base + (1 if i < extra else 0) for i in range(k)]
    if body.mode == "count":
        counts = [int(e.value) for e in body.entries]
        if any(c < 0 for c in counts):
            raise HTTPException(400, "张数不能为负数")
        if sum(counts) > n:
            raise HTTPException(400, f"分配总数 {sum(counts)} 超过了可分配的 {n} 张")
        return counts
    # ratio：百分比，总和不超过 100，剩下的留在未分配池
    ratios = [e.value for e in body.entries]
    if any(r < 0 for r in ratios):
        raise HTTPException(400, "比例不能为负数")
    if sum(ratios) > 100.0001:
        raise HTTPException(400, "比例总和不能超过 100%")
    exact = [n * r / 100 for r in ratios]
    counts = [math.floor(x) for x in exact]
    target = min(n, round(sum(exact)))
    # 最大余数法补齐
    for i in sorted(range(k), key=lambda i: exact[i] - counts[i], reverse=True)[: max(0, target - sum(counts))]:
        counts[i] += 1
    return counts


@router.post("/assign")
def assign(task_id: int, body: AssignIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task, _ = load_task_manager(db, task_id, user)
    if task.status != "active":
        raise HTTPException(409, "任务已结束，请先重新开启任务")
    uids = [e.user_id for e in body.entries]
    if len(set(uids)) != len(uids):
        raise HTTPException(400, "成员重复")
    members = {
        m.user_id: m
        for m in db.scalars(select(TaskMember).where(TaskMember.task_id == task_id, TaskMember.user_id.in_(uids)))
    }
    if len(members) != len(uids):
        raise HTTPException(400, "只能给任务成员分配图片")

    reclaimed = 0
    if body.reclaim:
        reclaimed = db.execute(
            update(Image)
            .where(Image.task_id == task_id, Image.assignee_id.is_not(None), Image.status == "todo")
            .values(assignee_id=None)
        ).rowcount

    pool = list(
        db.scalars(
            select(Image.id).where(Image.task_id == task_id, Image.assignee_id.is_(None)).order_by(Image.sort_key, Image.id)
        )
    )
    counts = _split_counts(len(pool), body)
    if body.order == "random":
        random.shuffle(pool)

    result = {}
    pos = 0
    for uid, c in zip(uids, counts):
        ids = pool[pos : pos + c]
        pos += c
        if ids:
            _set_assignee(db, ids, uid)
            m = members[uid]
            # 有了新图片，需要重新提交
            if m.status in ("submitted", "approved"):
                m.status = "labeling"
        result[str(uid)] = len(ids)
    db.commit()
    return {"assigned": result, "remaining": len(pool) - pos, "reclaimed": reclaimed}


@router.post("/members/{user_id}/reclaim")
def reclaim(
    task_id: int, user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    load_task_manager(db, task_id, user)
    _get_member(db, task_id, user_id)
    n = db.execute(
        update(Image)
        .where(Image.task_id == task_id, Image.assignee_id == user_id, Image.status == "todo")
        .values(assignee_id=None)
    ).rowcount
    db.commit()
    return {"reclaimed": n}


def maybe_finish(db: Session, task: Task) -> bool:
    """所有图片都已分配、完成，且所有标注员都审核通过 → 自动结束任务。"""
    total, unassigned, not_done = db.execute(
        select(
            func.count(),
            func.count().filter(Image.assignee_id.is_(None)),
            func.count().filter(Image.status != "done"),
        ).where(Image.task_id == task.id)
    ).one()
    if total == 0 or unassigned or not_done:
        return False
    pending = db.scalar(
        select(func.count())
        .select_from(TaskMember)
        .where(
            TaskMember.task_id == task.id,
            TaskMember.status != "approved",
            TaskMember.user_id.in_(
                select(Image.assignee_id).where(Image.task_id == task.id, Image.assignee_id.is_not(None)).distinct()
            ),
        )
    )
    if pending:
        return False
    task.status = "finished"
    task.updated_at = utcnow()
    return True


@router.post("/members/{user_id}/review")
def review(
    task_id: int,
    user_id: int,
    body: ReviewIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    task, _ = load_task_manager(db, task_id, user)
    m = _get_member(db, task_id, user_id)
    now = utcnow()
    m.review_comment = body.comment.strip()
    m.reviewed_at = now
    finished = False
    if body.action == "approve":
        if m.status != "submitted":
            raise HTTPException(409, "只能审核已提交的成员")
        m.status = "approved"
        db.execute(
            update(Image)
            .where(Image.task_id == task_id, Image.assignee_id == user_id)
            .values(flagged=False, review_note="")
        )
        db.flush()
        finished = maybe_finish(db, task)
    else:
        if m.status not in ("submitted", "approved"):
            raise HTTPException(409, "只能打回已提交或已通过的成员")
        m.status = "rejected"
        if task.status == "finished":
            task.status = "active"
        # 被标记的图片需要返工
        db.execute(
            update(Image)
            .where(Image.task_id == task_id, Image.assignee_id == user_id, Image.flagged.is_(True))
            .values(status="rework")
        )
    db.commit()
    return {"status": m.status, "task_finished": finished}
