from telegram_agent.core.agent_runtime.common.settings import settings
from telegram_agent.core.common.db.session_factory import create_async_session_factory

AsyncSessionLocal = create_async_session_factory(settings.sqlalchemy_database_url)

