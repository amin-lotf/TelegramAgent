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



FROM base AS telegram-ingress

RUN uv sync --extra telegram-ingress --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra telegram-ingress --extra apps --no-dev --frozen



FROM base AS content-processing

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN uv sync --extra content-processing --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra content-processing --extra apps --no-dev --frozen


FROM content-processing AS content-processing-worker
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh
RUN deno --version


FROM base AS whisperx

RUN apt-get update -o Acquire::Retries=5 \
 && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    libgl1 \
    libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

RUN uv sync --extra whisperx --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra whisperx --extra apps --no-dev --frozen


FROM base AS sensevoice

RUN apt-get update -o Acquire::Retries=5 \
 && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    libgl1 \
    libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

RUN uv sync --extra sensevoice --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra sensevoice --extra apps --no-dev --frozen


FROM base AS agent-runtime

RUN uv sync --extra agent-runtime --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra agent-runtime --extra apps --no-dev --frozen


FROM base AS llm-gateway

RUN uv sync --extra llm-gateway --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra llm-gateway --extra apps --no-dev --frozen


FROM base AS chunking

RUN uv sync --extra chunking --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra chunking --extra apps --no-dev --frozen


FROM base AS embedding

RUN uv sync --extra embedding --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra embedding --extra apps --no-dev --frozen


FROM base AS admin-dashboard

RUN uv sync --extra admin-dashboard --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra admin-dashboard --extra apps --no-dev --frozen
