# ruff: noqa: F403, F405, E501
from fastapi import APIRouter, Request, HTTPException
from ares.api.dependencies import *
from ares.domain.models import *
from ares.domain.assets import *
from ares.domain.visualizations import *
import logging

from ares.application.engine import DemoResearchEngine
from ares.adapters.docling_parser import DoclingSubprocessParser
from ares.adapters.faster_whisper import FasterWhisperSubprocessTranscriber
from ares.application.media_ingestion import FFmpegMediaProcessor
from ares.application.asset_ingestion import AssetIngestionExecutor, BuiltinRichExtractor

from ares.application.indexing import DocumentEmbeddingIndexer

logger = logging.getLogger('ares.api')
router = APIRouter()

@router.post('/api/v1/internal/worker/run-once', include_in_schema=False)
def run_once(*, request: Request) -> dict[str, object]:
    repository = request.app.state.repository
    cfg = request.app.state.settings
    blobs = request.app.state.blobs
    local_media_runtime = getattr(request.app.state, 'local_media_runtime', None)
    pdf_parser = request.app.state.pdf_parser

    if cfg.ares_mode != 'demo':
        raise HTTPException(status_code=403, detail='worker hook is demo-only')
    lease = repository.claim_next_job()
    if lease is not None:
        run_id = lease.run_id
        research = DemoResearchEngine(repository)
        research.execute(lease)
        repository.finish_job(lease)
        return {'processed': True, 'kind': 'research', 'run_id': str(run_id)}
    
    ingestion_lease = repository.claim_next_ingestion(max_attempts=cfg.max_job_attempts)
    if ingestion_lease is None:
        return {'processed': False}
    
    rich_parser = None
    if cfg.rich_parser_enabled:
        rich_parser = DoclingSubprocessParser(timeout_seconds=cfg.docling_timeout_seconds, max_bytes=cfg.max_upload_bytes, max_pages=cfg.max_rich_pdf_pages, language=cfg.ocr_language, model_cache_dir=cfg.docling_model_cache_dir)
    
    media_processor = None
    local_media = local_media_runtime()
    media_processor_ready = cfg.audio_enabled and local_media.transcription_ready or (cfg.video_enabled and local_media.video_processing_ready)
    if media_processor_ready:
        transcriber = FasterWhisperSubprocessTranscriber(model_path=cfg.whisper_model_path, model_revision=cfg.whisper_model_revision, compute_type=cfg.whisper_compute_type, cpu_threads=cfg.whisper_cpu_threads, beam_size=cfg.whisper_beam_size, language=cfg.whisper_language or None, timeout_seconds=cfg.whisper_timeout_seconds, subprocess_memory_mb=cfg.media_subprocess_memory_mb, subprocess_cpu_seconds=cfg.media_subprocess_cpu_seconds) if local_media.transcription_ready else None
        media_processor = FFmpegMediaProcessor(transcriber, ffmpeg_binary=cfg.ffmpeg_path, ffprobe_binary=cfg.ffprobe_path, max_audio_duration_seconds=cfg.max_audio_duration_seconds, max_video_duration_seconds=cfg.max_video_duration_seconds, max_video_source_pixels=cfg.max_video_source_pixels, max_selected_frames=cfg.max_video_frames, baseline_frames=cfg.video_baseline_frames, scene_threshold=cfg.video_scene_threshold, timeout_seconds=cfg.media_process_timeout_seconds, subprocess_memory_mb=cfg.media_subprocess_memory_mb, subprocess_cpu_seconds=cfg.media_subprocess_cpu_seconds)
    
    media = AssetIngestionExecutor(repository, blobs, BuiltinRichExtractor(pdf_parser, max_csv_rows=cfg.max_csv_rows, max_table_cells=cfg.max_table_cells, max_cell_chars=cfg.max_cell_chars), DocumentEmbeddingIndexer(repository, None, model_id='', dimensions=cfg.local_embedding_dimensions), rich_parser=rich_parser, ocr_enabled=cfg.ocr_enabled, media_processor=media_processor, max_frame_ocr_frames=cfg.video_frame_ocr_limit, max_image_pixels=cfg.max_image_pixels, max_table_cells=cfg.max_table_cells)
    media.execute(ingestion_lease)
    return {'processed': True, 'kind': 'ingestion', 'ingestion_id': str(ingestion_lease.ingestion_id)}
