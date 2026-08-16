"""scope agent messages to individual requests

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a7
Create Date: 2026-08-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c3d4e5f6a7b9"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_agent_messages_group_id_role",
        "agent_messages",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_agent_messages_ingress_message_id_role",
        "agent_messages",
        ["ingress_message_id", "role"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_agent_messages_ingress_message_id_role",
        "agent_messages",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_agent_messages_group_id_role",
        "agent_messages",
        ["group_id", "role"],
    )
