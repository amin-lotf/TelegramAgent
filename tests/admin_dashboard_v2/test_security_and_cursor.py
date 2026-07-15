from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from telegram_agent.core.admin_dashboard_v2.common.exceptions import InvalidCursorError
from telegram_agent.core.admin_dashboard_v2.common.types import CursorPosition, MessageListFilters
from telegram_agent.core.admin_dashboard_v2.security.passwords import hash_password, verify_password
from telegram_agent.core.admin_dashboard_v2.services.cursors import CursorCodec
from telegram_agent.core.admin_dashboard_v2.services.redaction import sanitize_payload


def test_password_hash_round_trip() -> None:
    encoded = hash_password("correct horse", iterations=10_000, salt=b"fixed-test-salt")
    assert verify_password("correct horse", encoded)
    assert verify_password("correct horse", f"'{encoded}'")
    assert verify_password("correct horse", f'"{encoded}"')
    assert not verify_password("wrong", encoded)
    assert not verify_password("correct horse", "invalid")


def test_cursor_is_signed_and_bound_to_filters() -> None:
    codec = CursorCodec("x" * 32)
    filters = MessageListFilters(chat_id=10)
    position = CursorPosition(datetime.now(timezone.utc), uuid4())
    encoded = codec.encode(position, filters)
    assert codec.decode(encoded, filters) == position
    with pytest.raises(InvalidCursorError):
        codec.decode(encoded, MessageListFilters(chat_id=11))
    replacement = "A" if encoded[-1] != "A" else "B"
    with pytest.raises(InvalidCursorError):
        codec.decode(encoded[:-1] + replacement, filters)


def test_recursive_redaction_masks_sensitive_fields_and_limits_payload() -> None:
    result = sanitize_payload(
        {
            "authorization": "Bearer secret",
            "telegram_file_id": "1234567890abcdef",
            "local_path": "/private/media/voice.ogg",
            "last_error": (
                "request failed at https://bot:password@example.test and "
                "Authorization: Bearer abc.def.ghi"
            ),
            "nested": {"password": "never-show"},
        },
        maximum_bytes=10_000,
    )
    assert result["authorization"] == "<redacted>"
    assert result["telegram_file_id"] == "1234…cdef"
    assert result["local_path"] == "<masked>/voice.ogg"
    assert "password" not in result["last_error"]
    assert "abc.def.ghi" not in result["last_error"]
    assert result["nested"]["password"] == "<redacted>"
