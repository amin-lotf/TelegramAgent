from telegram_agent.core.common.db.session_factory import create_async_session_factory
from telegram_agent.core.content_processing.common.settings import settings

AsyncSessionLocal = create_async_session_factory(settings.sqlalchemy_database_url)

