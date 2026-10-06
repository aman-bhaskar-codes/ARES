from __future__ import annotations

import math
import shutil
import struct
import subprocess
import threading
import time
import wave
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ares.adapters.filesystem_blob import FilesystemBlobStore
from ares.adapters.pdf_parser import BoundedPdfParser
from ares.api.app import create_app
from ares.api.settings import Settings
from ares.application.asset_ingestion import (
    AssetAdmissionService,
    AssetIngestionExecutor,
    BuiltinRichExtractor,
)
from ares.application.indexing import DocumentEmbeddingIndexer
from ares.application.identity import Principal, WorkspaceRole, principal_scope
from ares.application.media_ingestion import FFmpegMediaProcessor
from ares.application.repository import NotFoundError
from ares.ports.transcription import TranscriptionResult, TranscriptionSegment


class FakeTranscriber:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def transcribe(
        self, path: Path, *, language: str | None = None, cancelled=None
    ) -> TranscriptionResult:
        del language
        if cancelled is not None and cancelled():
            raise RuntimeError("cancelled")
        self.calls.append(path)
        return TranscriptionResult(
            language="en",
            language_probability=0.99,
            duration_ms=1_200,
            model_revision="fake-whisper-small",
            segments=(
                TranscriptionSegment(start_ms=0, end_ms=600, text="alpha ten"),
                TranscriptionSegment(start_ms=600, end_ms=1_200, text="beta ninety"),
            ),
            warnings=[],
        )


def _wav_bytes(duration_seconds: float = 1.25, *, sample_rate: int = 16_000) -> bytes:
    frames = int(duration_seconds * sample_rate)
    raw = bytearray()
    for index in range(frames):
        sample = int(5_000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        raw.extend(struct.pack("<h", sample))
    from io import BytesIO

    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes(raw))
    return buffer.getvalue()


def _make_video(tmp_path: Path) -> bytes:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not installed")
    target = tmp_path / "sample.mp4"
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x180:rate=12:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=16000:duration=2",
        "-c:v",
        "mpeg4",
        "-q:v",
        "4",
        "-c:a",
        "aac",
        "-shortest",
        "-y",
        str(target),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    if completed.returncode != 0:
        pytest.skip(f"local ffmpeg cannot build the test fixture: {completed.stderr[-240:]}")
    return target.read_bytes()


def _processor(transcriber: FakeTranscriber, *, frame_cap: int = 8) -> FFmpegMediaProcessor:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe are not installed")
    return FFmpegMediaProcessor(
        transcriber,
        max_audio_duration_seconds=10,
        max_video_duration_seconds=10,
        max_video_source_pixels=2_000_000,
        max_selected_frames=frame_cap,
        baseline_frames=min(frame_cap, 4),
        scene_threshold=0.2,
        timeout_seconds=30,
        subprocess_memory_mb=1024,
        subprocess_cpu_seconds=30,
    )


def _executor(repository, blobs, processor) -> AssetIngestionExecutor:
    return AssetIngestionExecutor(
        repository,
        blobs,
        BuiltinRichExtractor(
            BoundedPdfParser(max_bytes=2_000_000, max_pages=10, timeout_seconds=5)
        ),
        DocumentEmbeddingIndexer(repository, None, model_id="", dimensions=3),
        media_processor=processor,
        max_frame_ocr_frames=0,
    )


def test_audio_processor_preserves_timestamped_source_transcript() -> None:
    transcriber = FakeTranscriber()
    result = _processor(transcriber).extract(_wav_bytes(), mime_type="audio/wav", name="voice.wav")

    assert result.duration_ms >= 1_200
    assert result.width is None and result.height is None
    assert len(transcriber.calls) == 1
    assert [segment.text for segment in result.extraction.segments] == ["alpha ten", "beta ninety"]
    assert all(segment.modality == "audio" for segment in result.extraction.segments)
    assert [segment.locator.kind for segment in result.extraction.segments] == [
        "time_range",
        "time_range",
    ]
    assert result.extraction.segments[0].locator.start_ms == 0
    assert result.extraction.segments[1].locator.end_ms == 1_200
    assert result.extraction.segments[0].locator.track == "audio"
    assert len({segment.origin_group_id for segment in result.extraction.segments}) == 1
    assert result.extraction.model_revision == "fake-whisper-small"
    peaks = result.media_metadata["waveform_peaks"]
    assert isinstance(peaks, list) and 1 <= len(peaks) <= 120
    assert all(0.0 <= float(value) <= 1.0 for value in peaks)


