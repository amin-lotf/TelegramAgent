from __future__ import annotations

from telegram_agent.core.telegram_ingress.api.v1.fastapi_app import create_app
from telegram_agent.core.telegram_ingress.api.v1.messages.dependencies import (
    get_attachment_processing_result_service,
)
from telegram_agent.core.telegram_ingress.common.results import (
    ApplyAttachmentProcessingResultResult,
)
from tests.support.fastapi import set_expected_api_token
from tests.support.live_server import LiveServer


class StubProcessingResultService:
    def __init__(self) -> None:
        self.commands = []

    async def apply(self, command):
        self.commands.append(command)
        return ApplyAttachmentProcessingResultResult(applied=True)


def test_content_processing_callback_maps_request_to_command() -> None:
    service = StubProcessingResultService()
    app = create_app()
    set_expected_api_token(app, "content-token")
    app.dependency_overrides[get_attachment_processing_result_service] = (
        lambda: service
    )

    message_id = "2ae31ed0-f21d-4f8d-96cb-2b8d443a7d5f"
    attachment_id = "594040be-1d98-4769-882b-b87daeeab567"
    with LiveServer(app) as server:
        response = server.request(
            "POST",
            f"/api/v1/telegram/attachments/{attachment_id}/processing-result",
            json_body={
                "ingress_message_id": message_id,
                "status": "completed",
                "transcribed_text": "voice transcript",
            },
            headers={"Authorization": "Bearer content-token"},
        )

    assert response.status_code == 204
    assert len(service.commands) == 1
    command = service.commands[0]
    assert str(command.ingress_message_id) == message_id
    assert str(command.ingress_attachment_id) == attachment_id
    assert command.transcribed_text == "voice transcript"
