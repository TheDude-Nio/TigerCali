from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from . import models  # noqa: F401  注册表结构
from .config import settings
from .db import Base, engine
from .routers import auth, export, images, members, tasks

Base.metadata.create_all(engine)

app = FastAPI(title="华南虎一起标", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

for r in (auth.router, tasks.router, members.router, images.router, export.router):
    app.include_router(r)


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    return JSONResponse({"detail": f"参数错误 {loc}: {first.get('msg', '')}".strip()}, status_code=422)


class SelectiveGZip:
    """只压缩 JSON / JS / CSS，图片与导出的 zip 直接透传，避免浪费 CPU。"""

    _BINARY_SUFFIXES = ("/file", "/thumb", "/export")

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1024)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path: str = scope["path"]
            binary = path.endswith(self._BINARY_SUFFIXES) or "/attachments/" in path
            if not binary:
                await self.gzip(scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(SelectiveGZip)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


# ---------------------------------------------------------------- 前端静态文件

_dist = settings.frontend_dist
_index = _dist / "index.html"


@app.get("/assets/{path:path}")
def frontend_assets(path: str) -> FileResponse:
    base = (_dist / "assets").resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(404)
    # Vite 产物文件名带哈希，可以永久缓存
    return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str) -> Response:
    if full_path.startswith("api/"):
        raise HTTPException(404)
    candidate = (_dist / full_path).resolve() if full_path else None
    if candidate and _dist in candidate.parents and candidate.is_file():
        return FileResponse(candidate)
    if _index.is_file():
        return FileResponse(_index, headers={"Cache-Control": "no-cache"})
    return JSONResponse(
        {"detail": "前端尚未构建：请在 frontend 目录执行 npm install && npm run build"}, status_code=404
    )


def _ensure_path(p: Path) -> None:  # pragma: no cover
    p.mkdir(parents=True, exist_ok=True)


for _p in (settings.images_dir, settings.thumbs_dir, settings.attachments_dir):
    _ensure_path(_p)
