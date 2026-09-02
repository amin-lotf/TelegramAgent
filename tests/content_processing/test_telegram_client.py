from __future__ import annotations

from pathlib import Path

import httpx

from telegram_agent.core.content_processing.clients.telegram_client import TelegramClient
from telegram_agent.core.content_processing.common.settings import settings


def test_send_video_uses_streaming_mp4(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"media-bytes")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        captured["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

    client = TelegramClient(
        settings.model_copy(
            update={
                "telegram_bot_token": "123:token",
                "telegram_api_base_url": "http://telegram.test",
            }
        ),
        transport=httpx.MockTransport(handler),
    )
    result = client.send_video(chat_id=42, file_path=str(video), caption="done")

    assert result.message_id == 9
    assert str(captured["url"]).endswith("/bot123:token/sendVideo")
    body = captured["body"]
    assert isinstance(body, bytes)
    assert b"supports_streaming" in body
    assert b"true" in body
    assert b"video/mp4" in body
    assert b"clip.mp4" in body
    assert b"done" in body
