from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AssetStatus(StrEnum):
    QUARANTINED = "quarantined"
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IngestionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.READY, self.PARTIAL, self.FAILED, self.CANCELLED}


class IngestionStage(StrEnum):
    QUARANTINED = "quarantined"
    QUEUED = "queued"
    PARSING = "parsing"
    ENRICHING = "enriching"
    INDEXING = "indexing"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TextLocator(BaseModel):
    kind: Literal["text"] = "text"
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_offsets(self) -> "TextLocator":
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


class PageRegionLocator(BaseModel):
    kind: Literal["page_region"] = "page_region"
    page: int = Field(ge=1)
    bbox: tuple[float, float, float, float]
    coordinate_space: Literal["normalized_top_left"] = "normalized_top_left"
    rotation_degrees: int = 0

    @model_validator(mode="after")
    def validate_bbox(self) -> "PageRegionLocator":
        left, top, right, bottom = self.bbox
        if not all(0.0 <= value <= 1.0 for value in self.bbox):
            raise ValueError("normalized bbox values must be between 0 and 1")
        if right <= left or bottom <= top:
            raise ValueError("bbox must have positive width and height")
        if self.rotation_degrees not in {0, 90, 180, 270}:
            raise ValueError("rotation_degrees must be 0, 90, 180, or 270")
        return self


class TableCellsLocator(BaseModel):
    kind: Literal["table_cells"] = "table_cells"
    table_id: str = Field(min_length=1, max_length=120)
    rows: list[int] = Field(min_length=1, max_length=128)
    columns: list[int] = Field(min_length=1, max_length=128)
    page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_cells(self) -> "TableCellsLocator":
        if any(value < 0 for value in self.rows + self.columns):
            raise ValueError("table row/column indexes cannot be negative")
        return self


class TimeRangeLocator(BaseModel):
    kind: Literal["time_range"] = "time_range"
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    track: Literal["audio", "video"] = "audio"

    @model_validator(mode="after")
    def validate_range(self) -> "TimeRangeLocator":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class FrameRegionLocator(BaseModel):
    kind: Literal["frame_region"] = "frame_region"
    presentation_time_ms: int = Field(ge=0)
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    coordinate_space: Literal["normalized_top_left"] = "normalized_top_left"
    frame_id: UUID | None = None

    @model_validator(mode="after")
    def validate_bbox(self) -> "FrameRegionLocator":
        left, top, right, bottom = self.bbox
        if not all(0.0 <= value <= 1.0 for value in self.bbox):
            raise ValueError("normalized bbox values must be between 0 and 1")
        if right <= left or bottom <= top:
            raise ValueError("bbox must have positive width and height")
        return self


EvidenceLocator = Annotated[
    TextLocator | PageRegionLocator | TableCellsLocator | TimeRangeLocator | FrameRegionLocator,
    Field(discriminator="kind"),
]


class AssetView(BaseModel):
    id: UUID
    name: str
    mime_type: str
    byte_count: int
    sha256: str
    status: AssetStatus
    width: int | None = None
    height: int | None = None
    page_count: int | None = None
    duration_ms: int | None = None
    cloud_media_allowed: bool = False
    created_at: datetime


class IngestionView(BaseModel):
    id: UUID
    asset_id: UUID
    document_id: UUID | None = None
    status: IngestionStatus
    stage: IngestionStage
    lexical_ready: bool = False
    semantic_ready: bool = False
    cancellation_requested: bool = False
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    last_seq: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class AssetAdmission(BaseModel):
    asset: AssetView
    ingestion: IngestionView


class IngestionEventEnvelope(BaseModel):
    schema_version: int = 1
    ingestion_id: UUID
    seq: int
    event_type: str
    at: datetime
    payload: dict[str, object] = Field(default_factory=dict)


class SegmentView(BaseModel):
    id: UUID
    asset_id: UUID
    extraction_version_id: UUID
    document_id: UUID | None = None
    modality: Literal["text", "image", "table_cell", "audio", "video_frame"]
    text: str | None = None
    locator: EvidenceLocator
    derivation_kind: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    language: str | None = None
    content_hash: str
    origin_group_id: UUID | None = None
    created_at: datetime


class TableCellView(BaseModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    raw_text: str
    normalized_value: str | float | int | None = None
    unit: str | None = None
    is_header: bool = False
    segment_id: UUID | None = None


class TableView(BaseModel):
    id: UUID
    extraction_version_id: UUID
    table_key: str
    page: int | None = None
    locator: EvidenceLocator | None = None
    rows: int
    columns: int
    cells: list[TableCellView] = Field(default_factory=list)


class ExtractionSegmentDraft(BaseModel):
    modality: Literal["text", "image", "table_cell", "audio", "video_frame"] = "text"
    text: str | None = None
    locator: EvidenceLocator
    derivation_kind: str = "machine_extracted"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    language: str | None = None
    origin_group_id: UUID | None = None
    table_key: str | None = None
    table_row: int | None = Field(default=None, ge=0)
    table_column: int | None = Field(default=None, ge=0)


class ExtractionTableCellDraft(BaseModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    raw_text: str
    normalized_value: str | float | int | None = None
    unit: str | None = None
    is_header: bool = False
    locator: EvidenceLocator | None = None


class ExtractionTableDraft(BaseModel):
    table_key: str
    page: int | None = Field(default=None, ge=1)
    locator: EvidenceLocator | None = None
    rows: int = Field(ge=0)
    columns: int = Field(ge=0)
    cells: list[ExtractionTableCellDraft] = Field(default_factory=list)


class RichExtractionResult(BaseModel):
    parser_id: str
    parser_revision: str
    model_revision: str | None = None
    text: str = ""
    page_count: int | None = None
    page_map: list[dict[str, int]] = Field(default_factory=list)
    segments: list[ExtractionSegmentDraft] = Field(default_factory=list)
    tables: list[ExtractionTableDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    output_hash: str


class MediaTrackDraft(BaseModel):
    track_type: Literal["audio", "video"]
    stream_index: int = Field(ge=0)
    codec_name: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=32)
    duration_ms: int | None = Field(default=None, ge=0)
    sample_rate: int | None = Field(default=None, ge=1)
    channels: int | None = Field(default=None, ge=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    average_frame_rate: str | None = Field(default=None, max_length=40)
    metadata: dict[str, object] = Field(default_factory=dict)


class MediaTrackView(MediaTrackDraft):
    id: UUID
    asset_id: UUID
    extraction_version_id: UUID | None = None
    created_at: datetime


class MediaFrameDraft(BaseModel):
    presentation_time_ms: int = Field(ge=0)
    source_kind: Literal["periodic", "scene"]
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64)
    perceptual_hash: str | None = Field(default=None, max_length=32)
    jpeg_bytes: bytes = Field(repr=False)


class MediaFrameView(BaseModel):
    id: UUID
    asset_id: UUID
    extraction_version_id: UUID | None = None
    rendition_id: UUID
    presentation_time_ms: int
    source_kind: Literal["periodic", "scene"]
    width: int
    height: int
    content_hash: str
    content_url: str
    created_at: datetime


class MediaStoryboardView(BaseModel):
    asset_id: UUID
    duration_ms: int | None = None
    sampling_strategy: str
    sampled_times_ms: list[int] = Field(default_factory=list)
    waveform_peaks: list[float] = Field(default_factory=list)
    visual_coverage_warning: str | None = None
    tracks: list[MediaTrackView] = Field(default_factory=list)
    frames: list[MediaFrameView] = Field(default_factory=list)
