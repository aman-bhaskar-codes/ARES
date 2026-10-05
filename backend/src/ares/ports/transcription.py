from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


@dataclass(frozen=True, slots=True)
class TranscriptionSegment:
    start_ms: int
    end_ms: int
    text: str
    average_log_probability: float | None = None
    no_speech_probability: float | None = None


@dataclass(slots=True)
class TranscriptionResult:
    language: str | None
    language_probability: float | None
    duration_ms: int
    model_revision: str
    segments: tuple[TranscriptionSegment, ...]
    warnings: list[str] = field(default_factory=list)


class TranscriptionProvider(Protocol):
    def transcribe(
        self,
        path: str | Path,
        *,
        language: str | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> TranscriptionResult: ...
