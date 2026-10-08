from __future__ import annotations

import csv
import hashlib
import io
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import UUID

from ares.adapters.pdf_parser import BoundedPdfParser
from ares.application.documents import PreparedChunk, build_document_chunks
from ares.application.indexing import DocumentEmbeddingIndexer
from ares.application.media_ingestion import (
    MEDIA_MIME_TYPES,
    FFmpegMediaProcessor,
    MediaIngestionResult,
)
from ares.application.repository import IngestionLease, Repository, StaleLeaseError
from ares.domain.assets import (
    AssetAdmission,
    ExtractionSegmentDraft,
    ExtractionTableCellDraft,
    ExtractionTableDraft,
    FrameRegionLocator,
    IngestionStage,
    RichExtractionResult,
    TableCellsLocator,
    TextLocator,
)
from ares.domain.models import DocumentStatus
from ares.ports.storage import BlobStore


class AssetAdmissionError(ValueError):
    pass


class RichExtractionUnavailable(RuntimeError):
    pass


ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "text/csv",
    *MEDIA_MIME_TYPES,
}


@dataclass(frozen=True, slots=True)
class StagedUpload:
    path: Path
    byte_count: int
    sha256: str
    mime_type: str


def _sniff_mime(prefix: bytes, *, supplied: str, name: str) -> str:
    supplied = supplied.partition(";")[0].strip().lower()
    if prefix.startswith(b"%PDF-"):
        return "application/pdf"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
        return "image/webp"
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WAVE":
        return "audio/wav"
    if prefix.startswith(b"ID3") or (
        len(prefix) >= 2 and prefix[0] == 0xFF and (prefix[1] & 0xE0) == 0xE0
    ):
        return "audio/mpeg"
    if len(prefix) >= 12 and prefix[4:8] == b"ftyp":
        suffix = Path(name).suffix.casefold()
        if supplied.startswith("audio/") or suffix in {".m4a", ".m4b", ".m4p"}:
            return "audio/mp4"
        return "video/mp4"
    if prefix.startswith(b"\x1aE\xdf\xa3"):
        return "audio/webm" if supplied.startswith("audio/") else "video/webm"
    if prefix.startswith(b"OggS"):
        return "audio/ogg"
    if supplied == "text/csv" or Path(name).suffix.casefold() == ".csv":
        # CSV has no reliable magic number. Reject binary-looking payloads and let the
        # worker perform strict UTF-8/cell-count validation before publication.
        if b"\x00" in prefix:
            raise AssetAdmissionError("CSV upload contains binary data")
        return "text/csv"
    guessed = (mimetypes.guess_type(name)[0] or supplied).lower()
    if guessed in ALLOWED_MIME_TYPES and guessed.startswith("image/"):
        raise AssetAdmissionError("image signature does not match the declared type")
    raise AssetAdmissionError(
        "unsupported file type; ARES accepts PDF, PNG, JPEG, WebP, CSV, supported audio, MP4, and WebM"
    )


def inspect_staged_upload(path: Path, *, supplied_mime: str, name: str) -> StagedUpload:
    digest = hashlib.sha256()
    byte_count = 0
    prefix = b""
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            if not prefix:
                prefix = chunk[:64]
            digest.update(chunk)
            byte_count += len(chunk)
    if byte_count == 0:
        raise AssetAdmissionError("empty uploads are not accepted")
    return StagedUpload(
        path=path,
        byte_count=byte_count,
        sha256=digest.hexdigest(),
        mime_type=_sniff_mime(prefix, supplied=supplied_mime, name=name),
    )


