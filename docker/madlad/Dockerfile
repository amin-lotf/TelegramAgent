FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/appuser/.cache/huggingface \
    PATH=/opt/venv/bin:$PATH

SHELL ["/bin/bash", "-lc"]

RUN apt-get update -y --fix-missing \
    && apt-get install -y --no-install-recommends \
       build-essential ca-certificates curl git software-properties-common wget \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update -y \
    && apt-get install -y --no-install-recommends \
       python3.11 python3.11-dev python3.11-venv python3-pip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 --shell /bin/bash appuser \
    && mkdir -p /home/appuser/.cache/huggingface /app /adapters \
    && chown -R appuser:appuser /home/appuser /app /adapters

RUN python3.11 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --upgrade "pip<25" "setuptools>=70,<82" wheel \
    && /opt/venv/bin/python -m pip install --no-cache-dir \
       torch==2.7.1 --index-url https://download.pytorch.org/whl/cu128

WORKDIR /app

COPY docker/madlad/requirements.txt /app/requirements.txt
RUN /opt/venv/bin/python -m pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=appuser:appuser src /app/src
COPY --chown=appuser:appuser docker/madlad/app /app/app

USER appuser

ENV HOST=0.0.0.0 \
    PORT=8000 \
    PYTHONPATH=/app/src \
    MADLAD_MODEL_ID=google/madlad400-3b-mt \
    MADLAD_ADAPTER_DIR=/adapters

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
