from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.db.models.content_processing import (
    TranscriptSegment,
)
from telegram_agent.core.content_processing.services.dubbing_media import (
    DubbingAudioAssemblyService,
    DubbingSegmentPlanner,
)
from telegram_agent.core.content_processing.services.subtitle_preparation_service import (
    SubtitleSegment,
)


def test_segment_planner_merges_short_continuations_but_preserves_speaker_boundary() -> None:
    source = [
        _source(0, 0, 800, "Hello", "speaker-1"),
        _source(1, 950, 1500, "world.", "speaker-1"),
        _source(2, 1600, 2200, "New speaker", "speaker-2"),
    ]
    translated = [
        SubtitleSegment(start_ms=0, end_ms=800, text="Hola"),
        SubtitleSegment(start_ms=950, end_ms=1500, text="mundo."),
        SubtitleSegment(start_ms=1600, end_ms=2200, text="Nueva voz"),
    ]

    planned = DubbingSegmentPlanner().plan(
        source_segments=source, translated_segments=translated
    )

    assert len(planned) == 2
    assert planned[0].source_segment_indices == (0, 1)
    assert planned[0].source_text == "Hello world."
    assert planned[0].target_text == "Hola mundo."
    assert planned[1].source_segment_indices == (2,)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_audio_assembly_runs_real_ffmpeg_alignment_and_mix(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    residual = tmp_path / "residual.wav"
    clip = tmp_path / "clip.wav"
    _ffmpeg(
        "-f", "lavfi", "-i", "color=c=black:s=160x90:d=2:r=10",
        "-c:v", "mpeg4", str(video),
    )
    _ffmpeg(
        "-f", "lavfi", "-i", "sine=frequency=220:duration=2:sample_rate=48000",
        "-ac", "2", str(residual),
    )
    _ffmpeg(
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5:sample_rate=24000",
        str(clip),
    )
    plan = tmp_path / "plan.json"
    manifest = tmp_path / "tts.json"
    plan.write_text(
        json.dumps(
            {"segments": [{"index": 0, "start_ms": 500, "end_ms": 1000}]}
        ),
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps(
            {"segments": [{"index": 0, "tts_clip_path": str(clip)}]}
        ),
        encoding="utf-8",
    )
    service = DubbingAudioAssemblyService(
        settings.model_copy(
            update={
                "media_storage_root": str(tmp_path),
                "ffmpeg_timeout_seconds": 30,
            }
        )
    )

    output = service.assemble(
        job_id=uuid4(),
        video_path=video,
        residual_path=residual,
        plan_path=plan,
        tts_manifest_path=manifest,
    )

    assert output.is_file() and output.stat().st_size > 44
    duration = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert 1.9 <= float(duration.stdout.strip()) <= 2.1


def _ffmpeg(*arguments: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *arguments],
        capture_output=True,
        check=True,
    )


def _source(
    index: int, start_ms: int, end_ms: int, text: str, speaker: str
) -> TranscriptSegment:
    return TranscriptSegment(
        segment_index=index,
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        speaker=speaker,
    )