class AssetAdmissionService:
    def __init__(
        self,
        repository: Repository,
        blobs: BlobStore,
        *,
        max_upload_bytes: int,
        max_image_bytes: int | None = None,
        max_audio_bytes: int | None = None,
        max_video_bytes: int | None = None,
        audio_enabled: bool = False,
        video_enabled: bool = False,
        audio_ready: Callable[[], bool] | None = None,
        video_ready: Callable[[], bool] | None = None,
        cloud_media_enabled: bool = False,
    ) -> None:
        self.repository = repository
        self.blobs = blobs
        self.max_upload_bytes = max_upload_bytes
        self.max_image_bytes = max_image_bytes if max_image_bytes is not None else max_upload_bytes
        self.max_audio_bytes = max_audio_bytes if max_audio_bytes is not None else max_upload_bytes
        self.max_video_bytes = max_video_bytes if max_video_bytes is not None else max_upload_bytes
        self.audio_enabled = audio_enabled
        self.video_enabled = video_enabled
        self.audio_ready = audio_ready
        self.video_ready = video_ready
        self.cloud_media_enabled = cloud_media_enabled

    @property
    def maximum_admission_bytes(self) -> int:
        limits = [self.max_upload_bytes]
        if self.audio_enabled:
            limits.append(self.max_audio_bytes)
        if self.video_enabled:
            limits.append(self.max_video_bytes)
        return max(limits)

    def admit_staged(
        self,
        *,
        path: Path,
        name: str,
        supplied_mime: str,
        allow_cloud_media: bool = False,
    ) -> AssetAdmission:
        safe_name = Path(name).name.strip()
        if not safe_name or safe_name in {".", ".."}:
            raise AssetAdmissionError("upload requires a valid file name")
        if len(safe_name) > 240:
            raise AssetAdmissionError("file name is too long")
        staged = inspect_staged_upload(path, supplied_mime=supplied_mime, name=safe_name)
        is_audio = staged.mime_type.startswith("audio/")
        is_video = staged.mime_type.startswith("video/")
        if is_audio:
            if not self.audio_enabled:
                raise AssetAdmissionError("audio ingestion is disabled")
            if self.audio_ready is not None and not self.audio_ready():
                raise AssetAdmissionError(
                    "audio ingestion is enabled but no ready media worker is available"
                )
            if staged.byte_count > self.max_audio_bytes:
                raise AssetAdmissionError("audio exceeds the configured byte limit")
        elif is_video:
            if not self.video_enabled:
                raise AssetAdmissionError("video ingestion is disabled")
            if self.video_ready is not None and not self.video_ready():
                raise AssetAdmissionError(
                    "video ingestion is enabled but no ready media worker is available"
                )
            if staged.byte_count > self.max_video_bytes:
                raise AssetAdmissionError("video exceeds the configured byte limit")
        else:
            if staged.byte_count > self.max_upload_bytes:
                raise AssetAdmissionError("upload exceeds the configured byte limit")
            if staged.mime_type.startswith("image/") and staged.byte_count > self.max_image_bytes:
                raise AssetAdmissionError("image exceeds the configured byte limit")
        if allow_cloud_media and not (is_audio or is_video):
            raise AssetAdmissionError("cloud-media consent applies only to audio/video assets")
        if allow_cloud_media and not self.cloud_media_enabled:
            raise AssetAdmissionError("cloud media analysis is disabled")
        blob_key = self.blobs.put_file("assets", staged.path)
        try:
            asset, ingestion = self.repository.create_asset_ingestion(
                name=safe_name,
                mime_type=staged.mime_type,
                byte_count=staged.byte_count,
                sha256=staged.sha256,
                blob_key=blob_key,
                cloud_media_allowed=allow_cloud_media,
            )
        except Exception:
            if not self.repository.is_blob_referenced(blob_key):
                self.blobs.delete(blob_key)
            raise
        return AssetAdmission(asset=asset, ingestion=ingestion)