def test_video_processor_uses_bounded_pts_frames_and_shared_transcript_pipeline(
    tmp_path: Path,
) -> None:
    transcriber = FakeTranscriber()
    result = _processor(transcriber, frame_cap=6).extract(
        _make_video(tmp_path), mime_type="video/mp4", name="clip.mp4"
    )

    assert result.width == 320 and result.height == 180
    assert 1_500 <= result.duration_ms <= 10_000
    assert 1 <= len(result.frames) <= 6
    times = [frame.presentation_time_ms for frame in result.frames]
    assert times == sorted(times)
    assert all(0 <= timestamp <= result.duration_ms + 250 for timestamp in times)
    assert all(frame.width <= 1280 and frame.height <= 720 for frame in result.frames)
    assert all(len(frame.content_hash) == 64 for frame in result.frames)
    assert any(track.track_type == "video" for track in result.tracks)
    assert any(track.track_type == "audio" for track in result.tracks)
    assert result.extraction.segments[0].locator.track == "video"
    assert result.media_metadata["sampling_strategy"] == "periodic+scene-v1"
    assert result.media_metadata["waveform_peaks"]
    assert "not exhaustive" in str(result.media_metadata["visual_coverage_warning"]).lower()


def test_audio_ingestion_publishes_timestamp_segments_into_existing_rag_chunks(
    repository, tmp_path: Path
) -> None:
    blobs = FilesystemBlobStore(str(tmp_path / "blobs"))
    staged = tmp_path / "sample.wav"
    staged.write_bytes(_wav_bytes())
    admitted = AssetAdmissionService(
        repository,
        blobs,
        max_upload_bytes=2_000_000,
        max_audio_bytes=2_000_000,
        audio_enabled=True,
        audio_ready=lambda: True,
    ).admit_staged(path=staged, name="sample.wav", supplied_mime="audio/wav")

    lease = repository.claim_next_ingestion()
    assert lease is not None
    _executor(repository, blobs, _processor(FakeTranscriber())).execute(lease)

    ingestion = repository.get_ingestion(admitted.ingestion.id)
    assert ingestion.status.value == "ready"
    assert ingestion.document_id is not None
    asset = repository.get_asset_record(admitted.asset.id)
    assert asset.duration_ms is not None and asset.duration_ms >= 1_200
    chunks = repository.get_document_chunks([ingestion.document_id])
    assert chunks
    cited = [
        repository.get_segment(chunk.evidence_segment_id)
        for chunk in chunks
        if chunk.evidence_segment_id
    ]
    assert cited and all(segment.locator.kind == "time_range" for segment in cited)
    assert {segment.origin_group_id for segment in cited} == {cited[0].origin_group_id}


def test_video_storyboard_renditions_are_authorized_and_deleted_with_asset(
    repository, tmp_path: Path
) -> None:
    blobs = FilesystemBlobStore(str(tmp_path / "video-blobs"))
    staged = tmp_path / "sample.mp4"
    staged.write_bytes(_make_video(tmp_path))
    admitted = AssetAdmissionService(
        repository,
        blobs,
        max_upload_bytes=5_000_000,
        max_video_bytes=5_000_000,
        video_enabled=True,
        video_ready=lambda: True,
    ).admit_staged(path=staged, name="sample.mp4", supplied_mime="video/mp4")
    lease = repository.claim_next_ingestion()
    assert lease is not None
    _executor(repository, blobs, _processor(FakeTranscriber(), frame_cap=5)).execute(lease)

    ingestion = repository.get_ingestion(admitted.ingestion.id)
    assert ingestion.document_id is not None
    storyboard = repository.get_media_storyboard(admitted.asset.id)
    assert 1 <= len(storyboard.frames) <= 5
    assert storyboard.sampled_times_ms
    assert storyboard.waveform_peaks
    assert "sampled" in (storyboard.visual_coverage_warning or "").lower()
    rendition = repository.get_rendition_record(storyboard.frames[0].rendition_id)
    assert blobs.get_bytes(rendition.blob_key)

    other = Principal(
        user_id=uuid4(),
        workspace_id=uuid4(),
        role=WorkspaceRole.OWNER,
        subject="test:other-workspace",
    )
    with principal_scope(other):
        with pytest.raises(NotFoundError):
            repository.get_media_storyboard(admitted.asset.id)
        with pytest.raises(NotFoundError):
            repository.get_rendition_record(storyboard.frames[0].rendition_id)

    blob_keys = repository.delete_document_with_blobs(ingestion.document_id)
    assert rendition.blob_key in blob_keys
    for blob_key in blob_keys:
        blobs.delete(blob_key)
    with pytest.raises(FileNotFoundError):
        blobs.get_bytes(rendition.blob_key)


