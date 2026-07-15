FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir uv \
    && groupadd --system --gid 10001 dashboard \
    && useradd --system --uid 10001 --gid dashboard --home-dir /nonexistent dashboard

COPY pyproject.toml uv.lock ./
RUN uv sync --extra apps --extra admin-dashboard-v2 --no-dev --frozen --no-install-project

COPY src ./src
RUN uv sync --extra apps --extra admin-dashboard-v2 --no-dev --frozen

USER dashboard
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "telegram_agent.core.admin_dashboard_v2.api.v1.fastapi_app:fastapi_app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
