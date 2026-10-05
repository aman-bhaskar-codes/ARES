from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MediaRegionInput:
    """One application-approved image region sent to an optional vision provider.

    ``region_id`` is an opaque server-side identifier. Providers may describe it but
    never create source coordinates, timestamps, asset identifiers or permissions.
    """

    region_id: str
    mime_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class MediaRegionObservation:
    region_id: str
    text: str
    model_revision: str


class MultimodalUnderstandingProvider(Protocol):
    def describe_regions(
        self,
        instruction: str,
        regions: list[MediaRegionInput],
        *,
        max_output_tokens: int,
        timeout_seconds: float | None = None,
    ) -> list[MediaRegionObservation]: ...
