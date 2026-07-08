from __future__ import annotations

from telegram_agent.core.telegram_auth.api.v1.auth.dependencies import (
    get_telegram_auth_service,
)
from telegram_agent.core.telegram_auth.api.v1.fastapi_app import create_app

from tests.support.fastapi import set_expected_api_token
from tests.support.live_server import LiveServer


class StubUserAuthenticationService:
    def __init__(self, *, verify_result: bool = True, check_result: bool = True) -> None:
        self.verify_result = verify_result
        self.check_result = check_result
        self.verify_calls = []
        self.check_calls = []

    async def verify_user(self, command):
        self.verify_calls.append(command)
        return self.verify_result

    async def check_user(self, telegram_user_id: int):
        self.check_calls.append(telegram_user_id)
        return self.check_result


def test_verify_route_returns_success_and_passes_command(telegram_verify_payload) -> None:
    service = StubUserAuthenticationService(verify_result=True)
    app = create_app()
    set_expected_api_token(app, "test-token")
    app.dependency_overrides[get_telegram_auth_service] = lambda: service

    with LiveServer(app) as server:
        response = server.request(
            "POST",
            "/api/v1/telegram-auth/verify",
            json_body=telegram_verify_payload,
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "verified": True,
        "message": "Verified successfully",
    }
    assert len(service.verify_calls) == 1
    command = service.verify_calls[0]
    assert command.telegram_user_id == telegram_verify_payload["telegram_user_id"]
    assert command.chat_id == telegram_verify_payload["chat_id"]
    assert command.password == telegram_verify_payload["password"]
    assert command.username == telegram_verify_payload["username"]


def test_verify_route_returns_wrong_password_message(telegram_verify_payload) -> None:
    service = StubUserAuthenticationService(verify_result=False)
    app = create_app()
    set_expected_api_token(app, "test-token")
    app.dependency_overrides[get_telegram_auth_service] = lambda: service

    with LiveServer(app) as server:
        response = server.request(
            "POST",
            "/api/v1/telegram-auth/verify",
            json_body=telegram_verify_payload,
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "verified": False,
        "message": "Wrong password",
    }


def test_check_route_returns_prompt_when_user_is_not_verified() -> None:
    service = StubUserAuthenticationService(check_result=False)
    app = create_app()
    set_expected_api_token(app, "test-token")
    app.dependency_overrides[get_telegram_auth_service] = lambda: service

    with LiveServer(app) as server:
        response = server.request(
            "POST",
            "/api/v1/telegram-auth/check",
            json_body={"telegram_user_id": 9001},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "verified": False,
        "message": "Please verify first using /verify password",
    }
    assert service.check_calls == [9001]


def test_verify_route_requires_api_token(telegram_verify_payload) -> None:
    service = StubUserAuthenticationService()
    app = create_app()
    set_expected_api_token(app, "test-token")
    app.dependency_overrides[get_telegram_auth_service] = lambda: service

    with LiveServer(app) as server:
        response = server.request(
            "POST",
            "/api/v1/telegram-auth/verify",
            json_body=telegram_verify_payload,
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
