from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from telegram_agent.core.content_processing.downloaders.mux import MuxService


def _write_inputs(tmp_path: Path, *, subtitle_text: str) -> tuple[Path, Path, Path]:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.ogg"
    subtitle = tmp_path / "subs.srt"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n" + subtitle_text + "\n",
        encoding="utf-8",
    )
    return video, audio, subtitle


def _stub_mux(service: MuxService, monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr(
        "telegram_agent.core.content_processing.downloaders.mux.shutil.which",
        lambda _: "/usr/bin/ffmpeg",
    )
    monkeypatch.setattr(
        service, "_probe_video_size", lambda *args, **kwargs: (1920, 1080)
    )

    original_write = service._write_styled_ass

    def write_and_capture(**kwargs):
        original_write(**kwargs)
        captured["ass"] = kwargs["ass_path"].read_text(encoding="utf-8")

    monkeypatch.setattr(service, "_write_styled_ass", write_and_capture)

    def fake_run(command, *, cancellation_requested=None):
        captured["command"] = command
        Path(command[-1]).write_bytes(b"muxed-mp4")

    monkeypatch.setattr(service, "_run_ffmpeg", fake_run)
    return captured


def test_mux_burns_in_ass_and_writes_mp4(tmp_path: Path, monkeypatch) -> None:
    video, audio, subtitle = _write_inputs(tmp_path, subtitle_text="Hello world")
    service = MuxService(
        storage_root=tmp_path,
        ffmpeg_binary="ffmpeg",
        timeout_seconds=30,
    )
    captured = _stub_mux(service, monkeypatch)
    job_id = uuid4()

    result = Path(
        service.mux(
            job_id=job_id,
            video_path=str(video),
            audio_path=str(audio),
            subtitle_path=str(subtitle),
        )
    )

    assert result.suffix == ".mp4"
    assert result.name == f"v{job_id.hex[:10]}.mp4"
    assert result.is_file()
    command = captured["command"]
    assert command[command.index("-f") + 1] == "mp4"
    assert "libx264" in command
    assert "yuv420p" in command
    assert "+faststart" in command
    assert "veryfast" in command
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "ass=" in filter_complex
    assert "matroska" not in command
    assert "copy" not in command
    assert "-c:s" not in command
    assert "Style: Default,Noto Sans," in captured["ass"]
    assert "WrapStyle: 1" in captured["ass"]
    assert "2,60,60,40,1" not in captured["ass"]
    assert "2,120,120,54,1" in captured["ass"]


def test_mux_uses_arabic_font_for_persian_subtitles(
    tmp_path: Path, monkeypatch
) -> None:
    video, audio, subtitle = _write_inputs(tmp_path, subtitle_text="سلام دنیا")
    service = MuxService(
        storage_root=tmp_path,
        ffmpeg_binary="ffmpeg",
        timeout_seconds=30,
    )
    captured = _stub_mux(service, monkeypatch)

    service.mux(
        job_id=uuid4(),
        video_path=str(video),
        audio_path=str(audio),
        subtitle_path=str(subtitle),
    )

    assert "Style: Default,Noto Naskh Arabic," in captured["ass"]


def test_mux_uses_cjk_font_for_chinese_subtitles(
    tmp_path: Path, monkeypatch
) -> None:
    video, audio, subtitle = _write_inputs(tmp_path, subtitle_text="你好世界")
    service = MuxService(
        storage_root=tmp_path,
        ffmpeg_binary="ffmpeg",
        timeout_seconds=30,
    )
    captured = _stub_mux(service, monkeypatch)

    service.mux(
        job_id=uuid4(),
        video_path=str(video),
        audio_path=str(audio),
        subtitle_path=str(subtitle),
        subtitle_language="chinese",
    )

    assert "Style: Default,Noto Sans CJK SC," in captured["ass"]


def test_mux_uses_traditional_cjk_font_for_zh_hant(
    tmp_path: Path, monkeypatch
) -> None:
    video, audio, subtitle = _write_inputs(tmp_path, subtitle_text="繁體中文")
    service = MuxService(
        storage_root=tmp_path,
        ffmpeg_binary="ffmpeg",
        timeout_seconds=30,
    )
    captured = _stub_mux(service, monkeypatch)

    service.mux(
        job_id=uuid4(),
        video_path=str(video),
        audio_path=str(audio),
        subtitle_path=str(subtitle),
        subtitle_language="zh-tw",
    )

    assert "Style: Default,Noto Sans CJK TC," in captured["ass"]


def test_mux_uses_japanese_font_for_kana(tmp_path: Path, monkeypatch) -> None:
    video, audio, subtitle = _write_inputs(tmp_path, subtitle_text="こんにちは")
    service = MuxService(
        storage_root=tmp_path,
        ffmpeg_binary="ffmpeg",
        timeout_seconds=30,
    )
    captured = _stub_mux(service, monkeypatch)

    service.mux(
        job_id=uuid4(),
        video_path=str(video),
        audio_path=str(audio),
        subtitle_path=str(subtitle),
    )

    assert "Style: Default,Noto Sans CJK JP," in captured["ass"]
