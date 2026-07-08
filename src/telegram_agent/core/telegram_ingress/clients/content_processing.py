import logging
import httpx
from pydantic import  ValidationError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
    before_sleep_log,
)

from telegram_agent.core.common.exceptions import (
    ContentProcessingBadResponseError,
    ContentProcessingUnavailableError,
)
from telegram_agent.core.telegram_ingress.clients.schemas import ProcessAttachmentResponse
from telegram_agent.core.telegram_ingress.common.commands import ProcessAttachmentCommand

logger = logging.getLogger(__name__)





def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.RequestError):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code in {408, 429, 500, 502, 503, 504}

    return False


class ContentProcessingClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token

    async def process_attachment(self, command: ProcessAttachmentCommand) -> None:
        try:
            data = await self._request_process_attachment(command)
            ProcessAttachmentResponse.model_validate(data)

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code

            if status_code in {408, 429} or 500 <= status_code < 600:
                raise ContentProcessingUnavailableError(
                    "Content processing service is unavailable"
                ) from exc

            raise ContentProcessingBadResponseError(
                f"Content processing rejected the request with status {status_code}"
            ) from exc

        except httpx.RequestError as exc:
            raise ContentProcessingUnavailableError(
                "Content processing service is unavailable"
            ) from exc

        except (ValueError, ValidationError, TypeError) as exc:
            raise ContentProcessingBadResponseError(
                "Invalid response from content processing service"
            ) from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, min=0.2, max=2),
        retry=retry_if_exception(_should_retry),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def _request_process_attachment(
        self,
        command: ProcessAttachmentCommand,
    ) -> dict:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(
                f"{self._base_url}/attachments",
                json=command.model_dump(mode="json"),
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Idempotency-Key": command.idempotency_key,
                },
            )

            response.raise_for_status()
            return response.json()