from telegram_agent.core.admin_dashboard.db.mappings import content_processing as mappings
from telegram_agent.core.content_processing.db.models.content_processing import (
    DownloadRequest,
    SubtitleTranslation,
    TranslationBatch,
)


def test_workflow_read_mappings_match_owned_content_schema() -> None:
    pairs = (
        (mappings.download_requests, DownloadRequest.__table__),
        (mappings.subtitle_translations, SubtitleTranslation.__table__),
        (mappings.translation_batches, TranslationBatch.__table__),
    )
    for dashboard_table, owned_table in pairs:
        assert set(dashboard_table.c.keys()) <= set(owned_table.c.keys())
