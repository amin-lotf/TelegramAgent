from __future__ import annotations

from telegram_agent.core.telegram_ingress.api.v1.fastapi_app import create_app
from telegram_agent.core.telegram_ingress.api.v1.messages.dependencies import (
    get_user_message_service,
)

from tests.support.fastapi import set_expected_api_token
from tests.support.live_server import LiveServer


class StubUserMessageService:
    def __init__(self) -> None:
        self.commands = []

    async def create_user_message(self, command):
        self.commands.append(command)
        return object()


def test_receive_telegram_message_accepts_request_and_maps_caption(telegram_message_payload) -> None:
    service = StubUserMessageService()
    app = create_app()
    set_expected_api_token(app, "test-token")
    app.dependency_overrides[get_user_message_service] = lambda: service

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
