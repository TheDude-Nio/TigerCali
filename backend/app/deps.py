from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from .db import get_db, utcnow
from .models import AuthSession, Image, Task, TaskMember, User
from .security import token_hash

COOKIE_NAME = "tigercali_session"
MANAGER_ROLES = ("owner", "manager")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        raise HTTPException(401, "请先登录")
    row = db.execute(
        select(User, AuthSession.expires_at)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(AuthSession.token_hash == token_hash(token))
    ).first()
    if row is None or row[1] < utcnow():
        raise HTTPException(401, "登录已过期，请重新登录")
    return row[0]


def is_manager(member: TaskMember) -> bool:
    return member.role in MANAGER_ROLES


def load_task(db: Session, task_id: int, user: User) -> tuple[Task, TaskMember]:
    row = db.execute(
        select(Task, TaskMember)
        .join(TaskMember, and_(TaskMember.task_id == Task.id, TaskMember.user_id == user.id))
        .where(Task.id == task_id)
    ).first()
    if row is None:
        raise HTTPException(404, "任务不存在，或你不是该任务的成员")
    return row[0], row[1]


def load_task_manager(db: Session, task_id: int, user: User) -> tuple[Task, TaskMember]:
    task, member = load_task(db, task_id, user)
    if not is_manager(member):
        raise HTTPException(403, "需要该任务的管理员权限")
    return task, member


def load_image(db: Session, image_id: int, user: User) -> tuple[Image, Task, TaskMember]:
    img = db.get(Image, image_id)
    if img is None:
        raise HTTPException(404, "图片不存在")
    task, member = load_task(db, img.task_id, user)
    return img, task, member


def member_can_view(db: Session, task_id: int, user_id: int) -> bool:
    return (
        db.scalar(select(TaskMember.id).where(TaskMember.task_id == task_id, TaskMember.user_id == user_id))
        is not None
    )
