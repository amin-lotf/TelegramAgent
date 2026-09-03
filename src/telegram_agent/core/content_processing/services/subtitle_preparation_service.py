from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from telegram_agent.core.common.exceptions import (
    PermanentContentProcessingError,
    StorageError,
)
from telegram_agent.core.content_processing.common.settings import Settings
from telegram_agent.core.content_processing.db.models.content_processing import (
    TranscriptSegment,
)

# Industry-aligned defaults for mobile soft subtitles (BBC / Netflix-style).
# - BBC: ~37 Latin chars/line, max 2 lines
# - Netflix CJK: ~13–16 glyphs/line (wide characters count as 2 columns)
# - Common reading speed target: ~15–20 characters/second
# Budget is display columns, not raw strlen, so CJK stays inside the frame.
_MAX_CHARS_PER_LINE = 37
_MAX_LINES = 2
_MAX_CHARS_PER_CUE = _MAX_CHARS_PER_LINE * _MAX_LINES
_MIN_DURATION_MS = 1_000
_MAX_DURATION_MS = 7_000
_TARGET_CPS = 17.0  # characters per second
_MIN_GAP_MS = 80

# SRT players treat cue text as LTR. Neutral marks (. ! ? ؟) at the end of a
# Persian line then visually jump to the start. Force an RTL run per text line.
_ARABIC_LETTER_RE = re.compile(r"[\u0600-\u06FF]")
_BIDI_CONTROL_RE = re.compile(r"[\u200E\u200F\u061C\u202A-\u202E\u2066-\u2069]")
_PERSIAN_PUNCTUATION = str.maketrans({
    ",": "\u060C",
    ";": "\u061B",
    "?": "\u061F",
})
_RLE = "\u202B"
_PDF = "\u202C"
_ALM = "\u061C"


def _char_display_width(char: str) -> int:
    if unicodedata.combining(char) or unicodedata.category(char) in {"Mn", "Me", "Cf"}:
        return 0
    if unicodedata.east_asian_width(char) in {"W", "F", "A"}:
        return 2
    return 1


def _display_width(text: str) -> int:
    """Visible columns: CJK/kana/hangul/fullwidth count as 2, Latin as 1."""
    return sum(_char_display_width(char) for char in text)


def _wrap_tokens(text: str) -> list[str]:
    """Latin words stay intact; wide-script glyphs wrap per character."""
    tokens: list[str] = []
    buffer: list[str] = []
    for char in text:
        if char.isspace():
            if buffer:
                tokens.append("".join(buffer))
                buffer = []
            continue
        if _char_display_width(char) >= 2:
            if buffer:
                tokens.append("".join(buffer))
                buffer = []
            tokens.append(char)
        else:
            buffer.append(char)
    if buffer:
        tokens.append("".join(buffer))
    return tokens


def _join_token(current: str, token: str) -> str:
    if not current:
        return token
    prev = current[-1]
    first = token[0]
    if _char_display_width(prev) >= 2 and _char_display_width(first) >= 2:
        return current + token
    if _char_display_width(first) >= 2:
        return f"{current} {token}"
    if _char_display_width(prev) >= 2:
        return current + token
    return f"{current} {token}"


def _split_by_display_width(text: str, max_width: int) -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    width = 0
    for char in text:
        char_width = _char_display_width(char)
        if current and width + char_width > max_width:
            pieces.append("".join(current))
            current = [char]
            width = char_width
        else:
            current.append(char)
            width += char_width
    if current:
        pieces.append("".join(current))
    return pieces


def _format_rtl_srt_line(line: str) -> str:
    """Keep terminal punctuation attached to a Persian/Arabic SRT line."""
    if not _ARABIC_LETTER_RE.search(line):
        return line
    text = _BIDI_CONTROL_RE.sub("", line)
    text = text.translate(_PERSIAN_PUNCTUATION)
    return f"{_RLE}{text}{_ALM}{_PDF}"


@dataclass(frozen=True)
class SubtitleSegment:
    start_ms: int
    end_ms: int
    text: str


