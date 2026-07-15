from __future__ import annotations

from datetime import datetime
from uuid import UUID

from telegram_agent.core.admin_dashboard.api.v1.messages.schemas import MessageListQuery


def test_empty_form_strings_are_none() -> None:
    query = MessageListQuery(
        page=1,
        page_size="",
        filter_ingress_message_id="",
        chat_id="",
        message_id="",
        telegram_user_id="",
        conversation_status="",
        attachment_status="",
        has_attachment="",
        failed_only="",
        created_from="",
        created_to="",
        q="",
    )
    assert query.filter_ingress_message_id is None
    assert query.chat_id is None
    assert query.message_id is None
    assert query.telegram_user_id is None
    assert query.conversation_status is None
    assert query.attachment_status is None
    assert query.has_attachment is None
    assert query.failed_only is False
    assert query.created_from is None
    assert query.created_to is None
    assert query.q is None
    assert query.page_size is None


def test_populated_filters_parse() -> None:
    query = MessageListQuery(
        page=2,
        page_size="25",
        filter_ingress_message_id="01234567-89ab-cdef-0123-456789abcdef",
        chat_id="42",
        message_id="7",
        telegram_user_id="99",
        conversation_status="pending",
        attachment_status="ready",
        has_attachment="true",
        failed_only="on",
        created_from="2026-07-15T10:30",
        created_to="2026-07-15T12:00:00",
        q=" hello ",
    )
    assert query.page == 2
    assert query.page_size == 25
    assert query.filter_ingress_message_id == UUID("01234567-89ab-cdef-0123-456789abcdef")
    assert query.chat_id == 42
    assert query.message_id == 7
    assert query.telegram_user_id == 99
    assert query.conversation_status == "pending"
    assert query.attachment_status == "ready"
    assert query.has_attachment is True
    assert query.failed_only is True
    assert isinstance(query.created_from, datetime)
    assert isinstance(query.created_to, datetime)
    assert query.q == "hello"
