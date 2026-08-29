from __future__ import annotations

from telegram_agent.core.telegram_ingress.api.v1.fastapi_app import create_app
from telegram_agent.core.telegram_ingress.api.v1.messages.dependencies import (
    get_cancel_all_command_service,
    get_telegram_auth_client,
    get_user_message_service,
)
from telegram_agent.core.telegram_ingress.api.v1.messages.router import (
    _is_cancel_all_command,
)
from telegram_agent.core.telegram_ingress.api.v1.messages.schemas import TelegramUserRequest

from tests.support.fastapi import set_expected_api_token
from tests.support.live_server import LiveServer


class StubUserMessageService:
    def __init__(self) -> None:
        self.commands = []

    async def create_user_message(self, command):
        self.commands.append(command)
        return object()


class StubTelegramAuthClient:
    async def check_user(self, _telegram_user_id: int) -> None:
        return None


class StubCancelAllCommandService:
    def __init__(self) -> None:
        self.commands = []

    async def accept(self, command) -> None:
        self.commands.append(command)


def test_receive_telegram_message_accepts_request_and_maps_caption(telegram_message_payload) -> None:
    service = StubUserMessageService()
    app = create_app()
    set_expected_api_token(app, "test-token")
    app.dependency_overrides[get_user_message_service] = lambda: service
    app.dependency_overrides[get_telegram_auth_client] = lambda: StubTelegramAuthClient()

    payload = dict(telegram_message_payload)
    payload["text"] = None
    payload["caption"] = "Voice note caption"
    payload["attachment"] = {
        "type": "voice",
        "file_id": "voice-file-333",
        "file_unique_id": "voice-unique-333",
    }

    with LiveServer(app) as server:
        response = server.request(
            "POST",
            "/api/v1/telegram/messages",
            json_body=payload,
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert len(service.commands) == 1
    command = service.commands[0]
    assert command.update_id == payload["update_id"]
    assert command.reply_message_id == payload["reply_to_message_id"]
    assert command.text == "Voice note caption"
    assert command.attachment is not None
    assert command.attachment.file_id == "voice-file-333"


def test_receive_telegram_message_requires_api_token(telegram_message_payload) -> None:
    service = StubUserMessageService()
    app = create_app()
    set_expected_api_token(app, "test-token")
    app.dependency_overrides[get_user_message_service] = lambda: service
    app.dependency_overrides[get_telegram_auth_client] = lambda: StubTelegramAuthClient()

    with LiveServer(app) as server:
        response = server.request(
            "POST",
            "/api/v1/telegram/messages",
            json_body=telegram_message_payload,
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_receive_telegram_message_rejects_empty_message(telegram_message_payload) -> None:
    service = StubUserMessageService()
    app = create_app()
    set_expected_api_token(app, "test-token")
    app.dependency_overrides[get_user_message_service] = lambda: service
    app.dependency_overrides[get_telegram_auth_client] = lambda: StubTelegramAuthClient()

    payload = dict(telegram_message_payload)
    payload["text"] = None
    payload["caption"] = None
    payload["attachment"] = None

    with LiveServer(app) as server:
        response = server.request(
            "POST",
            "/api/v1/telegram/messages",
            json_body=payload,
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "value_error"


def test_cancel_all_command_variants_are_detected_without_attachments() -> None:
    base = {
        "telegram_user_id": 7,
        "chat_id": 100,
        "message_id": 20,
    }
    assert _is_cancel_all_command(TelegramUserRequest(**base, text="/cancel_all"))
    assert _is_cancel_all_command(
        TelegramUserRequest(**base, text=" /CANCEL_ALL@My_Bot ")
    )
    assert not _is_cancel_all_command(
        TelegramUserRequest(**base, text="/cancel_all now")
    )
    assert not _is_cancel_all_command(
        TelegramUserRequest(
            **base,
            text="/cancel_all",
            attachment={"type": "video", "file_id": "file"},
        )
    )


def test_cancel_all_is_routed_to_command_service(telegram_message_payload) -> None:
    messages = StubUserMessageService()
    commands = StubCancelAllCommandService()
    app = create_app()
    set_expected_api_token(app, "test-token")
    app.dependency_overrides[get_user_message_service] = lambda: messages
    app.dependency_overrides[get_cancel_all_command_service] = lambda: commands
    app.dependency_overrides[get_telegram_auth_client] = lambda: StubTelegramAuthClient()
    payload = dict(telegram_message_payload)
    payload["text"] = "/cancel_all"
    payload["caption"] = None
    payload["attachment"] = None
    with LiveServer(app) as server:
        response = server.request(
            "POST",
            "/api/v1/telegram/messages",
            json_body=payload,
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 202
    assert messages.commands == []
    assert len(commands.commands) == 1
    assert commands.commands[0].message_id == payload["message_id"]
