"""运行配置，全部可通过 TIGERCALI_* 环境变量覆盖。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"TIGERCALI_{name}", default)


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(_env("DATA_DIR", str(ROOT_DIR / "data"))).resolve()
        self.database_url = _env("DATABASE_URL") or f"sqlite:///{self.data_dir / 'tigercali.db'}"
        self.frontend_dist = Path(_env("FRONTEND_DIST", str(ROOT_DIR / "frontend" / "dist"))).resolve()
        # 部署在 HTTPS 后面时打开，cookie 只通过 HTTPS 发送
        self.secure_cookie = _bool(_env("SECURE_COOKIE", "0"))
        # 设置后注册时需要填写邀请码，防止公网部署被随意注册
        self.invite_code = _env("INVITE_CODE", "") or ""
        self.session_days = int(_env("SESSION_DAYS", "30"))
        self.max_image_mb = int(_env("MAX_IMAGE_MB", "64"))
        self.thumb_size = int(_env("THUMB_SIZE", "320"))
        self.upload_workers = int(_env("UPLOAD_WORKERS", str(min(8, os.cpu_count() or 2))))

        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"


settings = Settings()
