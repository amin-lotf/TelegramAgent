from __future__ import annotations

from fastapi.testclient import TestClient

from telegram_agent.core.admin_dashboard_v2.api.v1.fastapi_app import create_app
from telegram_agent.core.admin_dashboard_v2.common.settings import Settings
from tests.admin_dashboard_v2.conftest import TEST_PASSWORD, TEST_PASSWORD_HASH


def test_routes_require_admin_and_render_database_failure() -> None:
    settings = Settings(
        telegram_ingress_read_database_url="postgresql://invalid:invalid@127.0.0.1:1/db",
        content_processing_read_database_url="postgresql://invalid:invalid@127.0.0.1:1/db",
        agent_runtime_read_database_url="postgresql://invalid:invalid@127.0.0.1:1/db",
        admin_username="operator",
        admin_password_hash=f"'{TEST_PASSWORD_HASH}'",
        cursor_secret="dashboard-v2-test-cursor-secret-000000",
        database_connect_timeout_seconds=0.1,
        database_pool_timeout_seconds=0.1,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        unauthorized = client.get("/messages")
        assert unauthorized.status_code == 401
        assert "Basic" in unauthorized.headers["www-authenticate"]
        response = client.get("/messages", auth=("operator", TEST_PASSWORD))
        assert response.status_code == 200
        assert "Telegram Ingress" in response.text
        assert "invalid:invalid" not in response.text
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cache-control"] == "no-store"
        empty_filters = client.get(
            "/messages",
            params={"chat_id": "", "has_attachment": "", "date_from": ""},
            auth=("operator", TEST_PASSWORD),
        )
        assert empty_filters.status_code == 200
