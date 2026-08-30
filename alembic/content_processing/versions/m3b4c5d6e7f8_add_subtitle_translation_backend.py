"""Add subtitle translation backend and model cache identity.

Revision ID: m3b4c5d6e7f8
Revises: l2a3b4c5d6e7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "l2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subtitle_translations",
        sa.Column("backend", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE subtitle_translations
            SET backend = CASE
              WHEN model_name ILIKE '%madlad%' THEN 'local'
              WHEN model_name IS NOT NULL AND btrim(model_name) <> '' THEN 'openai'
              ELSE 'local'
            END
            WHERE backend IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE subtitle_translations
            SET model_name = CASE
              WHEN backend = 'local' THEN 'google/madlad400-3b-mt'
              ELSE 'gpt-5.4'
            END
            WHERE model_name IS NULL OR btrim(model_name) = ''
            """
        )
    )
    op.alter_column(
        "subtitle_translations",
        "backend",
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.alter_column(
        "subtitle_translations",
        "model_name",
        existing_type=sa.String(length=128),
        nullable=False,
    )
    op.drop_constraint(
        "uq_subtitle_translations_job_language",
        "subtitle_translations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_subtitle_translations_job_language_backend_model",
        "subtitle_translations",
        ["job_id", "target_language", "backend", "model_name"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_subtitle_translations_job_language_backend_model",
        "subtitle_translations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_subtitle_translations_job_language",
        "subtitle_translations",
        ["job_id", "target_language"],
    )
    op.alter_column(
        "subtitle_translations",
        "model_name",
        existing_type=sa.String(length=128),
        nullable=True,
    )
    op.drop_column("subtitle_translations", "backend")
