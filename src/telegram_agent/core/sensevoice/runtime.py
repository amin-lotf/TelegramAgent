from __future__ import annotations

import asyncio
import importlib
import logging
import re
from pathlib import Path
from typing import Any

from fastapi.concurrency import run_in_threadpool

from telegram_agent.core.common.exceptions import (
    SenseVoiceBackendBusyError,
    SenseVoiceBackendUnavailableError,
)
from telegram_agent.core.sensevoice.common.results import ModelEmotionResult
from telegram_agent.core.sensevoice.common.settings import settings

logger = logging.getLogger(__name__)

# SenseVoice tag set (see FunAudioLLM/SenseVoice).
# Named emotions from the model vocabulary.
_EMOTION_TAGS = frozenset(
    {
        "HAPPY",
        "SAD",
        "ANGRY",
        "NEUTRAL",
        "FEARFUL",
        "DISGUSTED",
        "SURPRISED",
    }
)
# SenseVoice emits <|EMO_UNKNOWN|> when no confident emotion class is chosen.
_UNKNOWN_EMOTION_TAGS = frozenset(
    {
        "EMO_UNKNOWN",
        "UNKNOWN",
        "UNK",
    }
)
_EVENT_TAGS = frozenset(
    {
        "BGM",
        "Speech",
        "Applause",
        "Laughter",
        "Cry",
        "Sneeze",
        "Breath",
        "Cough",
    }
)
_LANGUAGE_TAGS = frozenset({"zh", "en", "yue", "ja", "ko", "nospeech"})
_ITN_TAGS = frozenset({"withitn", "woitn"})
_TAG_PATTERN = re.compile(r"<\|([^|>]+)\|>")


def _normalize_emotion_tag(tag: str) -> str | None:
    """Map a SenseVoice emotion-like tag to a stored label, or None if unrelated."""
    upper = tag.strip().upper()
    if not upper:
        return None
    # Accept both <|NEUTRAL|> and occasional <|EMO_NEUTRAL|>-style tags.
    if upper.startswith("EMO_"):
        upper = upper[4:]
    if upper in _EMOTION_TAGS:
        return upper
    if upper in _UNKNOWN_EMOTION_TAGS or upper == "UNKNOWN":
        return "UNKNOWN"
    return None


def parse_sensevoice_text(raw_text: str) -> ModelEmotionResult:
    """Parse SenseVoice special tags from model output text."""
    tags = [match.group(1).strip() for match in _TAG_PATTERN.finditer(raw_text or "")]
    emotion: str | None = None
    events: list[str] = []
    language: str | None = None

    for tag in tags:
        normalized = tag.strip()
        if not normalized:
            continue
        emotion_label = _normalize_emotion_tag(normalized)
        if emotion_label is not None:
            emotion = emotion_label
            continue
        upper = normalized.upper()
        if normalized in _EVENT_TAGS or upper.title() in _EVENT_TAGS:
            # Preserve canonical casing from _EVENT_TAGS when possible.
            canonical = next(
                (item for item in _EVENT_TAGS if item.lower() == normalized.lower()),
                normalized,
            )
            if canonical not in events:
                events.append(canonical)
            continue
        lower = normalized.lower()
        if lower in _LANGUAGE_TAGS and language is None:
            language = lower
            continue
        if lower in _ITN_TAGS:
            continue

    plain_text = _TAG_PATTERN.sub("", raw_text or "").strip() or None
    return ModelEmotionResult(
        emotion=emotion,
        events=tuple(events),
        language=language,
        text=plain_text,
    )


class SenseVoiceRuntime:
    def __init__(
        self,
        *,
        model_name: str,
        device: str,
        concurrency: int,
    ) -> None:
        if concurrency <= 0:
            raise ValueError("sensevoice_concurrency must be greater than zero")

        self._model_name = model_name
        self._device = device
        self._semaphore = asyncio.Semaphore(concurrency)
        self._capacity_lock = asyncio.Lock()

        funasr_module = importlib.import_module("funasr")
        auto_model_cls = funasr_module.AutoModel
        self._model = auto_model_cls(
            model=model_name,
            device=device,
            disable_update=True,
        )

        logger.info(
            "SenseVoice runtime loaded: model=%s device=%s concurrency=%s",
            model_name,
            device,
            concurrency,
        )

    @classmethod
    def from_settings(cls) -> "SenseVoiceRuntime":
        return cls(
            model_name=settings.sensevoice_model,
            device=settings.sensevoice_device,
            concurrency=settings.sensevoice_concurrency,
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    async def extract_emotion(
        self,
        *,
        audio_path: Path,
        language: str | None = None,
    ) -> ModelEmotionResult:
        await self._acquire_capacity_slot()
        try:
            return await run_in_threadpool(
                self._extract_emotion_sync,
                audio_path,
                language,
            )
        except SenseVoiceBackendBusyError:
            raise
        except Exception as exc:
            raise SenseVoiceBackendUnavailableError(
                "SenseVoice emotion extraction failed"
            ) from exc
        finally:
            self._semaphore.release()

    async def _acquire_capacity_slot(self) -> None:
        async with self._capacity_lock:
            if self._semaphore.locked():
                raise SenseVoiceBackendBusyError()
            await self._semaphore.acquire()

    def _extract_emotion_sync(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> ModelEmotionResult:
        generate_kwargs: dict[str, Any] = {
            "input": str(audio_path),
            "use_itn": True,
            "batch_size_s": 60,
            "ban_emo_unk" : True
        }
        if language:
            generate_kwargs["language"] = language
        else:
            generate_kwargs["language"] = "auto"

        results = self._model.generate(**generate_kwargs)
        if not results:
            return ModelEmotionResult(emotion=None, events=(), language=None, text=None)

        first = results[0]
        if not isinstance(first, dict):
            raise SenseVoiceBackendUnavailableError(
                "SenseVoice returned an unexpected response payload"
            )

        raw_text = first.get("text")
        if raw_text is None:
            raw_text = ""
        return parse_sensevoice_text(str(raw_text))
