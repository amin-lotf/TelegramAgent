FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

RUN apt-get update -o Acquire::Retries=5 \
 && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    libgl1 \
    libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

COPY src /app/src

RUN pip install --no-cache-dir -U pip setuptools wheel \
 && pip install --no-cache-dir \
    "colorlog>=6.10.1" \
    "fastapi>=0.136.1" \
    "pydantic>=2.13.4" \
    "pydantic-settings>=2.14.0" \
    "python-dotenv>=1.1.1" \
    "python-multipart>=0.0.20" \
    "uvicorn>=0.46.0" \
    "whisperx>=3.3,<4"