def test_media_api_refuses_configured_audio_when_runtime_is_not_ready(tmp_path: Path) -> None:
    settings = Settings(
        ares_mode="demo",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'api.sqlite3'}",
        blob_root=str(tmp_path / "blobs"),
        audio_enabled=True,
        max_upload_bytes=1_024,
        max_image_bytes=1_024,
        max_request_body_bytes=1_024,
        max_audio_bytes=2_000_000,
        max_asset_request_body_bytes=2_000_000,
        whisper_model_path=str(tmp_path / "missing-whisper-model"),
    )
    client = TestClient(create_app(settings))
    response = client.post(
        "/api/v2/assets",
        files={"file": ("voice.wav", _wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ASSET_ADMISSION_REJECTED"
    assert "no ready media worker" in response.json()["detail"]["message"]


def test_demo_video_degrades_to_visual_only_when_asr_is_unavailable(tmp_path: Path) -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe are not installed")
    settings = Settings(
        ares_mode="demo",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'visual-only.sqlite3'}",
        blob_root=str(tmp_path / "visual-only-blobs"),
        video_enabled=True,
        max_video_bytes=5_000_000,
        max_asset_request_body_bytes=6_000_000,
        whisper_model_path=str(tmp_path / "missing-whisper-model"),
        max_video_duration_seconds=10,
        max_video_frames=5,
        video_baseline_frames=3,
        media_process_timeout_seconds=30,
        media_subprocess_cpu_seconds=30,
        media_subprocess_memory_mb=1024,
    )
    client = TestClient(create_app(settings))

    system = client.get("/api/v1/system/status")
    assert system.status_code == 200
    assert system.json()["ingestion"]["video_ready"] is True
    assert system.json()["tools"]["audio_transcription"]["ready"] is False

    created = client.post(
        "/api/v2/assets",
        files={"file": ("visual-only.mp4", _make_video(tmp_path), "video/mp4")},
    )
    assert created.status_code == 202
    ingestion_id = created.json()["ingestion"]["id"]
    asset_id = created.json()["asset"]["id"]

    processed = client.post("/api/v1/internal/worker/run-once")
    assert processed.status_code == 200
    assert processed.json()["processed"] is True

    ingestion = client.get(f"/api/v2/ingestions/{ingestion_id}")
    assert ingestion.status_code == 200
    assert ingestion.json()["status"] == "partial"
    assert any(
        "without transcript evidence" in warning.lower() for warning in ingestion.json()["warnings"]
    )

    storyboard = client.get(f"/api/v2/assets/{asset_id}/storyboard")
    assert storyboard.status_code == 200
    assert storyboard.json()["frames"]


class BlockingMediaProcessor:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancel_observed = threading.Event()

    def extract(self, raw: bytes, *, mime_type: str, name: str, cancelled=None):
        del raw, mime_type, name
        self.started.set()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if cancelled is not None and cancelled():
                self.cancel_observed.set()
                raise RuntimeError("media processing cancelled")
            time.sleep(0.01)
        raise RuntimeError("test media processor did not observe cancellation")


def test_running_media_cancellation_prevents_publication(repository, tmp_path: Path) -> None:
    blobs = FilesystemBlobStore(str(tmp_path / "cancel-blobs"))
    staged = tmp_path / "cancel.wav"
    staged.write_bytes(_wav_bytes())
    admitted = AssetAdmissionService(
        repository,
        blobs,
        max_upload_bytes=2_000_000,
        max_audio_bytes=2_000_000,
        audio_enabled=True,
        audio_ready=lambda: True,
    ).admit_staged(path=staged, name="cancel.wav", supplied_mime="audio/wav")
    lease = repository.claim_next_ingestion()
    assert lease is not None
    processor = BlockingMediaProcessor()
    executor = _executor(repository, blobs, processor)  # type: ignore[arg-type]
    errors: list[BaseException] = []

    def run() -> None:
        try:
            executor.execute(lease)
        except BaseException as exc:  # executor may surface the intentional cancellation
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert processor.started.wait(timeout=1.0)
    cancelled = repository.request_ingestion_cancel(admitted.ingestion.id)
    assert cancelled.cancellation_requested is True
    thread.join(timeout=3.0)

    assert not thread.is_alive()
    assert processor.cancel_observed.is_set()
    final = repository.get_ingestion(admitted.ingestion.id)
    assert final.status.value == "cancelled"
    assert final.document_id is None
    assert repository.get_media_storyboard(admitted.asset.id).frames == []
    # Cancellation is a terminal user action, not an ingestion failure.
    assert errors == []


def test_cancelled_media_asset_can_be_deleted_without_a_document(
    repository, tmp_path: Path
) -> None:
    blobs = FilesystemBlobStore(str(tmp_path / "delete-cancelled-blobs"))
    staged = tmp_path / "delete-cancelled.wav"
    staged.write_bytes(_wav_bytes())
    admitted = AssetAdmissionService(
        repository,
        blobs,
        max_upload_bytes=2_000_000,
        max_audio_bytes=2_000_000,
        audio_enabled=True,
        audio_ready=lambda: True,
    ).admit_staged(path=staged, name="delete-cancelled.wav", supplied_mime="audio/wav")
    asset = repository.get_asset_record(admitted.asset.id)
    repository.request_ingestion_cancel(admitted.ingestion.id)

    blob_keys = repository.delete_asset_with_blobs(admitted.asset.id)
    assert asset.original_blob_key in blob_keys
    for blob_key in blob_keys:
        blobs.delete(blob_key)

    with pytest.raises(NotFoundError):
        repository.get_asset_record(admitted.asset.id)
    with pytest.raises(NotFoundError):
        repository.get_ingestion(admitted.ingestion.id)
    with pytest.raises(FileNotFoundError):
        blobs.get_bytes(asset.original_blob_key)


def test_deleting_running_media_asset_fences_publication(repository, tmp_path: Path) -> None:
    blobs = FilesystemBlobStore(str(tmp_path / "delete-running-blobs"))
    staged = tmp_path / "delete-running.wav"
    staged.write_bytes(_wav_bytes())
    admitted = AssetAdmissionService(
        repository,
        blobs,
        max_upload_bytes=2_000_000,
        max_audio_bytes=2_000_000,
        audio_enabled=True,
        audio_ready=lambda: True,
    ).admit_staged(path=staged, name="delete-running.wav", supplied_mime="audio/wav")
    asset = repository.get_asset_record(admitted.asset.id)
    lease = repository.claim_next_ingestion()
    assert lease is not None
    processor = BlockingMediaProcessor()
    executor = _executor(repository, blobs, processor)  # type: ignore[arg-type]

    thread = threading.Thread(target=lambda: _swallow_executor_error(executor, lease))
    thread.start()
    assert processor.started.wait(timeout=1.0)

    blob_keys = repository.delete_asset_with_blobs(admitted.asset.id)
    for blob_key in blob_keys:
        blobs.delete(blob_key)
    thread.join(timeout=3.0)

    assert not thread.is_alive()
    with pytest.raises(NotFoundError):
        repository.get_asset_record(admitted.asset.id)
    with pytest.raises(NotFoundError):
        repository.get_ingestion(admitted.ingestion.id)
    with pytest.raises(FileNotFoundError):
        blobs.get_bytes(asset.original_blob_key)


def _swallow_executor_error(executor: AssetIngestionExecutor, lease) -> None:
    try:
        executor.execute(lease)
    except Exception:
        # Deleting the authoritative ingestion record is an intentional hard fence.
        # The assertion in the test is that the worker terminates and cannot publish.
        return
