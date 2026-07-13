from __future__ import annotations

from uuid import UUID

import httpx
from pydantic import ValidationError

from telegram_agent.core.common.exceptions import (
    AgentRuntimeBadResponseError,
    AgentRuntimeUnavailableError,
)
from telegram_agent.core.telegram_ingress.clients.schemas import AgentRuntimeAcceptedResponse
from telegram_agent.core.telegram_ingress.common.commands import RuntimeMessageBatchPayload


class AgentRuntimeClient:
    def __init__(self, *, base_url: str, token: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = httpx.Timeout(timeout_seconds)

    def submit_message_batch(
        self,
        *,
        batch_id: UUID,
        idempotency_key: str,
        payload: RuntimeMessageBatchPayload,
    ) -> None:
        request_payload = {
            "batch_id": str(batch_id),
            **payload.model_dump(mode="json"),
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/messages",
                    json=request_payload,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Idempotency-Key": idempotency_key,
                    },
                )
            response.raise_for_status()
            AgentRuntimeAcceptedResponse.model_validate(response.json())
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {408, 429} or 500 <= status_code < 600:
                raise AgentRuntimeUnavailableError(
                    "Agent runtime service is unavailable"
                ) from exc
            raise AgentRuntimeBadResponseError(
                f"Agent runtime rejected the message batch with status {status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise AgentRuntimeUnavailableError(
                "Agent runtime service is unavailable"
            ) from exc
        except (ValueError, ValidationError, TypeError) as exc:
            raise AgentRuntimeUnavailableError(
                "Agent runtime returned an invalid acceptance response"
            ) from exc
