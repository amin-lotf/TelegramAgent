"""Drop unused chunk/embedding tables and segment emotion columns.

Revision ID: k1f2a3b4c5d6
Revises: j0e1f2a3b4c5
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "j0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE jobs
            SET status = 'transcribed', updated_at = NOW()
            WHERE status IN (
                'emotion_extracting',
                'emotion_extracted',
                'chunking',
                'chunked',
                'embedding',
                'embedded'
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM outbox_events
            WHERE event_type IN (
                'content_processing.transcript.ready_for_emotion_extraction',
                'content_processing.transcript.ready_for_chunking',
                'content_processing.chunks.ready_for_embedding'
            )
            """
        )
    )
    op.drop_index(
        "ix_chunk_embeddings_job_id_created",
        table_name="chunk_embeddings",
    )
    op.drop_index(op.f("ix_chunk_embeddings_job_id"), table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")
    op.drop_index("ix_content_chunks_job_type", table_name="content_chunks")
    op.drop_index(op.f("ix_content_chunks_job_id"), table_name="content_chunks")
    op.drop_table("content_chunks")
    op.drop_column("transcript_segments", "audio_events")
    op.drop_column("transcript_segments", "emotion")
    op.execute(sa.text("DROP EXTENSION IF EXISTS vector"))


def downgrade() -> None:
    raise RuntimeError("Irreversible cleanup of unused chunk/emotion schema")
