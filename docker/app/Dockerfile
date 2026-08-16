FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04 AS cosyvoice-runtime

ARG COSYVOICE_REPO_REF=main
ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-lc"]

RUN apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --no-install-recommends \
       build-essential ca-certificates curl ffmpeg git git-lfs libsox-dev sox wget \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install
RUN wget --quiet \
      https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh \
      -O /tmp/miniforge.sh \
    && bash /tmp/miniforge.sh -b -p /opt/miniforge \
    && rm /tmp/miniforge.sh \
    && /opt/miniforge/bin/conda create -y -p /opt/cosyvoice python=3.10 \
    && /opt/miniforge/bin/conda install -y -p /opt/cosyvoice -c conda-forge pynini==2.1.5 \
    && /opt/miniforge/bin/conda clean -afy
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice \
    && git -C /opt/CosyVoice checkout "${COSYVOICE_REPO_REF}" \
    && git -C /opt/CosyVoice submodule update --init --recursive
COPY docker/app/cosyvoice-requirements.txt /tmp/cosyvoice-requirements.txt
RUN /opt/cosyvoice/bin/python -m pip install --upgrade "pip<25" "setuptools>=70,<82" wheel \
    && /opt/cosyvoice/bin/python -m pip install --no-cache-dir \
       torch==2.7.1 torchaudio==2.7.1 \
       --index-url https://download.pytorch.org/whl/cu128 \
    && /opt/cosyvoice/bin/python -m pip install --no-cache-dir --no-build-isolation \
       openai-whisper==20250625 \
    && /opt/cosyvoice/bin/python -m pip install --no-cache-dir \
       -r /tmp/cosyvoice-requirements.txt


FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04 AS sam-audio-runtime

ARG SAM_AUDIO_REPO_REF=bb4c6999d2677c7402360e426afc01ddfad6dce0
ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-lc"]

RUN apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --no-install-recommends \
       build-essential ca-certificates curl ffmpeg git git-lfs libgl1 libglib2.0-0 \
       libsndfile1 libsox-dev pkg-config sox wget \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install
RUN wget --quiet \
      https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh \
      -O /tmp/miniforge.sh \
    && bash /tmp/miniforge.sh -b -p /opt/miniforge \
    && rm /tmp/miniforge.sh \
    && /opt/miniforge/bin/conda create -y -p /opt/sam-audio python=3.11 \
    && /opt/miniforge/bin/conda clean -afy
COPY docker/app/sam-audio-requirements.txt /tmp/sam-audio-requirements.txt
RUN /opt/sam-audio/bin/python -m pip install --upgrade "pip<25" "setuptools>=70,<82" wheel \
    && /opt/sam-audio/bin/python -m pip install --no-cache-dir \
       torch==2.7.1 torchaudio==2.7.1 torchvision==0.22.1 \
       --index-url https://download.pytorch.org/whl/cu128 \
    && (/opt/sam-audio/bin/python -m pip install --no-cache-dir torchcodec==0.4.0 \
        || /opt/sam-audio/bin/python -m pip install --no-cache-dir torchcodec) \
    && /opt/sam-audio/bin/python -m pip install --no-cache-dir \
       -r /tmp/sam-audio-requirements.txt \
    && /opt/sam-audio/bin/python -m pip install --no-cache-dir \
       "git+https://github.com/facebookresearch/sam-audio.git@${SAM_AUDIO_REPO_REF}"


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


FROM base AS gpu-execution

RUN uv sync --extra gpu-execution --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra gpu-execution --extra apps --no-dev --frozen


FROM base AS gpu-execution-worker

RUN apt-get update -o Acquire::Retries=5 \
 && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsndfile1 \
    libsox3 \
    rubberband-cli \
    sox \
 && rm -rf /var/lib/apt/lists/*

RUN uv sync --extra gpu-execution --extra whisperx --extra sensevoice --extra apps --no-dev --frozen --no-install-project

COPY src ./src

RUN uv sync --extra gpu-execution --extra whisperx --extra sensevoice --extra apps --no-dev --frozen

COPY --from=cosyvoice-runtime /opt/cosyvoice /opt/cosyvoice
COPY --from=cosyvoice-runtime /opt/CosyVoice /opt/CosyVoice
COPY --from=sam-audio-runtime /opt/sam-audio /opt/sam-audio

ENV PYTHONPATH="/app/src:/opt/CosyVoice:/opt/CosyVoice/third_party/Matcha-TTS"


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
