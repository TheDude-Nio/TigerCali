from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import labels
from ..config import settings
from ..db import get_db, iso, utcnow
from ..deps import COOKIE_NAME, get_current_user
from ..models import AuthSession, TaskMember, User
from ..security import hash_password, login_limiter, new_token, token_hash, verify_password

router = APIRouter(prefix="/api", tags=["auth"])

USERNAME_RE = re.compile(r"^[\w.\-]{2,32}$")


class RegisterIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)
    school: str = Field(max_length=128)
    invite_code: str = ""


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)


class PasswordIn(BaseModel):
    old_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


class ProfileIn(BaseModel):
    school: str = Field(max_length=128)


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "school": u.school, "created_at": iso(u.created_at)}


def _check_password(pw: str) -> None:
    if len(pw) < 6:
        raise HTTPException(400, "密码至少 6 位")


def _check_school(school: str) -> str:
    school = " ".join(school.split())
    if not 2 <= len(school) <= 64:
        raise HTTPException(400, "学校名称长度应为 2~64 个字符")
    return school


def _start_session(db: Session, user: User, response: Response) -> None:
    token = new_token()
    now = utcnow()
    db.add(
        AuthSession(
            token_hash=token_hash(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(days=settings.session_days),
        )
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookie,
        path="/",
    )


@router.get("/meta")
def get_meta() -> dict:
    return {"app_name": "华南虎一起标", "invite_required": bool(settings.invite_code), **labels.meta()}


@router.post("/auth/register")
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)) -> dict:
    if settings.invite_code and body.invite_code.strip() != settings.invite_code:
        raise HTTPException(403, "邀请码错误")
    username = body.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "用户名为 2~32 位，只能包含中英文、数字、下划线、点和短横线")
    _check_password(body.password)
    school = _check_school(body.school)
    if db.scalar(select(User.id).where(func.lower(User.username) == username.lower())):
        raise HTTPException(409, "用户名已被占用")
    user = User(username=username, password_hash=hash_password(body.password), school=school)
    db.add(user)
    db.flush()
    _start_session(db, user, response)
    db.commit()
    return user_out(user)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    username = body.username.strip()
    key = f"{request.client.host if request.client else '-'}|{username.lower()}"
    if login_limiter.blocked(key):
        raise HTTPException(429, "登录失败次数过多，请 10 分钟后再试")
    user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        login_limiter.fail(key)
        raise HTTPException(400, "用户名或密码错误")
    login_limiter.reset(key)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at < utcnow()))
    _start_session(db, user, response)
    db.commit()
    return user_out(user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return user_out(user)


@router.patch("/auth/me")
def update_me(body: ProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    user.school = _check_school(body.school)
    db.add(user)
    db.commit()
    return user_out(user)


@router.post("/auth/password")
def change_password(
    body: PasswordIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "原密码错误")
    _check_password(body.new_password)
    user.password_hash = hash_password(body.new_password)
    db.add(user)
    # 其他设备上的登录全部失效，保留当前会话
    current = token_hash(request.cookies.get(COOKIE_NAME, ""))
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.token_hash != current))
    db.commit()
    return {"ok": True}


@router.get("/schools")
def list_schools(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(User.school, func.count()).group_by(User.school).order_by(func.count().desc()).limit(500)
    ).all()
    return [{"school": s, "users": n} for s, n in rows]


@router.get("/users")
def search_users(
    q: str = "",
    school: str = "",
    task_id: int | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(User.id, User.username, User.school)
    q = q.strip()
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(User.username.ilike(f"%{escaped}%", escape="\\"))
    if school:
        stmt = stmt.where(User.school == school)
    rows = db.execute(stmt.order_by(func.length(User.username), User.username).limit(min(max(limit, 1), 200))).all()
    member_ids: set[int] = set()
    if task_id is not None and rows:
        member_ids = set(
            db.scalars(
                select(TaskMember.user_id).where(
                    TaskMember.task_id == task_id, TaskMember.user_id.in_([r[0] for r in rows])
                )
            )
        )
    return [{"id": i, "username": n, "school": s, "is_member": i in member_ids} for i, n, s in rows]
