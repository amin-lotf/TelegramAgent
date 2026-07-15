from telegram_agent.core.admin_dashboard.services.redact import mask_path, text_preview


def test_mask_path_enabled() -> None:
    masked = mask_path(
        "/app/media/job-id/asset-id.ogg",
        enabled=True,
    )
    assert masked is not None
    assert masked.endswith("asset-id.ogg")
    assert not masked.startswith("/app/media")


def test_mask_path_disabled() -> None:
    path = "/app/media/job-id/asset-id.ogg"
    assert mask_path(path, enabled=False) == path


def test_text_preview_truncates() -> None:
    preview = text_preview("a" * 200, max_len=20)
    assert len(preview) <= 20
