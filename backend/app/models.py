from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    school: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Task(Base):
    __tablename__ = "tasks"
    # 删除后 id 不复用：图片 URL 按 id 永久缓存，复用会让浏览器显示旧图
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    # 标注要求，Markdown
    description: Mapped[str] = mapped_column(Text, default="")
    task_type: Mapped[str] = mapped_column(String(20), default="armor4")
    # {"mode": "armor", "colors": [...], "tags": [...]} 或 {"mode": "custom", "names": [...]}
    label_config: Mapped[dict] = mapped_column(JSON)
    # 由 label_config 展开：[{"name": "B_1", "color": "B", "tag": "1"}, ...]，下标即 YOLO class id
    classes: Mapped[list] = mapped_column(JSON)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    # active | finished
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TaskMember(Base):
    __tablename__ = "task_members"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # owner | manager | annotator
    role: Mapped[str] = mapped_column(String(16), default="annotator")
    # labeling | submitted | approved | rejected
    status: Mapped[str] = mapped_column(String(16), default="labeling")
    review_comment: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        UniqueConstraint("task_id", "sha1", name="uq_image_sha1"),
        Index("ix_images_task_sort", "task_id", "sort_key"),
        Index("ix_images_task_assignee_status", "task_id", "assignee_id", "status"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    # 上传时的相对路径，如 seq1/frame_0001.jpg
    filename: Mapped[str] = mapped_column(String(255))
    # 自然排序键：frame2 排在 frame10 前面
    sort_key: Mapped[str] = mapped_column(String(512))
    sha1: Mapped[str] = mapped_column(String(40))
    ext: Mapped[str] = mapped_column(String(8))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer, default=0)
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # todo(未完成) | done(已完成) | rework(被打回需返工)
    status: Mapped[str] = mapped_column(String(8), default="todo")
    # [{"cls": 0, "pts": [[x, y] * 4]}]，像素坐标，点序固定为 左上、左下、右下、右上
    annotations: Mapped[list] = mapped_column(JSON, default=list)
    ann_count: Mapped[int] = mapped_column(Integer, default=0)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    review_note: Mapped[str] = mapped_column(String(500), default="")
    version: Mapped[int] = mapped_column(Integer, default=0)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
