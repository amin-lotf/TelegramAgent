from telegram_agent.core.common.db.session_factory import create_sync_session_factory
from telegram_agent.core.gpu_execution.common.settings import settings


SyncSessionLocal = create_sync_session_factory(settings.sqlalchemy_database_url)
