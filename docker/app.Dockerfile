# syntax=docker/dockerfile:1
# Security Vision: una imagen, dos destinos.
#   docker build -f docker/app.Dockerfile --target api    -t security-vision-api .
#   docker build -f docker/app.Dockerfile --target worker -t security-vision-worker .
# Las versiones están fijadas (comprobadas en el registro el 2026-11-13).

# ---------------------------------------------------------------- web (React + Vite)
FROM node:26.13.0-bookworm-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

# ---------------------------------------------------------------- base Python
FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /app
RUN useradd --system --uid 10001 --home-dir /app sv
COPY pyproject.toml uv.lock README.md alembic.ini ./

# ---------------------------------------------------------------- API (+ frontend compilado)
FROM base AS api
RUN uv sync --frozen --no-dev --no-install-project --extra otel
COPY src ./src
COPY apps/api ./apps/api
COPY apps/processing-worker ./apps/processing-worker
RUN uv sync --frozen --no-dev --extra otel
COPY --from=web /web/dist /app/web
COPY ml/model_registry ./ml/model_registry
ENV SV_WEB_DIST=/app/web SV_STORAGE_DIR=/data/storage PATH="/app/.venv/bin:$PATH"
RUN mkdir -p /data/storage && chown -R sv /app /data
USER sv
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health/live').status!=200)"
CMD ["uvicorn", "security_vision_api.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]

# ---------------------------------------------------------------- worker (captura + IA)
# onnxruntime-gpu trae CUDA/cuDNN como paquetes pip (nvidia-*): con la GPU expuesta por el NVIDIA Container
# Toolkit usa CUDA; sin ella cae a CPU (SV_INFERENCE_DEVICES=["cuda","cpu"]). Los .onnx no se versionan:
# se montan en /app/ml/model_registry (ver docker-compose.yml).
FROM base AS worker
RUN uv sync --frozen --no-dev --no-install-project --extra inference --extra otel
COPY src ./src
COPY apps/api ./apps/api
COPY apps/processing-worker ./apps/processing-worker
RUN uv sync --frozen --no-dev --extra inference --extra otel
COPY ml/model_registry ./ml/model_registry
ENV SV_STORAGE_DIR=/data/storage SV_WORKER_METRICS_HOST=0.0.0.0 PATH="/app/.venv/bin:$PATH"
RUN mkdir -p /data/storage && chown -R sv /app /data
USER sv
EXPOSE 9101
CMD ["sv-worker"]