class SubtitlePreparationService:
    """Normalize transcript segments into a clean, readable subtitle file.

    Whisper segments are often one long sentence (90–150+ chars). Mobile players
    render that as a large block. This service reflows text into short cues
    before writing SRT (later converted to styled ASS and burned into MP4).

    This service is deterministic and never calls an LLM. Callers must pass
    already-translated (or original) segments. ``target_language`` is retained
    for metadata/future formatting variants only.
    """

    def __init__(
        self,
        *,
        storage_root: Path,
        max_chars_per_line: int = _MAX_CHARS_PER_LINE,
        max_lines: int = _MAX_LINES,
        min_duration_ms: int = _MIN_DURATION_MS,
        max_duration_ms: int = _MAX_DURATION_MS,
        target_cps: float = _TARGET_CPS,
    ) -> None:
        self._storage_root = storage_root.expanduser().resolve()
        self._max_chars_per_line = max(12, max_chars_per_line)
        self._max_lines = max(1, max_lines)
        self._max_chars_per_cue = self._max_chars_per_line * self._max_lines
        self._min_duration_ms = max(400, min_duration_ms)
        self._max_duration_ms = max(self._min_duration_ms, max_duration_ms)
        self._target_cps = max(8.0, target_cps)

    @classmethod
    def from_settings(cls, settings: Settings) -> "SubtitlePreparationService":
        return cls(storage_root=Path(settings.media_storage_root))

    def prepare(
        self,
        *,
        job_id: UUID,
        segments: list[TranscriptSegment] | list[SubtitleSegment],
        target_language: str | None,
    ) -> str:
        # target_language is unused by deterministic reflow/formatting.
        _ = target_language

        if not segments:
            raise PermanentContentProcessingError(
                "Cannot prepare subtitles without transcript segments"
            )

        output_path = self._subtitle_path(job_id)
        self._create_parent_directory(output_path)
        temporary_path = output_path.with_name(f".{output_path.name}.part")

        try:
            cues = self._reflow_segments(segments)
            content = self._render_srt(cues)
            temporary_path.write_text(content, encoding="utf-8")
            if temporary_path.stat().st_size <= 0:
                raise PermanentContentProcessingError(
                    "Subtitle preparation produced an empty file"
                )
            temporary_path.replace(output_path)
        except PermanentContentProcessingError:
            temporary_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise StorageError("Unable to write subtitle file") from exc
        finally:
            temporary_path.unlink(missing_ok=True)

        return str(output_path)

    def _subtitle_path(self, job_id: UUID) -> Path:
        path = (self._storage_root / str(job_id) / "subtitles.srt").resolve()
        try:
            path.relative_to(self._storage_root)
        except ValueError as exc:
            raise StorageError("Resolved subtitle path is outside storage root") from exc
        return path

    def _create_parent_directory(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError("Unable to create subtitle storage directory") from exc

    def _reflow_segments(
        self,
        segments: list[TranscriptSegment] | list[SubtitleSegment],
    ) -> list[SubtitleSegment]:
        cues: list[SubtitleSegment] = []
        for segment in segments:
            start_ms = max(0, int(segment.start_ms))
            end_ms = max(start_ms, int(segment.end_ms))
            text = " ".join((segment.text or "").split())
            if not text:
                continue
            cues.extend(self._split_segment(start_ms=start_ms, end_ms=end_ms, text=text))

        if not cues:
            raise PermanentContentProcessingError(
                "Cannot prepare subtitles: all transcript segments are empty"
            )
        return self._enforce_timing_gaps(cues)

    def _split_segment(
        self,
        *,
        start_ms: int,
        end_ms: int,
        text: str,
    ) -> list[SubtitleSegment]:
        chunks = self._chunk_text(text)
        if len(chunks) == 1:
            duration = max(end_ms - start_ms, self._min_duration_ms)
            duration = min(duration, self._max_duration_ms)
            # Prefer original window when it is already short enough.
            if end_ms - start_ms >= self._min_duration_ms:
                cue_end = min(end_ms, start_ms + self._max_duration_ms)
            else:
                cue_end = start_ms + duration
            return [
                SubtitleSegment(
                    start_ms=start_ms,
                    end_ms=cue_end,
                    text=chunks[0],
                )
            ]

        weights = [max(len(chunk.replace("\n", "")), 1) for chunk in chunks]
        total_weight = sum(weights)
        window = max(end_ms - start_ms, self._min_duration_ms * len(chunks))

        # Ideal duration from reading speed, but stay inside the source window
        # when possible and never exceed max cue duration.
        ideal_total = sum(
            max(
                self._min_duration_ms,
                min(
                    self._max_duration_ms,
                    int(round(len(chunk.replace("\n", "")) / self._target_cps * 1000)),
                ),
            )
            for chunk in chunks
        )
        total_duration = max(window, min(ideal_total, self._max_duration_ms * len(chunks)))

        cues: list[SubtitleSegment] = []
        cursor = start_ms
        for index, (chunk, weight) in enumerate(zip(chunks, weights)):
            if index == len(chunks) - 1:
                cue_end = start_ms + total_duration
            else:
                share = weight / total_weight
                cue_duration = int(round(total_duration * share))
                cue_duration = max(self._min_duration_ms, min(self._max_duration_ms, cue_duration))
                cue_end = cursor + cue_duration
            cues.append(
                SubtitleSegment(start_ms=cursor, end_ms=max(cursor + self._min_duration_ms, cue_end), text=chunk)
            )
            cursor = cues[-1].end_ms
        return cues

    def _chunk_text(self, text: str) -> list[str]:
        """Split into cues of at most 2 lines × max display columns/line."""
        tokens = _wrap_tokens(text)
        if not tokens:
            return []

        cues: list[str] = []
        current_lines: list[str] = []
        current_line = ""

        def flush_cue() -> None:
            nonlocal current_lines, current_line
            if current_line:
                current_lines.append(current_line)
                current_line = ""
            if current_lines:
                cues.append("\n".join(current_lines))
                current_lines = []

        def start_piece(piece: str) -> None:
            nonlocal current_line
            if current_line:
                current_lines.append(current_line)
                current_line = ""
            if len(current_lines) >= self._max_lines:
                flush_cue()
            current_line = piece

        for token in tokens:
            candidate = _join_token(current_line, token)
            if _display_width(candidate) <= self._max_chars_per_line:
                current_line = candidate
                continue

            if current_line:
                current_lines.append(current_line)
                current_line = ""
            if len(current_lines) >= self._max_lines:
                flush_cue()

            if _display_width(token) <= self._max_chars_per_line:
                current_line = token
            else:
                for piece in _split_by_display_width(token, self._max_chars_per_line):
                    start_piece(piece)

        if current_line:
            current_lines.append(current_line)
        if current_lines:
            cues.append("\n".join(current_lines))
        return cues

    def _enforce_timing_gaps(
        self,
        cues: list[SubtitleSegment],
    ) -> list[SubtitleSegment]:
        if not cues:
            return cues
        adjusted: list[SubtitleSegment] = [cues[0]]
        for cue in cues[1:]:
            prev = adjusted[-1]
            start = max(cue.start_ms, prev.end_ms + _MIN_GAP_MS)
            end = max(start + self._min_duration_ms, cue.end_ms)
            # Keep original end when possible; only extend if start moved.
            if start > cue.start_ms:
                duration = max(self._min_duration_ms, cue.end_ms - cue.start_ms)
                end = start + min(duration, self._max_duration_ms)
            adjusted.append(
                SubtitleSegment(start_ms=start, end_ms=end, text=cue.text)
            )
        return adjusted

    def _render_srt(self, cues: list[SubtitleSegment]) -> str:
        blocks: list[str] = []
        for index, cue in enumerate(cues, start=1):
            text = "\n".join(
                _format_rtl_srt_line(line) for line in cue.text.split("\n")
            )
            blocks.append(
                f"{index}\n"
                f"{self._format_timestamp(cue.start_ms)} --> "
                f"{self._format_timestamp(cue.end_ms)}\n"
                f"{text}"
            )
        return "\n\n".join(blocks) + "\n"

    @staticmethod
    def _format_timestamp(total_ms: int) -> str:
        if total_ms < 0:
            total_ms = 0
        hours, remainder = divmod(total_ms, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, milliseconds = divmod(remainder, 1_000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
