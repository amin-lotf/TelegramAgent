from __future__ import annotations

from hashlib import blake2b


def secondary_task_scope_lock_key(*, telegram_user_id: int, chat_id: int) -> int:
    """Return a stable signed bigint for a PostgreSQL advisory transaction lock."""
    scope = f"secondary-task-cancellation:{telegram_user_id}:{chat_id}".encode()
    digest = blake2b(scope, digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)
