from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, MetaData, String, Table


metadata = MetaData()

telegram_users = Table(
    "telegram_users", metadata,
    Column("id", Integer, primary_key=True),
    Column("telegram_user_id", BigInteger, nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("username", String(255)),
    Column("first_name", String(255)),
    Column("last_name", String(255)),
    Column("is_bot", Boolean, nullable=False),
    Column("language_code", String(20)),
    Column("is_active", Boolean, nullable=False),
    Column("verified_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
)
