from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import defaultdict, deque
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Final

from web_analyzer.core.common.settings import settings

RESET = "\033[0m"

LEVEL_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;31m",
}

# NODE_COLOR = "\033[35m"   # purple
# PHASE_COLOR = "\033[34m"  # blue

_BUFFER_SIZE: Final[int] = 200
_QUEUE_SIZE: Final[int] = 200


@dataclass(frozen=True, slots=True)
class LiveLogEvent:
    timestamp: str
    level: str
    logger_name: str
    message: str
    chat_id: str
    node: str | None = None
    phase: str | None = None


@dataclass(slots=True)
class _LiveLogSubscriber:
    queue: asyncio.Queue[LiveLogEvent]
    loop: asyncio.AbstractEventLoop

class LiveLogBroker:
    def __init__(self, *, buffer_size: int = _BUFFER_SIZE, queue_size: int = _QUEUE_SIZE) -> None:
        self._buffer_size = buffer_size
        self._queue_size = queue_size
        self._buffer_by_chat_id: dict[str, deque[LiveLogEvent]] = defaultdict(
            lambda: deque(maxlen=self._buffer_size),
        )
        self._subscribers_by_chat_id: dict[str, list[_LiveLogSubscriber]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(
        self,
        chat_id: str,
    ) -> tuple[_LiveLogSubscriber, list[LiveLogEvent]]:
        normalized_chat_id = str(chat_id).strip()
        subscriber = _LiveLogSubscriber(
            queue=asyncio.Queue(maxsize=self._queue_size),
            loop=asyncio.get_running_loop(),
        )

        with self._lock:
            self._subscribers_by_chat_id[normalized_chat_id].append(subscriber)
            backlog = list(self._buffer_by_chat_id.get(normalized_chat_id, ()))

        return subscriber, backlog

    def unsubscribe(self, chat_id: str, subscriber: _LiveLogSubscriber) -> None:
        normalized_chat_id = str(chat_id).strip()
        with self._lock:
            subscribers = self._subscribers_by_chat_id.get(normalized_chat_id)
            if not subscribers:
                return
            self._subscribers_by_chat_id[normalized_chat_id] = [
                item for item in subscribers if item is not subscriber
            ]
            if not self._subscribers_by_chat_id[normalized_chat_id]:
                self._subscribers_by_chat_id.pop(normalized_chat_id, None)

    def publish(self, event: LiveLogEvent) -> None:
        normalized_chat_id = str(event.chat_id).strip()
        if not normalized_chat_id or normalized_chat_id == "-":
            return

        with self._lock:
            self._buffer_by_chat_id[normalized_chat_id].append(event)
            subscribers = list(self._subscribers_by_chat_id.get(normalized_chat_id, ()))

        for subscriber in subscribers:
            try:
                subscriber.loop.call_soon_threadsafe(
                    self._push_event,
                    subscriber.queue,
                    event,
                )
            except RuntimeError:
                continue

    @staticmethod
    def _push_event(queue: asyncio.Queue[LiveLogEvent], event: LiveLogEvent) -> None:
        if queue.full():
            with suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        with suppress(asyncio.QueueFull):
            queue.put_nowait(event)


_live_log_broker = LiveLogBroker()
_live_log_persistence_callback: Callable[[LiveLogEvent], None] | None = None
_live_log_persistence_lock = threading.Lock()


def get_live_log_broker() -> LiveLogBroker:
    return _live_log_broker


def configure_live_log_persistence(
    callback: Callable[[LiveLogEvent], None] | None,
) -> None:
    global _live_log_persistence_callback

    with _live_log_persistence_lock:
        _live_log_persistence_callback = callback


def clear_live_log_persistence() -> None:
    configure_live_log_persistence(None)


def _get_live_log_persistence_callback() -> Callable[[LiveLogEvent], None] | None:
    with _live_log_persistence_lock:
        return _live_log_persistence_callback


def serialize_live_log_event(event: LiveLogEvent) -> dict[str, Any]:
    return {
        "timestamp": event.timestamp,
        "level": event.level,
        "logger_name": event.logger_name,
        "message": event.message,
        "chat_id": event.chat_id,
        "node": event.node,
        "phase": event.phase,
    }


def _normalize_log_field(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    return text


class LiveLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            chat_id = _normalize_log_field(getattr(record, "chat_id", None))
            if not chat_id:
                return

            level = str(record.levelname or "INFO").strip().lower()
            if level not in {"debug", "info", "warning", "error", "critical"}:
                level = "info"

            event = LiveLogEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                level=level,
                logger_name=record.name,
                message=record.getMessage(),
                chat_id=chat_id,
                node=_normalize_log_field(getattr(record, "node", None)),
                phase=_normalize_log_field(getattr(record, "phase", None)),
            )
            get_live_log_broker().publish(event)

            callback = _get_live_log_persistence_callback()
            if callback is not None:
                callback(event)
        except Exception:
            self.handleError(record)


class AgentFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # defaults
        for key in ("chat_id", "node", "phase"):
            if not hasattr(record, key):
                setattr(record, key, "-")

        # --- color level ---
        original_levelname = record.levelname
        level_color = LEVEL_COLORS.get(original_levelname, "")
        if level_color:
            record.levelname = f"{level_color}{original_levelname}:{RESET}"

        # --- color node & phase VALUES only ---
        original_node = record.node
        original_phase = record.phase
        if level_color:
            record.node = f"{level_color}{original_node}{RESET}"
            record.phase = f"{level_color}{original_phase}{RESET}"

        try:
            return super().format(record)
        finally:
            # restore originals (important)
            record.levelname = original_levelname
            record.node = original_node
            record.phase = original_phase


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", settings.LOG_LEVEL).upper()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(
        AgentFormatter(
            "%(levelname)-18s %(asctime)s  "
            "[%(name)s] chat_id=%(chat_id)s "
            "node=%(node)s phase=%(phase)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(stream_handler)
    root.addHandler(LiveLogHandler())
    logging.getLogger("fatolai_chatbot").setLevel(logging.DEBUG)

    for noisy_logger in (
            "httpcore",
            "httpx",
            "openai",
            "urllib3",
            "asyncio",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
