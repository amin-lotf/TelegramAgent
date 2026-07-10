from contextlib import AbstractAsyncContextManager
from typing import Callable

from telegram_agent.core.content_processing.db.uow.async_content_processing import \
    AsyncSqlAlchemyContentProcessingUnitOfWork


class AsyncTelegramJobService:
    def __init__(
            self,
            uow_factory: Callable[
                [],
                AbstractAsyncContextManager[AsyncSqlAlchemyContentProcessingUnitOfWork],
            ],
    ):
        self._uow_factory = uow_factory

