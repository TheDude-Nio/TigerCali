# 基础镜像走 AWS ECR 上的官方镜像副本（国内比 Docker Hub 稳），需要时用 --build-arg 换掉
ARG NODE_IMAGE=public.ecr.aws/docker/library/node:22-alpine
ARG PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.12-slim

# ---------- 阶段一：构建前端 ----------
FROM ${NODE_IMAGE} AS web
ARG NPM_REGISTRY=https://registry.npmmirror.com
WORKDIR /web
# 先只拷依赖清单：源码变了也能复用 npm ci 这一层缓存
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund --registry=${NPM_REGISTRY}
COPY frontend/ ./
RUN npm run build

# ---------- 阶段二：运行环境（只带后端代码和前端产物，不含 node） ----------
FROM ${PYTHON_IMAGE}
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    TIGERCALI_DATA_DIR=/data \
    TIGERCALI_FRONTEND_DIST=/app/frontend/dist \
    TIGERCALI_PORT=8000
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/dist /app/frontend/dist

# 数据库、图片、缩略图、预标注模型（models/armor.onnx）都在数据卷里
VOLUME ["/data"]
EXPOSE 8000

# slim 镜像没有 wget/curl，用 Python 自带的 urllib 探活
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('TIGERCALI_PORT', '8000'), timeout=3)" || exit 1

CMD ["python", "-m", "app"]
