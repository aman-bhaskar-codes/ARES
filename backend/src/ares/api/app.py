from __future__ import annotations
from ares.api.routers import (
    auth as auth_router,
    system as system_router,
    conversations as conversations_router,
    assets as assets_router,
    ingestions as ingestions_router,
    segments as segments_router,
    documents as documents_router,
    runs as runs_router,
    evidence as evidence_router,
    artifacts as artifacts_router,
    internal as internal_router,
)











import asyncio
import importlib.util
import httpx
import logging
import re
import time
import os
import tempfile
from uuid import UUID, uuid4
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit
from fastapi import FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import inspect, text
from ares.adapters.db import Base, build_session_factory
from ares.adapters.filesystem_blob import FilesystemBlobStore
from ares.adapters.pdf_parser import BoundedPdfParser, PdfParseError
from ares.api.settings import Settings, get_settings
from ares.api.body_limit import PathAwareRequestBodyLimitMiddleware
from ares.api.event_stream import stream_run_events
from ares.api.ingestion_stream import stream_ingestion_events
from ares.application.observability import configure_logging, configure_telemetry, request_context, telemetry_export_status
from ares.application.auth import AuthStore, AuthenticationError, OidcClient, _sha256
from ares.application.identity import Principal, local_principal, principal_scope
from ares.api.spa_static import SpaStaticFiles
from ares.application.documents import DocumentIngestService
from ares.application.asset_ingestion import AssetAdmissionError, AssetAdmissionService, AssetIngestionExecutor, BuiltinRichExtractor
from ares.application.indexing import DocumentEmbeddingIndexer
from ares.application.media_capabilities import probe_local_media_runtime
from ares.application.media_ingestion import FFmpegMediaProcessor
from ares.adapters.docling_parser import DoclingSubprocessParser
from ares.adapters.faster_whisper import FasterWhisperSubprocessTranscriber
from ares.application.engine import DemoResearchEngine
from ares.application.exports import ExportError, ExportService
from ares.application.visualizations import VisualizationExportError, VisualizationService
from ares.application.repository import IdempotencyConflictError, NotFoundError, Repository, RunAdmissionError
from ares.domain.assets import AssetAdmission, AssetView, IngestionView, MediaStoryboardView, SegmentView, TableView
from ares.domain.models import ArtifactView, ConversationCreate, ConversationView, DocumentTextCreate, DocumentView, EvidenceView, ExportCreate, RunCreate, RunSnapshot, RunQualityView, AuthMeView, WorkspaceSwitchRequest, WorkspaceView
from ares.domain.visualizations import VisualizationView

