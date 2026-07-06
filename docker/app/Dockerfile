FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./


FROM base AS telegram-auth

RUN uv sync --extra telegram-auth --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra telegram-auth --extra apps --no-dev --frozen



FROM base AS orchestration

RUN uv sync --extra orchestration --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra orchestration --extra apps --no-dev --frozen



FROM base AS video-processing

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN uv sync --extra video-processing --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra video-processing --extra apps --no-dev --frozen
