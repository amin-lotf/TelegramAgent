import hashlib
import hmac

import logging

from telegram_agent.core.telegram_auth.common.settings import settings

logger = logging.getLogger(__name__)

def hash_password(password: str) -> str:
    return hmac.new(
        settings.bot_verify_secret.encode('utf-8'),
        password.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def password_matches(password: str) -> bool:
    provided_hash = hash_password(password)
    logger.debug(f"Provided hash: {provided_hash}")
    return hmac.compare_digest(provided_hash, settings.bot_verify_hash)
