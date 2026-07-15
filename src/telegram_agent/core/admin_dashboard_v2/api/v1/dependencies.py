from fastapi import Request

from telegram_agent.core.admin_dashboard_v2.services.message_listing import MessageListingService
from telegram_agent.core.admin_dashboard_v2.services.message_trace import MessageTraceQueryService


def get_message_listing_service(request: Request) -> MessageListingService:
    return request.app.state.message_listing_service


def get_message_trace_service(request: Request) -> MessageTraceQueryService:
    return request.app.state.message_trace_service
