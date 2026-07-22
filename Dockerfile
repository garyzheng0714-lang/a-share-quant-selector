# CI 通过 build args 传入已审核的 digest；生产 workflow 会拒绝非 digest 镜像。
ARG NODE_IMAGE=node:22.17.1-bookworm-slim@sha256:2fa754a9ba4d7adbd2a51d182eaabbe355c82b673624035a38c0d42b08724854
ARG PYTHON_IMAGE=python:3.11.15-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba

# 变量默认值与发布参数都同时锁定 tag 和 digest；Hadolint 无法解析 FROM 中的 ARG。
# hadolint ignore=DL3006
FROM ${NODE_IMAGE} AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# hadolint ignore=DL3006
FROM ${PYTHON_IMAGE} AS python-dependencies
WORKDIR /build
COPY requirements.lock ./
# 除纯 Python 的 jsonpath 外只接受 wheel；禁用隔离构建，避免额外下载未锁定的构建依赖。
RUN pip install --no-cache-dir --no-compile --no-build-isolation \
    --require-hashes --only-binary=:all: --no-binary=jsonpath \
    --prefix=/install -r requirements.lock

# hadolint ignore=DL3006
FROM ${PYTHON_IMAGE} AS runtime
ARG GIT_COMMIT_SHA
LABEL org.opencontainers.image.revision="${GIT_COMMIT_SHA}"
ENV GIT_COMMIT_SHA="${GIT_COMMIT_SHA}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

# 基础镜像按 digest 固定；构建时安装该 Debian 版本已经发布的安全修复。
# 运行期不需要 Python 打包工具，移除后同时缩小攻击面。
# hadolint ignore=DL3005
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes setuptools wheel

RUN groupadd --gid 10001 quant \
    && useradd --uid 10001 --gid quant --create-home --no-log-init \
        --shell /usr/sbin/nologin quant
WORKDIR /app
COPY --from=python-dependencies /install /usr/local
COPY --chown=quant:quant . .
COPY --from=frontend-builder --chown=quant:quant /frontend/dist ./frontend/dist
RUN mkdir -p data state && chown -R quant:quant data state

USER 10001:10001
EXPOSE 5000
CMD ["gunicorn", "--bind=0.0.0.0:5000", "--workers=1", "--threads=8", "--timeout=60", "web_server:create_app()"]
