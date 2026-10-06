from sqlalchemy import text
import importlib.util
from typing import Annotated, Any
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Response, HTTPException, Query, UploadFile, File, Header
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from ares.api.dependencies import *
from ares.domain.models import *
from ares.domain.assets import *
from ares.domain.visualizations import *
from ares.application.auth import AuthenticationError
from ares.application.repository import NotFoundError, IdempotencyConflictError, RunAdmissionError
from ares.application.asset_ingestion import AssetAdmissionError
from ares.application.exports import ExportError
from ares.application.visualizations import VisualizationExportError
from ares.application.identity import Principal
import asyncio
import tempfile
import os
from pathlib import Path
import httpx
import logging
logger = logging.getLogger('ares.api')
router = APIRouter()

@router.get('/health/live')
def live(*, request: Request) -> dict[str, str]:
    repository = request.app.state.repository
    cfg = request.app.state.settings
    auth_store = getattr(request.app.state, 'auth_store', None)
    oidc = getattr(request.app.state, 'oidc', None)
    blobs = request.app.state.blobs
    asset_admission = getattr(request.app.state, 'asset_admission', None)
    documents = getattr(request.app.state, 'documents', None)
    exports = getattr(request.app.state, 'exports', None)
    visualizations = getattr(request.app.state, 'visualizations', None)
    engine = getattr(request.app.state, 'db_engine', None)
    local_media_runtime = getattr(request.app.state, 'local_media_runtime', None)
    return {'status': 'ok'}

@router.get('/health/ready')
def ready(*, request: Request) -> dict[str, str]:
    repository = request.app.state.repository
    cfg = request.app.state.settings
    auth_store = getattr(request.app.state, 'auth_store', None)
    oidc = getattr(request.app.state, 'oidc', None)
    blobs = request.app.state.blobs
    asset_admission = getattr(request.app.state, 'asset_admission', None)
    documents = getattr(request.app.state, 'documents', None)
    exports = getattr(request.app.state, 'exports', None)
    visualizations = getattr(request.app.state, 'visualizations', None)
    engine = getattr(request.app.state, 'db_engine', None)
    local_media_runtime = getattr(request.app.state, 'local_media_runtime', None)
    try:
        with engine.connect() as connection:
            connection.execute(text('select 1'))
            if cfg.deployment_environment == 'production':
                revision = connection.scalar(text('SELECT version_num FROM alembic_version LIMIT 1'))
                if revision != cfg.required_schema_revision:
                    raise RuntimeError(f'database schema revision {revision!r} does not match required {cfg.required_schema_revision!r}')
        if cfg.ares_mode == 'local_live':
            cfg.validate_live_mode()
        if cfg.readiness_requires_worker:
            profiles = repository.get_worker_profiles(stale_seconds=cfg.worker_stale_seconds)
            if profiles['research'] + profiles['combined'] < 1:
                raise RuntimeError('no active research-capable worker is available')
        return {'status': 'ready', 'mode': cfg.ares_mode}
    except Exception as exc:
        raise HTTPException(status_code=503, detail={'code': 'NOT_READY', 'message': str(exc)}) from exc

