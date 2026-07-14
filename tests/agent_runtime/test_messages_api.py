from uuid import uuid4

from telegram_agent.core.agent_runtime.api.v1.fastapi_app import create_app
from telegram_agent.core.agent_runtime.api.v1.messages.dependencies import (
    get_message_batch_ingestion_service,
)
from telegram_agent.core.agent_runtime.common.results import IngestMessageBatchResult
from telegram_agent.core.telegram_ingress.clients.agent_runtime import AgentRuntimeClient
from telegram_agent.core.telegram_ingress.common.commands import (
    RuntimeMessageBatchPayload,
    RuntimeMessagePayload,
)
from tests.support.fastapi import set_expected_api_token
from tests.support.live_server import LiveServer


class StubIngestionService:
    def __init__(self) -> None:
        self.commands = []

    async def ingest(self, command):
        self.commands.append(command)
        return IngestMessageBatchResult(
            batch_id=command.batch_id,
            chat_id=command.chat_id,
            created=True,
            message_count=len(command.messages),
        )


def test_accepts_valid_ordered_message_batch() -> None:
    service = StubIngestionService()
    app = create_app()
    set_expected_api_token(app, "runtime-token")
    app.dependency_overrides[get_message_batch_ingestion_service] = lambda: service
    payload = _payload()

    with LiveServer(app) as server:
        response = server.request(
            "POST",
            "/api/v1/agent-runtime/messages",
            json_body=payload,
            headers={
                "Authorization": "Bearer runtime-token",
                "Idempotency-Key": "conversation-batch-1",
            },
        )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert len(service.commands) == 1
    assert service.commands[0].idempotency_key == "conversation-batch-1"
    assert service.commands[0].chat_id == 900100
    assert len(service.commands[0].messages) == 2


def test_rejects_messages_that_are_not_in_strict_order() -> None:
    service = StubIngestionService()
    app = create_app()
    set_expected_api_token(app, "runtime-token")
    app.dependency_overrides[get_message_batch_ingestion_service] = lambda: service
    payload = _payload()
    payload["messages"].reverse()

    with LiveServer(app) as server:
        response = server.request(
            "POST",
            "/api/v1/agent-runtime/messages",
            json_body=payload,
            headers={
                "Authorization": "Bearer runtime-token",
                "Idempotency-Key": "conversation-batch-2",
            },
        )

    assert response.status_code == 422
    assert service.commands == []


def test_requires_idempotency_key() -> None:
    service = StubIngestionService()
    app = create_app()
    set_expected_api_token(app, "runtime-token")
    app.dependency_overrides[get_message_batch_ingestion_service] = lambda: service

    with LiveServer(app) as server:
        response = server.request(
            "POST",
            "/api/v1/agent-runtime/messages",
            json_body=_payload(),
            headers={"Authorization": "Bearer runtime-token"},
        )

    assert response.status_code == 422
    assert service.commands == []


def _payload() -> dict:
    return {
        "batch_id": str(uuid4()),
        "chat_id": 900100,
        "messages": [
            {
                "ingress_message_id": str(uuid4()),
                "telegram_user_id": 123456,
                "message_id": 10,
                "reply_message_id": None,
                "text": "first",
                "attachment": None,
            },
            {
                "ingress_message_id": str(uuid4()),
                "telegram_user_id": 123456,
                "message_id": 20,
                "reply_message_id": 10,
                "text": "second",
                "attachment": {
                    "ingress_attachment_id": str(uuid4()),
                    "type": "video",
                    "status": "processing",
                    "file_id": "video-file",
                    "file_unique_id": "video-unique",
                },
            },
        ],
    }


def test_ingress_client_submits_to_runtime_messages_endpoint() -> None:
    service = StubIngestionService()
    app = create_app()
    set_expected_api_token(app, "runtime-token")
    app.dependency_overrides[get_message_batch_ingestion_service] = lambda: service
    payload = RuntimeMessageBatchPayload(
        chat_id=900100,
        messages=(
            RuntimeMessagePayload(
                ingress_message_id=uuid4(),
                telegram_user_id=123456,
                message_id=10,
                text="through the ingress client",
            ),
        ),
    )

    with LiveServer(app) as server:
        AgentRuntimeClient(
            base_url=f"{server.base_url}/api/v1/agent-runtime",
            token="runtime-token",
            timeout_seconds=5,
        ).submit_message_batch(
            batch_id=uuid4(),
            idempotency_key="client-integration-batch",
            payload=payload,
        )

    assert len(service.commands) == 1
    assert service.commands[0].idempotency_key == "client-integration-batch"
