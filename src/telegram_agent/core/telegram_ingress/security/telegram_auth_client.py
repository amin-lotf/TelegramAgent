import logging

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from telegram_agent.core.common.exceptions import TelegramAuthUnavailableError, \
    TelegramAuthBadResponseError, TelegramUserUnauthorizedError

logger = logging.getLogger(__name__)




class TelegramAuthClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url
        self._token = token

    async def check_user(self, telegram_user_id: int) -> None:
        try:
            data = await self._request_check_user(telegram_user_id)

        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise TelegramAuthUnavailableError("Telegram auth service is unavailable") from exc

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code

            if 500 <= status_code < 600:
                raise TelegramAuthUnavailableError("Telegram auth service failed") from exc

            raise TelegramAuthBadResponseError("Unexpected response from telegram auth service") from exc

        except (ValueError, KeyError, TypeError) as exc:
            raise TelegramAuthBadResponseError("Invalid response from telegram auth service") from exc

        verified = data["verified"]

        if not verified:
            raise TelegramUserUnauthorizedError("Unauthorized")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, min=0.2, max=2),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def _request_check_user(self, telegram_user_id: int) -> dict:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(
                f"{self._base_url}/check",
                json={"telegram_user_id": telegram_user_id},
                headers={"Authorization": f"Bearer {self._token}"},
            )

            response.raise_for_status()
            return response.json()