@router.get('/api/v1/system/status')
def system_status(*, request: Request) -> dict[str, object]:
    repository = request.app.state.repository
    cfg = request.app.state.settings
    auth_store = getattr(request.app.state, 'auth_store', None)
    oidc = getattr(request.app.state, 'oidc', None)
    blobs = request.app.state.blobs
    asset_admission = getattr(request.app.state, 'asset_admission', None)
    documents = getattr(request.app.state, 'documents', None)
    exports = getattr(request.app.state, 'exports', None)
    visualizations = getattr(request.app.state, 'visualizations', None)
    engine = getattr(request.app.state, 'db_engine', None)
    local_media_runtime = getattr(request.app.state, 'local_media_runtime', None)
    postgres = cfg.database_url.startswith('postgresql')
    if cfg.local_embeddings_enabled or cfg.gemini_embeddings_enabled:
        retrieval_backend = 'postgresql+pgvector-exact' if postgres else 'sqlite-persisted-vector-exact'
    else:
        retrieval_backend = 'persisted-lexical'
    fleet = repository.get_worker_fleet(stale_seconds=cfg.worker_stale_seconds)
    worker_profiles = repository.get_worker_profiles(stale_seconds=cfg.worker_stale_seconds)
    worker_capabilities = repository.get_worker_capabilities(stale_seconds=cfg.worker_stale_seconds)
    media_ready = cfg.ares_mode == 'demo' or bool(worker_capabilities.get('ingestion', False))
    if cfg.ares_mode == 'demo':
        local_media = local_media_runtime()
        docling_ready = importlib.util.find_spec('docling') is not None
        fastembed_ready = importlib.util.find_spec('fastembed') is not None
        audio_ready = bool(cfg.audio_enabled and local_media.transcription_ready)
        video_ready = bool(cfg.video_enabled and local_media.video_processing_ready)
        rich_parser_ready = bool(cfg.rich_parser_enabled and docling_ready)
        ocr_ready = bool(cfg.rich_parser_enabled and cfg.ocr_enabled and docling_ready)
        local_embeddings_ready = bool(cfg.local_embeddings_enabled and fastembed_ready)
    else:
        audio_ready = bool(cfg.audio_enabled and worker_capabilities.get('audio', False))
        video_ready = bool(cfg.video_enabled and worker_capabilities.get('video', False))
        rich_parser_ready = bool(cfg.rich_parser_enabled and worker_capabilities.get('rich_parser', False))
        ocr_ready = bool(cfg.ocr_enabled and worker_capabilities.get('ocr', False))
        local_embeddings_ready = bool(cfg.local_embeddings_enabled and worker_capabilities.get('local_embeddings', False))
    return {'mode': cfg.ares_mode, 'deployment_environment': cfg.deployment_environment, 'auth_mode': cfg.auth_mode, 'worker_fleet': fleet, 'worker_profiles': worker_profiles, 'telemetry_export': telemetry_export_status(cfg.otel_exporter_otlp_endpoint), 'strict_free_mode': cfg.strict_free_mode, 'billable_fallback_allowed': cfg.allow_billable_providers, 'gemini_model': cfg.gemini_model if cfg.ares_mode == 'local_live' else None, 'retrieval_backend': retrieval_backend, 'visualizations': {'enabled': cfg.visualizations_enabled, 'ready': visualization_storage_ready(cfg, engine), 'max_graph_nodes': cfg.visualization_graph_max_nodes, 'max_graph_edges': cfg.visualization_graph_max_edges}, 'ingestion': {'enabled': cfg.async_ingestion_enabled, 'ready': cfg.async_ingestion_enabled and media_ready, 'accepted_mime_types': ['application/pdf', 'text/csv', *(['image/png', 'image/jpeg', 'image/webp'] if cfg.rich_parser_enabled and cfg.ocr_enabled else []), *(['audio/wav', 'audio/mpeg', 'audio/mp4', 'audio/webm', 'audio/ogg'] if cfg.audio_enabled else []), *(['video/mp4', 'video/webm'] if cfg.video_enabled else [])], 'max_upload_bytes': cfg.max_upload_bytes, 'max_image_bytes': cfg.max_image_bytes, 'max_audio_bytes': cfg.max_audio_bytes, 'max_video_bytes': cfg.max_video_bytes, 'max_audio_duration_seconds': cfg.max_audio_duration_seconds, 'max_video_duration_seconds': cfg.max_video_duration_seconds, 'max_video_frames': cfg.max_video_frames, 'audio_ready': audio_ready, 'video_ready': video_ready, 'microphone_enabled': bool(cfg.microphone_enabled and audio_ready), 'max_image_pixels': cfg.max_image_pixels, 'max_pdf_pages': cfg.max_rich_pdf_pages, 'max_csv_rows': cfg.max_csv_rows, 'max_table_cells': cfg.max_table_cells}, 'tools': {'gemini': {'configured': cfg.ares_mode == 'local_live' and bool(cfg.gemini_api_key), 'metered': True}, 'searxng': {'configured': bool(cfg.searxng_url), 'metered': False}, 'openalex': {'configured': True, 'authenticated': bool(cfg.openalex_api_key), 'metered': False}, 'crossref': {'configured': True, 'polite_pool': bool(cfg.crossref_mailto), 'metered': False}, 'arxiv': {'configured': True, 'metered': False}, 'github': {'configured': True, 'authenticated': bool(cfg.github_read_token), 'metered': False}, 'gemini_embeddings': {'configured': cfg.gemini_embeddings_enabled, 'metered': False}, 'local_embeddings': {'configured': cfg.local_embeddings_enabled, 'ready': local_embeddings_ready, 'metered': False}, 'rich_parser': {'configured': cfg.rich_parser_enabled, 'ready': rich_parser_ready, 'metered': False}, 'ocr': {'configured': cfg.ocr_enabled, 'ready': ocr_ready, 'metered': False}, 'audio_transcription': {'configured': cfg.audio_enabled, 'ready': audio_ready, 'degraded': cfg.audio_enabled and (not audio_ready), 'metered': False}, 'video_sampling': {'configured': cfg.video_enabled, 'ready': video_ready, 'degraded': cfg.video_enabled and (not video_ready), 'metered': False}, 'jev': {'configured': cfg.jev_enabled, 'metered': True}}}
def telemetry_export_status(endpoint: str | None) -> dict[str, str]:
    if not endpoint:
        return {"status": "disabled", "endpoint": "none"}
    if "localhost" in endpoint or "127.0.0.1" in endpoint:
        return {"status": "local", "endpoint": endpoint}
    return {"status": "remote", "endpoint": "***"}