class BuiltinRichExtractor:
    """Bounded extraction for formats that do not require the optional Docling profile."""

    def __init__(
        self,
        pdf_parser: BoundedPdfParser,
        *,
        max_csv_rows: int = 5_000,
        max_table_cells: int = 50_000,
        max_cell_chars: int = 10_000,
    ) -> None:
        self.pdf_parser = pdf_parser
        self.max_csv_rows = max_csv_rows
        self.max_table_cells = max_table_cells
        self.max_cell_chars = max_cell_chars

    @staticmethod
    def _hash_payload(payload: object) -> str:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def extract_pdf(self, raw: bytes, *, name: str) -> RichExtractionResult:
        parsed = self.pdf_parser.parse(raw)
        if parsed.status == "needs_ocr":
            raise RichExtractionUnavailable("PDF has no usable text layer and requires OCR")
        segments: list[ExtractionSegmentDraft] = []
        for page in parsed.page_map:
            start, end = int(page["char_start"]), int(page["char_end"])
            text = parsed.text[start:end].strip()
            if not text:
                continue
            segments.append(
                ExtractionSegmentDraft(
                    modality="text",
                    text=text,
                    locator=TextLocator(char_start=start, char_end=max(start + 1, end)),
                    derivation_kind="native_text",
                )
            )
        payload = {
            "parser": parsed.parser_version,
            "text": parsed.text,
            "page_map": parsed.page_map,
            "warnings": parsed.warnings,
        }
        return RichExtractionResult(
            parser_id="pypdf",
            parser_revision=parsed.parser_version,
            text=parsed.text,
            page_count=parsed.page_count,
            page_map=parsed.page_map,
            segments=segments,
            warnings=parsed.warnings,
            output_hash=self._hash_payload(payload),
        )

    def extract_csv(self, raw: bytes, *, name: str) -> RichExtractionResult:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV must be UTF-8 encoded") from exc
        sample = text[:16_384]
        try:
            dialect = (
                csv.Sniffer().sniff(sample, delimiters=",;\t|") if sample.strip() else csv.excel
            )
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text, newline=""), dialect)
        rows: list[list[str]] = []
        total_cells = 0
        for row_index, row in enumerate(reader):
            if row_index >= self.max_csv_rows:
                raise ValueError(f"CSV exceeds the {self.max_csv_rows:,}-row limit")
            if any(len(cell) > self.max_cell_chars for cell in row):
                raise ValueError("CSV contains a cell larger than the configured limit")
            total_cells += len(row)
            if total_cells > self.max_table_cells:
                raise ValueError(f"CSV exceeds the {self.max_table_cells:,}-cell limit")
            rows.append(row)
        if not rows:
            raise ValueError("CSV contains no rows")
        columns = max((len(row) for row in rows), default=0)
        table_key = "table-1"
        cell_drafts: list[ExtractionTableCellDraft] = []
        segments: list[ExtractionSegmentDraft] = []
        for row_index, row in enumerate(rows):
            padded = row + [""] * (columns - len(row))
            non_empty_columns = [index for index, value in enumerate(padded) if value.strip()]
            if non_empty_columns:
                segments.append(
                    ExtractionSegmentDraft(
                        modality="table_cell",
                        text=" | ".join(padded),
                        locator=TableCellsLocator(
                            table_id=table_key,
                            rows=[row_index],
                            columns=non_empty_columns,
                        ),
                        derivation_kind="csv_native",
                    )
                )
            for column_index, value in enumerate(padded):
                locator = TableCellsLocator(
                    table_id=table_key, rows=[row_index], columns=[column_index]
                )
                cell_drafts.append(
                    ExtractionTableCellDraft(
                        row=row_index,
                        column=column_index,
                        raw_text=value,
                        normalized_value=_normalize_scalar(value),
                        is_header=row_index == 0,
                        locator=locator,
                    )
                )
                segments.append(
                    ExtractionSegmentDraft(
                        modality="table_cell",
                        text=value,
                        locator=locator,
                        derivation_kind="csv_native",
                        table_key=table_key,
                        table_row=row_index,
                        table_column=column_index,
                    )
                )
        normalized_text = "\n".join(" | ".join(row + [""] * (columns - len(row))) for row in rows)
        table = ExtractionTableDraft(
            table_key=table_key,
            rows=len(rows),
            columns=columns,
            cells=cell_drafts,
        )
        payload = {"rows": rows, "dialect": getattr(dialect, "delimiter", ",")}
        return RichExtractionResult(
            parser_id="python-csv",
            parser_revision="stdlib-csv-v1",
            text=normalized_text,
            segments=segments,
            tables=[table],
            warnings=[],
            output_hash=self._hash_payload(payload),
        )