def create_app(settings: Settings | None=None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(json_logs=cfg.json_logs)
    logger = logging.getLogger('ares.api')
    telemetry_shutdown = configure_telemetry(endpoint=cfg.otel_exporter_otlp_endpoint, service_name=f'{cfg.otel_service_name}-api', sample_ratio=cfg.otel_trace_sample_ratio, export_timeout_seconds=cfg.otel_export_timeout_seconds)
    Path('.data').mkdir(exist_ok=True)
    engine, sessions = build_session_factory(cfg.database_url)
    if cfg.ares_mode == 'demo' and cfg.database_url.startswith('sqlite'):
        Base.metadata.create_all(engine)
    repository = Repository(sessions)
    auth_store = AuthStore(sessions)
    oidc = None
    if cfg.auth_mode == 'oidc':
        cfg.validate_security_mode()
        oidc = OidcClient(issuer=cfg.oidc_issuer, client_id=cfg.oidc_client_id, client_secret=cfg.oidc_client_secret, redirect_uri=f"{cfg.public_base_url.rstrip('/')}/api/v1/auth/callback", scopes=cfg.oidc_scopes, state_ttl_seconds=cfg.oidc_state_ttl_seconds, session_ttl_hours=cfg.session_ttl_hours, store=auth_store)
    blobs = FilesystemBlobStore(cfg.blob_root)
    pdf_parser = BoundedPdfParser(max_bytes=cfg.max_upload_bytes, max_pages=cfg.max_pdf_pages, timeout_seconds=cfg.pdf_parse_timeout_seconds)
    documents = DocumentIngestService(repository, blobs, pdf_parser)

    def local_media_runtime():
        return probe_local_media_runtime(ffmpeg_binary=cfg.ffmpeg_path, ffprobe_binary=cfg.ffprobe_path, whisper_model_path=cfg.whisper_model_path)

    def media_capability_ready(capability: str) -> bool:
        if cfg.ares_mode == 'demo':
            local_media = local_media_runtime()
            if capability == 'audio':
                return local_media.transcription_ready
            if capability == 'video':
                return local_media.video_processing_ready
            return False
        return bool(repository.get_worker_capabilities(stale_seconds=cfg.worker_stale_seconds).get(capability, False))
    asset_admission = AssetAdmissionService(repository, blobs, max_upload_bytes=cfg.max_upload_bytes, max_image_bytes=cfg.max_image_bytes, max_audio_bytes=cfg.max_audio_bytes, max_video_bytes=cfg.max_video_bytes, audio_enabled=cfg.audio_enabled, video_enabled=cfg.video_enabled, audio_ready=lambda: media_capability_ready('audio'), video_ready=lambda: media_capability_ready('video'), cloud_media_enabled=cfg.cloud_media_enabled)
    exports = ExportService(repository, blobs)
    visualizations = VisualizationService(repository, max_graph_nodes=cfg.visualization_graph_max_nodes, max_graph_edges=cfg.visualization_graph_max_edges)

    def visualization_storage_ready() -> bool:
        if not cfg.visualizations_enabled:
            return False
        try:
            inspector = inspect(engine)
            return inspector.has_table('visualization_datasets') and inspector.has_table('visualizations')
        except Exception:
            return False

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if oidc is not None:
            await oidc.close()
        await asyncio.to_thread(telemetry_shutdown)
        await asyncio.to_thread(engine.dispose)
    app = FastAPI(title='ARES API', version='0.11.0', lifespan=lifespan)
    app.state.settings = cfg
    app.state.repository = repository
    app.state.db_engine = engine
    app.state.blobs = blobs
    app.state.auth_store = auth_store
    app.state.oidc = oidc
    app.state.documents = documents
    app.state.asset_admission = asset_admission
    app.state.exports = exports
    app.state.visualizations = visualizations
    app.state.local_media_runtime = local_media_runtime
    app.state.pdf_parser = pdf_parser
    app.add_middleware(PathAwareRequestBodyLimitMiddleware, default_max_body_size=cfg.max_request_body_bytes, path_max_body_sizes={'/api/v2/assets': cfg.max_asset_request_body_bytes})
    app.add_middleware(CORSMiddleware, allow_origins=list(dict.fromkeys([cfg.frontend_origin, 'http://127.0.0.1:5173', 'http://localhost:5173'])) if cfg.deployment_environment == 'local' else [cfg.frontend_origin], allow_credentials=True, allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type', 'Idempotency-Key', 'Last-Event-ID', 'X-Request-ID', 'X-CSRF-Token', 'Range'], expose_headers=['X-Request-ID', 'X-Idempotent-Replay', 'Retry-After', 'Accept-Ranges', 'Content-Range', 'Content-Length'])
    if cfg.deployment_environment == 'production':
        public_host = urlsplit(cfg.public_base_url).hostname
        if not public_host:
            raise ValueError('PUBLIC_BASE_URL must contain a hostname in production')
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[public_host])
    public_paths = {'/health/live', '/health/ready', '/api/v1/auth/login', '/api/v1/auth/callback'}

    def _origin(value: str) -> str:
        parsed = urlsplit(value)
        return f'{parsed.scheme}://{parsed.netloc}' if parsed.scheme and parsed.netloc else ''
    allowed_mutation_origins = {_origin(cfg.frontend_origin), _origin(cfg.public_base_url)} - {''}

    @app.middleware('http')
    async def authentication_boundary(request: Request, call_next):
        path = request.url.path
        principal: Principal | None = None
        browser_session = None
        if request.method == 'OPTIONS':
            return await call_next(request)
        if cfg.auth_mode == 'disabled':
            principal = local_principal()
        elif path.startswith('/api/') and path not in public_paths:
            browser_session = auth_store.resolve_session(request.cookies.get(cfg.session_cookie_name, ''))
            if browser_session is None:
                return JSONResponse(status_code=401, content={'detail': {'code': 'AUTH_REQUIRED', 'message': 'sign in required'}})
            principal = browser_session.principal
            if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
                origin = request.headers.get('origin', '')
                csrf_header = request.headers.get('x-csrf-token', '')
                csrf_cookie = request.cookies.get(cfg.csrf_cookie_name, '')
                if origin not in allowed_mutation_origins:
                    return JSONResponse(status_code=403, content={'detail': {'code': 'CSRF_ORIGIN', 'message': 'mutation origin rejected'}})
                if not csrf_header or csrf_header != csrf_cookie or _sha256(csrf_header) != browser_session.csrf_hash:
                    return JSONResponse(status_code=403, content={'detail': {'code': 'CSRF_TOKEN', 'message': 'CSRF token rejected'}})
                if path not in {'/api/v1/auth/logout', '/api/v1/auth/workspace'} and (not principal.can_write):
                    return JSONResponse(status_code=403, content={'detail': {'code': 'ROLE_FORBIDDEN', 'message': 'workspace role is read-only'}})
        request.state.principal = principal
        request.state.browser_session = browser_session
        if principal is None:
            return await call_next(request)
        with principal_scope(principal):
            return await call_next(request)

    @app.middleware('http')
    async def request_observability(request: Request, call_next):
        incoming = request.headers.get('x-request-id', '').strip()
        request_id = incoming if re.fullmatch('[A-Za-z0-9._:-]{1,128}', incoming) else str(uuid4())
        started = time.perf_counter()
        status = 500
        with request_context(request_id):
            try:
                response = await call_next(request)
                status = response.status_code
            except Exception:
                logger.exception('request failed', extra={'event': 'http.request', 'fields': {'method': request.method, 'path': request.url.path, 'status': 500}})
                raise
            finally:
                logger.info('request completed', extra={'event': 'http.request', 'fields': {'method': request.method, 'path': request.url.path, 'status': status, 'duration_ms': round((time.perf_counter() - started) * 1000, 3)}})
        response.headers['X-Request-ID'] = request_id
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Permissions-Policy', f"camera=(), microphone={('(self)' if cfg.microphone_enabled else '()')}, geolocation=()")
        response.headers.setdefault('Cross-Origin-Resource-Policy', 'same-site')
        response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
        response.headers.setdefault('X-Permitted-Cross-Domain-Policies', 'none')
        if request.url.path.startswith('/api/v1/auth/'):
            response.headers.setdefault('Cache-Control', 'no-store')
        if request.url.path.startswith('/api/') or request.url.path.startswith('/health/'):
            response.headers.setdefault('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
        else:
            response.headers.setdefault('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
        if cfg.deployment_environment == 'production':
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        return response

    @app.get('/api/v1/auth/login')
    async def auth_login(return_path: str='/') -> RedirectResponse:
        if oidc is None:
            raise HTTPException(status_code=404, detail={'code': 'AUTH_DISABLED', 'message': 'OIDC is disabled'})
        try:
            url = await oidc.begin_login(return_path)
        except (AuthenticationError, httpx.HTTPError) as exc:
            raise HTTPException(status_code=503, detail={'code': 'OIDC_UNAVAILABLE', 'message': str(exc)}) from exc
        return RedirectResponse(url, status_code=302)

    @app.get('/api/v1/auth/callback')
    async def auth_callback(code: str, state: str) -> RedirectResponse:
        if oidc is None:
            raise HTTPException(status_code=404, detail={'code': 'AUTH_DISABLED', 'message': 'OIDC is disabled'})
        try:
            result = await oidc.complete_login(code=code, state=state)
        except (AuthenticationError, httpx.HTTPError) as exc:
            auth_store.audit(None, 'auth.login_failed', metadata={'reason': type(exc).__name__})
            raise HTTPException(status_code=401, detail={'code': 'OIDC_LOGIN_FAILED', 'message': str(exc)}) from exc
        response = RedirectResponse(f"{cfg.frontend_origin.rstrip('/')}{result.return_path}", status_code=303)
        response.set_cookie(cfg.session_cookie_name, result.session_token, httponly=True, secure=cfg.session_cookie_secure, samesite='lax', path='/', max_age=cfg.session_ttl_hours * 3600)
        response.set_cookie(cfg.csrf_cookie_name, result.csrf_token, httponly=False, secure=cfg.session_cookie_secure, samesite='lax', path='/', max_age=cfg.session_ttl_hours * 3600)
        return response

    @app.post('/api/v2/assets', response_model=AssetAdmission, status_code=202)
    async def create_asset(file: Annotated[UploadFile, File(...)]) -> AssetAdmission:
        if not cfg.async_ingestion_enabled:
            raise HTTPException(status_code=503, detail={'code': 'ASYNC_INGESTION_DISABLED', 'message': 'rich asset ingestion is disabled'})
        name = Path(file.filename or 'asset').name.strip()[:240] or 'asset'
        supplied = file.content_type or 'application/octet-stream'
        temporary_path: str | None = None
        received = 0
        try:
            with tempfile.NamedTemporaryFile(prefix='ares-upload-', suffix='.stage', delete=False) as staged:
                temporary_path = staged.name
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    max_asset_bytes = max(cfg.max_upload_bytes, cfg.max_audio_bytes if cfg.audio_enabled else 0, cfg.max_video_bytes if cfg.video_enabled else 0)
                    if received > max_asset_bytes:
                        raise HTTPException(status_code=413, detail={'code': 'UPLOAD_TOO_LARGE', 'message': 'asset exceeds the configured upload limit'})
                    staged.write(chunk)
                staged.flush()
                os.fsync(staged.fileno())
            try:
                return await asyncio.to_thread(asset_admission.admit_staged, path=Path(temporary_path), name=name, supplied_mime=supplied)
            except AssetAdmissionError as exc:
                message = str(exc)
                status = 415 if 'unsupported file type' in message or 'signature' in message else 422
                raise HTTPException(status_code=status, detail={'code': 'ASSET_ADMISSION_REJECTED', 'message': message}) from exc
        finally:
            if temporary_path:
                try:
                    Path(temporary_path).unlink(missing_ok=True)
                except OSError:
                    logger.exception('failed to remove staged upload')

    @app.delete('/api/v2/assets/{asset_id}', status_code=204)
    async def delete_asset(asset_id: UUID) -> Response:
        try:
            blob_keys = await asyncio.to_thread(repository.delete_asset_with_blobs, asset_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
        for blob_key in blob_keys:
            await asyncio.to_thread(blobs.delete, blob_key)
        return Response(status_code=204)

    @app.get('/api/v2/ingestions/{ingestion_id}/events')
    async def ingestion_events(ingestion_id: UUID, request: Request, after: int | None=Query(default=None, ge=0)) -> StreamingResponse:
        try:
            repository.get_ingestion(ingestion_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
        header = request.headers.get('last-event-id')
        try:
            header_cursor = max(0, int(header)) if header else 0
        except ValueError:
            header_cursor = 0
        cursor = max(header_cursor, after or 0)
        principal: Principal | None = request.state.principal
        session_token = request.cookies.get(cfg.session_cookie_name, '')

        def revalidate_ingestion() -> bool:
            if cfg.auth_mode == 'disabled':
                return True
            if principal is None or not session_token:
                return False
            resolved = auth_store.resolve_session(session_token)
            return bool(resolved is not None and resolved.principal.session_id == principal.session_id and (resolved.principal.user_id == principal.user_id) and (resolved.principal.workspace_id == principal.workspace_id))
        generator = stream_ingestion_events(repository=repository, ingestion_id=ingestion_id, request=request, principal=principal, after=cursor, revalidate=revalidate_ingestion, page_size=cfg.event_page_size, max_replay=cfg.event_max_replay, heartbeat_seconds=cfg.event_heartbeat_seconds, authorization_recheck_seconds=cfg.stream_authorization_recheck_seconds)
        return StreamingResponse(generator, media_type='text/event-stream', headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})

    @app.get('/api/v2/assets/{asset_id}/content')
    async def get_asset_content(asset_id: UUID, range_header: str | None=Header(default=None, alias='Range')) -> Response:
        try:
            asset = await asyncio.to_thread(repository.get_asset_record, asset_id)
            size = await asyncio.to_thread(blobs.get_size, asset.original_blob_key)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=410, detail={'code': 'ASSET_GONE', 'message': 'asset bytes are unavailable'}) from exc
        base_headers = {'Accept-Ranges': 'bytes', 'Content-Disposition': f'''inline; filename="{asset.original_name.replace(chr(34), '')}"''', 'Cache-Control': 'private, no-store'}
        if not range_header:
            content = await asyncio.to_thread(blobs.get_bytes, asset.original_blob_key)
            return Response(content=content, media_type=asset.mime_type, headers={**base_headers, 'Content-Length': str(len(content))})
        match = re.fullmatch('bytes=(\\d*)-(\\d*)', range_header.strip())
        if not match or ',' in range_header:
            raise HTTPException(status_code=416, detail={'code': 'INVALID_RANGE', 'message': 'only one byte range is supported'})
        left, right = match.groups()
        if not left and (not right):
            raise HTTPException(status_code=416, detail={'code': 'INVALID_RANGE', 'message': 'invalid byte range'})
        if left:
            start = int(left)
            end = min(size - 1, int(right) if right else size - 1)
        else:
            suffix = int(right)
            if suffix <= 0:
                raise HTTPException(status_code=416, detail={'code': 'INVALID_RANGE', 'message': 'invalid suffix range'})
            start = max(0, size - suffix)
            end = size - 1
        if start >= size or end < start:
            return Response(status_code=416, headers={**base_headers, 'Content-Range': f'bytes */{size}'})
        content = await asyncio.to_thread(blobs.get_range, asset.original_blob_key, start, end)
        return Response(content=content, status_code=206, media_type=asset.mime_type, headers={**base_headers, 'Content-Range': f'bytes {start}-{end}/{size}', 'Content-Length': str(len(content))})

    @app.get('/api/v2/renditions/{rendition_id}/content')
    async def get_rendition_content(rendition_id: UUID) -> Response:
        try:
            rendition = await asyncio.to_thread(repository.get_rendition_record, rendition_id)
            content = await asyncio.to_thread(blobs.get_bytes, rendition.blob_key)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=410, detail={'code': 'RENDITION_GONE', 'message': 'rendition bytes are unavailable'}) from exc
        return Response(content=content, media_type=rendition.mime_type, headers={'Content-Length': str(len(content)), 'Cache-Control': 'private, no-store', 'Content-Disposition': 'inline'})

    @app.post('/api/v1/documents/text', response_model=DocumentView, status_code=201)
    async def create_text_document(payload: DocumentTextCreate) -> DocumentView:
        return await asyncio.to_thread(documents.ingest_text, payload)

    @app.post('/api/v1/documents/pdf', response_model=DocumentView, status_code=201)
    async def create_pdf_document(file: Annotated[UploadFile, File(...)]) -> DocumentView:
        name = Path(file.filename or 'document.pdf').name.strip()[:255] or 'document.pdf'
        if file.content_type not in {None, '', 'application/pdf', 'application/octet-stream'}:
            raise HTTPException(status_code=415, detail={'code': 'UNSUPPORTED_MEDIA_TYPE', 'message': 'PDF upload must use application/pdf'})
        chunks: list[bytes] = []
        received = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > cfg.max_upload_bytes:
                raise HTTPException(status_code=413, detail={'code': 'UPLOAD_TOO_LARGE', 'message': 'PDF exceeds the configured upload limit'})
            chunks.append(chunk)
        raw = b''.join(chunks)
        try:
            return await asyncio.to_thread(documents.ingest_pdf, name=name, raw=raw)
        except PdfParseError as exc:
            raise HTTPException(status_code=422, detail={'code': 'PDF_PARSE_FAILED', 'message': str(exc)}) from exc

    @app.delete('/api/v1/documents/{document_id}', status_code=204)
    async def delete_document(document_id: UUID) -> Response:
        try:
            blob_keys = await asyncio.to_thread(repository.delete_document_with_blobs, document_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
        for blob_key in blob_keys:
            await asyncio.to_thread(blobs.delete, blob_key)
        return Response(status_code=204)

    @app.post('/api/v1/runs/{run_id}/exports', response_model=ArtifactView, status_code=201)
    async def create_export(run_id: UUID, payload: ExportCreate) -> ArtifactView:
        try:
            return await asyncio.to_thread(exports.create, run_id, payload)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
        except ExportError as exc:
            raise HTTPException(status_code=409, detail={'code': 'EXPORT_NOT_READY', 'message': str(exc)}) from exc

    @app.get('/api/v1/artifacts/{artifact_id}')
    async def download_artifact(artifact_id: UUID) -> Response:
        try:
            record = await asyncio.to_thread(repository.get_artifact_record, artifact_id)
            content = await asyncio.to_thread(blobs.get_bytes, record.blob_key)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=410, detail={'code': 'ARTIFACT_GONE', 'message': 'artifact bytes are unavailable'}) from exc
        return Response(content=content, media_type=record.content_type, headers={'Content-Disposition': f'attachment; filename="{record.file_name}"'})

    @app.get('/api/v1/runs/{run_id}/events')
    async def events(run_id: UUID, request: Request, after: int | None=Query(default=None, ge=0)) -> StreamingResponse:
        try:
            repository.get_run(run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
        header = request.headers.get('last-event-id')
        try:
            header_cursor = max(0, int(header)) if header else 0
        except ValueError:
            header_cursor = 0
        cursor = max(header_cursor, after or 0)
        principal: Principal | None = request.state.principal
        session_token = request.cookies.get(cfg.session_cookie_name, '')

        def revalidate() -> bool:
            if cfg.auth_mode == 'disabled':
                return True
            if principal is None or not session_token:
                return False
            resolved = auth_store.resolve_session(session_token)
            return bool(resolved is not None and resolved.principal.session_id == principal.session_id and (resolved.principal.user_id == principal.user_id) and (resolved.principal.workspace_id == principal.workspace_id))
        generator = stream_run_events(repository=repository, run_id=run_id, request=request, principal=principal, after=cursor, revalidate=revalidate, page_size=cfg.event_page_size, max_replay=cfg.event_max_replay, heartbeat_seconds=cfg.event_heartbeat_seconds, authorization_recheck_seconds=cfg.stream_authorization_recheck_seconds)
        return StreamingResponse(generator, media_type='text/event-stream', headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})
    if cfg.web_dist_dir:
        web_root = Path(cfg.web_dist_dir)
        if web_root.is_dir():
            app.mount('/', SpaStaticFiles(directory=web_root, html=True), name='web')
    app.include_router(auth_router.router)
    app.include_router(system_router.router)
    app.include_router(conversations_router.router)
    app.include_router(assets_router.router)
    app.include_router(ingestions_router.router)
    app.include_router(segments_router.router)
    app.include_router(documents_router.router)
    app.include_router(runs_router.router)
    app.include_router(evidence_router.router)
    app.include_router(artifacts_router.router)
    app.include_router(internal_router.router)
    return app
app = create_app()