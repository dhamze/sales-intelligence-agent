# Backend image: one image, three roles (API, worker, migrations), chosen by the command.
# Build from the repository root:  docker build -f deploy/backend.Dockerfile -t sia-backend .
# Base images are pinned by version AND digest so builds are reproducible.

FROM ghcr.io/astral-sh/uv:0.13.4@sha256:9f130421e930bfbdc563c00740466603f8723158e90297d07957c2294640262b AS uv

FROM python:3.13.16-slim-trixie@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_FROZEN=1
WORKDIR /app
# Dependencies first (cached until uv.lock changes), then our own code.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/README.md backend/
RUN uv sync --no-dev --package sia-backend --no-install-workspace
COPY backend/src backend/src
RUN uv sync --no-dev --package sia-backend --no-editable

FROM python:3.13.16-slim-trixie@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f
# Run as an unprivileged user: a compromised process can't modify the image or own the host.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY backend/alembic.ini backend/alembic.ini
COPY backend/migrations backend/migrations
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 SIA_ENV=production
USER app
EXPOSE 8000
# API by default. The worker runs `python -m sia.worker`; migrations run
# `alembic -c backend/alembic.ini upgrade head` (see deploy/compose.prod.yaml).
# --proxy-headers: trust X-Forwarded-For from Caddy (the API port is never published).
CMD ["uvicorn", "sia.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