def _normalize_scalar(value: str) -> str | int | float | None:
    stripped = value.strip()
    if not stripped:
        return None
    # Keep identifiers with leading zeroes as text. Numeric normalization is a
    # convenience field only; the raw cell remains authoritative.
    if re.fullmatch(r"[-+]?\d+", stripped) and not re.fullmatch(r"[-+]?0\d+", stripped):
        try:
            return int(stripped)
        except ValueError:
            pass
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][-+]?\d+)?", stripped):
        try:
            value_float = float(stripped)
            return (
                value_float
                if value_float == value_float and abs(value_float) != float("inf")
                else stripped
            )
        except ValueError:
            pass
    return stripped


def _chunks_for_extraction(name: str, extraction: RichExtractionResult) -> list[PreparedChunk]:
    if extraction.tables and extraction.parser_id == "python-csv":
        chunks: list[PreparedChunk] = []
        cursor = 0
        row_segments = [
            (index, segment)
            for index, segment in enumerate(extraction.segments)
            if segment.locator.kind == "table_cells" and len(segment.locator.columns) > 1
        ]
        for chunk_index, (segment_index, segment) in enumerate(row_segments, start=1):
            text = segment.text or ""
            if not text.strip():
                continue
            start = extraction.text.find(text, cursor)
            if start < 0:
                raise ValueError("CSV row text could not be aligned with the extracted document")
            cursor = start + len(text)
            chunks.append(
                PreparedChunk(
                    chunk_index=chunk_index,
                    text=text,
                    char_start=start,
                    char_end=cursor,
                    page_start=None,
                    page_end=None,
                    locator=f"table 1 · row {segment.locator.rows[0] + 1}",
                    segment_index=segment_index,
                )
            )
            cursor += 1
        return chunks

    media_segments = [
        (index, segment)
        for index, segment in enumerate(extraction.segments)
        if segment.locator.kind in {"time_range", "frame_region"} and (segment.text or "").strip()
    ]
    if media_segments:
        chunks: list[PreparedChunk] = []
        cursor = 0
        for chunk_index, (segment_index, segment) in enumerate(media_segments):
            segment_text = (segment.text or "").strip()
            start = extraction.text.find(segment_text, cursor)
            if start < 0:
                start = extraction.text.find(segment_text)
            if start < 0:
                raise ValueError(
                    "media evidence text could not be aligned with the compatibility document"
                )
            end = start + len(segment_text)
            cursor = end
            if segment.locator.kind == "time_range":
                locator = (
                    f"{segment.locator.track} "
                    f"{segment.locator.start_ms}ms–{segment.locator.end_ms}ms"
                )
            else:
                locator = f"video frame {segment.locator.presentation_time_ms}ms"
            chunks.append(
                PreparedChunk(
                    chunk_index=chunk_index,
                    text=segment_text,
                    char_start=start,
                    char_end=end,
                    page_start=None,
                    page_end=None,
                    locator=locator,
                    segment_index=segment_index,
                )
            )
        return chunks

    chunks = build_document_chunks(name=name, text=extraction.text, page_map=extraction.page_map)
    if not chunks or not extraction.segments:
        return chunks
    assigned: list[PreparedChunk] = []
    for chunk in chunks:
        segment_index = None
        for index, segment in enumerate(extraction.segments):
            if segment.locator.kind == "text":
                if (
                    segment.locator.char_end > chunk.char_start
                    and segment.locator.char_start < chunk.char_end
                ):
                    segment_index = index
                    break
            elif segment.locator.kind == "page_region" and chunk.page_start is not None:
                if chunk.page_start <= segment.locator.page <= (chunk.page_end or chunk.page_start):
                    segment_index = index
                    break
        assigned.append(
            PreparedChunk(
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                locator=chunk.locator,
                segment_index=segment_index,
            )
        )
    return assigned


