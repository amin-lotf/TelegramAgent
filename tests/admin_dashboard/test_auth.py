from telegram_agent.core.admin_dashboard.common.settings import Settings
from telegram_agent.core.admin_dashboard.api.v1.auth import attempt_login


def test_login_success() -> None:
    settings = Settings(
        admin_username="admin",
        admin_password="secret",
        session_secret="session",
    )
    assert attempt_login(username="admin", password="secret", app_settings=settings)


def test_login_failure() -> None:
    settings = Settings(
        admin_username="admin",
        admin_password="secret",
        session_secret="session",
    )
    assert not attempt_login(username="admin", password="wrong", app_settings=settings)
