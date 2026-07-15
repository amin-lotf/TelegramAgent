from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from uuid import UUID

from telegram_agent.core.admin_dashboard_v2.common.exceptions import InvalidCursorError
from telegram_agent.core.admin_dashboard_v2.common.types import (
    CursorPosition,
    MessageListFilters,
)


class CursorCodec:
    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")

    def encode(self, position: CursorPosition, filters: MessageListFilters) -> str:
        payload = {
            "created_at": position.created_at.isoformat(),
            "message_id": str(position.message_id),
            "filters": self._filter_digest(filters),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._secret, raw, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature + raw).decode("ascii").rstrip("=")

    def decode(self, value: str, filters: MessageListFilters) -> CursorPosition:
        try:
            padded = value + "=" * (-len(value) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
            signature, raw = decoded[:32], decoded[32:]
            expected = hmac.new(self._secret, raw, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise InvalidCursorError("Pagination cursor signature is invalid")
            payload = json.loads(raw)
            if payload["filters"] != self._filter_digest(filters):
                raise InvalidCursorError("Pagination cursor does not match current filters")
            return CursorPosition(
                created_at=datetime.fromisoformat(payload["created_at"]),
                message_id=UUID(payload["message_id"]),
            )
        except InvalidCursorError:
            raise
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise InvalidCursorError("Pagination cursor is malformed") from exc

    @staticmethod
    def _filter_digest(filters: MessageListFilters) -> str:
        raw = json.dumps(
            filters.fingerprint_values(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