class AssetIngestionExecutor:
    def __init__(
        self,
        repository: Repository,
        blobs: BlobStore,
        builtin: BuiltinRichExtractor,
        indexer: DocumentEmbeddingIndexer,
        *,
        rich_parser=None,
        ocr_enabled: bool = False,
        max_image_pixels: int = 20_000_000,
        max_table_cells: int = 50_000,
        media_processor: FFmpegMediaProcessor | None = None,
        max_frame_ocr_frames: int = 8,
        config_hash: str = "m09-default",
    ) -> None:
        self.repository = repository
        self.blobs = blobs
        self.builtin = builtin
        self.indexer = indexer
        self.rich_parser = rich_parser
        self.ocr_enabled = ocr_enabled
        self.max_image_pixels = max_image_pixels
        self.max_table_cells = max_table_cells
        self.media_processor = media_processor
        self.max_frame_ocr_frames = max(0, max_frame_ocr_frames)
        self.config_hash = config_hash

    def execute(self, lease: IngestionLease) -> None:
        new_blob_keys: list[str] = []
        try:
            self.repository.authorize_ingestion_execution(lease)
            if self.repository.ingestion_cancel_requested(lease):
                self.repository.complete_ingestion(lease)
                return
            asset = self.repository.get_ingestion_asset_for_worker(lease)
            self.repository.set_ingestion_stage(lease, IngestionStage.PARSING)
            raw = self.blobs.get_bytes(asset.original_blob_key)

            extraction: RichExtractionResult
            media_result: MediaIngestionResult | None = None
            if asset.mime_type == "text/csv":
                extraction = self.builtin.extract_csv(raw, name=asset.original_name)
            elif asset.mime_type == "application/pdf":
                try:
                    extraction = self.builtin.extract_pdf(raw, name=asset.original_name)
                except RichExtractionUnavailable:
                    extraction = self._rich_extract(
                        lease, asset.mime_type, raw, asset.original_name
                    )
            elif asset.mime_type.startswith("image/"):
                width, height = self._validate_image_dimensions(raw)
                self.repository.set_ingestion_asset_dimensions(lease, width=width, height=height)
                extraction = self._rich_extract(lease, asset.mime_type, raw, asset.original_name)
            elif asset.mime_type in MEDIA_MIME_TYPES:
                if self.media_processor is None:
                    raise RichExtractionUnavailable(
                        "media ingestion is unavailable in this worker profile"
                    )
                self.repository.set_ingestion_stage(lease, IngestionStage.ENRICHING)
                media_result = self.media_processor.extract(
                    raw,
                    mime_type=asset.mime_type,
                    name=asset.original_name,
                    cancelled=lambda: self.repository.ingestion_cancel_requested(lease),
                )
                extraction = media_result.extraction
                if asset.mime_type.startswith("video/") and media_result.frames:
                    extraction = self._enrich_video_frames(
                        extraction, media_result, asset_sha256=asset.sha256
                    )
                self.repository.set_ingestion_asset_media_metadata(
                    lease,
                    duration_ms=media_result.duration_ms,
                    width=media_result.width,
                    height=media_result.height,
                    media_metadata=media_result.media_metadata,
                )
            else:  # admission should make this unreachable
                raise ValueError(f"unsupported admitted MIME type {asset.mime_type}")

            if self.repository.ingestion_cancel_requested(lease):
                self.repository.complete_ingestion(lease)
                return
            if sum(len(table.cells) for table in extraction.tables) > self.max_table_cells:
                raise ValueError(
                    f"extraction exceeds the {self.max_table_cells:,}-cell publication limit"
                )
            chunks = _chunks_for_extraction(asset.original_name, extraction)
            status = DocumentStatus.READY if chunks else DocumentStatus.PARTIAL
            if extraction.warnings:
                status = DocumentStatus.PARTIAL if status is DocumentStatus.READY else status
            publication = self.repository.publish_ingestion_extraction(
                lease,
                parser_id=extraction.parser_id,
                parser_revision=extraction.parser_revision,
                model_revision=extraction.model_revision,
                config_hash=self.config_hash,
                output_hash=extraction.output_hash,
                text_content=extraction.text,
                page_count=extraction.page_count,
                page_map=extraction.page_map,
                warnings=extraction.warnings,
                document_status=status,
                segments=extraction.segments,
                tables=extraction.tables,
                chunks=chunks,
            )
            if media_result is not None:
                frame_blobs = []
                for frame in media_result.frames:
                    blob_key = self.blobs.put_bytes("renditions/video-frames", frame.jpeg_bytes)
                    new_blob_keys.append(blob_key)
                    frame_blobs.append((frame, blob_key))
                self.repository.publish_media_metadata(
                    lease,
                    extraction_version_id=publication.extraction_version_id,
                    tracks=media_result.tracks,
                    frames=frame_blobs,
                    media_metadata=media_result.media_metadata,
                )
            if self.repository.ingestion_cancel_requested(lease):
                self.repository.complete_ingestion(lease)
                return
            completion_warnings = list(extraction.warnings)
            semantic_partial = False
            try:
                self.indexer.index_document(lease, publication.document_id)
            except StaleLeaseError:
                raise
            except Exception as exc:
                # Lexical publication is already durable and useful. Semantic indexing is
                # an independent readiness dimension, so a model/runtime failure degrades
                # the ingestion instead of discarding searchable evidence. A retry can
                # resume missing embeddings idempotently.
                semantic_partial = True
                completion_warnings.append(
                    f"Semantic indexing unavailable: {type(exc).__name__}: {str(exc)[:240]}"
                )
                self.repository.mark_document_semantic_ready(
                    lease, publication.document_id, ready=False
                )
            self.repository.complete_ingestion(
                lease,
                partial=status is DocumentStatus.PARTIAL or semantic_partial,
                warnings=completion_warnings,
            )
        except StaleLeaseError:
            self._cleanup_unreferenced_blobs(new_blob_keys)
            raise
        except Exception as exc:
            self._cleanup_unreferenced_blobs(new_blob_keys)
            # Media subprocesses poll the durable cancellation flag. If the user
            # cancelled while FFmpeg/ASR was running, publish a cancelled terminal
            # state rather than converting that intentional stop into a failure.
            try:
                if self.repository.ingestion_cancel_requested(lease):
                    self.repository.complete_ingestion(lease)
                    return
            except StaleLeaseError:
                raise
            self.repository.fail_ingestion(lease, code=type(exc).__name__, message=str(exc)[:800])
            raise

    def _cleanup_unreferenced_blobs(self, blob_keys: list[str]) -> None:
        for blob_key in dict.fromkeys(blob_keys):
            try:
                if not self.repository.is_blob_referenced(blob_key):
                    self.blobs.delete(blob_key)
            except Exception:
                # Cleanup is best-effort here; the authoritative DB transaction is
                # already fenced. Operators can reconcile orphaned content-addressed
                # blobs without risking deletion of referenced media.
                pass

    def _enrich_video_frames(
        self,
        extraction: RichExtractionResult,
        media_result: MediaIngestionResult,
        *,
        asset_sha256: str,
    ) -> RichExtractionResult:
        if (
            not self.ocr_enabled
            or self.rich_parser is None
            or self.max_frame_ocr_frames <= 0
            or not media_result.frames
        ):
            return extraction
        frame_count = min(self.max_frame_ocr_frames, len(media_result.frames))
        if frame_count == len(media_result.frames):
            selected = list(media_result.frames)
        else:
            indexes = {
                round(index * (len(media_result.frames) - 1) / max(1, frame_count - 1))
                for index in range(frame_count)
            }
            selected = [media_result.frames[index] for index in sorted(indexes)]
        origin_group_id = next(
            (
                segment.origin_group_id
                for segment in extraction.segments
                if segment.origin_group_id is not None
            ),
            UUID(bytes=bytes.fromhex(asset_sha256)[:16]),
        )
        segments = list(extraction.segments)
        text_parts = [extraction.text] if extraction.text else []
        warnings = list(extraction.warnings)
        for frame in selected:
            try:
                parsed = self.rich_parser.parse(
                    raw=frame.jpeg_bytes,
                    mime_type="image/jpeg",
                    name=f"frame-{frame.presentation_time_ms}.jpg",
                )
            except Exception as exc:
                warnings.append(
                    f"Frame OCR at {frame.presentation_time_ms} ms failed: "
                    f"{type(exc).__name__}: {str(exc)[:180]}"
                )
                continue
            for source_segment in parsed.segments:
                frame_text = (source_segment.text or "").strip()
                if not frame_text:
                    continue
                bbox = (0.0, 0.0, 1.0, 1.0)
                if source_segment.locator.kind == "page_region":
                    bbox = source_segment.locator.bbox
                segments.append(
                    ExtractionSegmentDraft(
                        modality="video_frame",
                        text=frame_text,
                        locator=FrameRegionLocator(
                            presentation_time_ms=frame.presentation_time_ms,
                            bbox=bbox,
                        ),
                        derivation_kind="frame_ocr",
                        confidence=source_segment.confidence,
                        language=source_segment.language,
                        origin_group_id=origin_group_id,
                    )
                )
                text_parts.append(frame_text)
        text_content = "\n".join(part for part in text_parts if part)
        payload = {
            "base_output_hash": extraction.output_hash,
            "segments": [segment.model_dump(mode="json") for segment in segments],
            "warnings": warnings,
        }
        return RichExtractionResult(
            parser_id=extraction.parser_id,
            parser_revision=extraction.parser_revision,
            model_revision=extraction.model_revision,
            text=text_content,
            page_count=extraction.page_count,
            page_map=extraction.page_map,
            segments=segments,
            tables=extraction.tables,
            warnings=list(dict.fromkeys(warnings)),
            output_hash=hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        )

    def _validate_image_dimensions(self, raw: bytes) -> tuple[int, int]:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RichExtractionUnavailable(
                "image processing requires the optional rich-document profile"
            ) from exc
        try:
            with Image.open(io.BytesIO(raw)) as image:
                width, height = image.size
                if width <= 0 or height <= 0:
                    raise ValueError("image has invalid decoded dimensions")
                if width * height > self.max_image_pixels:
                    raise ValueError(
                        f"image exceeds the {self.max_image_pixels:,}-pixel decoded limit"
                    )
                image.verify()
                return width, height
        except RichExtractionUnavailable:
            raise
        except Exception as exc:
            raise ValueError("image could not be safely decoded") from exc

    def _rich_extract(
        self, lease: IngestionLease, mime_type: str, raw: bytes, name: str
    ) -> RichExtractionResult:
        if not self.ocr_enabled:
            raise RichExtractionUnavailable(
                "OCR is required for this asset but OCR_ENABLED is false"
            )
        if self.rich_parser is None:
            raise RichExtractionUnavailable(
                "rich document parser is unavailable in this worker profile"
            )
        self.repository.set_ingestion_stage(lease, IngestionStage.ENRICHING)
        return self.rich_parser.parse(raw=raw, mime_type=mime_type, name=name)


__all__ = [
    "ALLOWED_MIME_TYPES",
    "AssetAdmissionError",
    "AssetAdmissionService",
    "AssetIngestionExecutor",
    "BuiltinRichExtractor",
    "RichExtractionUnavailable",
    "StagedUpload",
    "inspect_staged_upload",
]
