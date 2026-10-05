from __future__ import annotations

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
from ares.domain.assets import (
    AssetAdmission,
    AssetView,
    IngestionView,
    MediaStoryboardView,
    SegmentView,
    TableView,
)
from ares.domain.models import (
    ArtifactView,
    ConversationCreate,
    ConversationView,
    DocumentTextCreate,
    DocumentView,
    EvidenceView,
    ExportCreate,
    RunCreate,
    RunSnapshot,
    RunQualityView,
    AuthMeView,
    WorkspaceSwitchRequest,
    WorkspaceView,
    WorkerFleetView,
)
from ares.domain.visualizations import VisualizationView


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(json_logs=cfg.json_logs)
    logger = logging.getLogger("ares.api")
    telemetry_shutdown = configure_telemetry(
        endpoint=cfg.otel_exporter_otlp_endpoint, service_name=f"{cfg.otel_service_name}-api",
        sample_ratio=cfg.otel_trace_sample_ratio, export_timeout_seconds=cfg.otel_export_timeout_seconds,
    )
    Path(".data").mkdir(exist_ok=True)
    engine, sessions = build_session_factory(cfg.database_url)
    if cfg.ares_mode == "demo" and cfg.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    repository = Repository(sessions)
    auth_store = AuthStore(sessions)
    oidc = None
    if cfg.auth_mode == "oidc":
        cfg.validate_security_mode()
        oidc = OidcClient(
            issuer=cfg.oidc_issuer, client_id=cfg.oidc_client_id, client_secret=cfg.oidc_client_secret,
            redirect_uri=f"{cfg.public_base_url.rstrip('/')}/api/v1/auth/callback", scopes=cfg.oidc_scopes,
            state_ttl_seconds=cfg.oidc_state_ttl_seconds, session_ttl_hours=cfg.session_ttl_hours, store=auth_store,
        )
    blobs = FilesystemBlobStore(cfg.blob_root)
    pdf_parser = BoundedPdfParser(
        max_bytes=cfg.max_upload_bytes,
        max_pages=cfg.max_pdf_pages,
        timeout_seconds=cfg.pdf_parse_timeout_seconds,
    )
    documents = DocumentIngestService(repository, blobs, pdf_parser)
    def local_media_runtime():
        return probe_local_media_runtime(
            ffmpeg_binary=cfg.ffmpeg_path,
            ffprobe_binary=cfg.ffprobe_path,
            whisper_model_path=cfg.whisper_model_path,
        )

    def media_capability_ready(capability: str) -> bool:
        if cfg.ares_mode == "demo":
            local_media = local_media_runtime()
            if capability == "audio":
                return local_media.transcription_ready
            if capability == "video":
                return local_media.video_processing_ready
            return False
        return bool(
            repository.get_worker_capabilities(stale_seconds=cfg.worker_stale_seconds).get(
                capability, False
            )
        )

    asset_admission = AssetAdmissionService(
        repository,
        blobs,
        max_upload_bytes=cfg.max_upload_bytes,
        max_image_bytes=cfg.max_image_bytes,
        max_audio_bytes=cfg.max_audio_bytes,
        max_video_bytes=cfg.max_video_bytes,
        audio_enabled=cfg.audio_enabled,
        video_enabled=cfg.video_enabled,
        audio_ready=lambda: media_capability_ready("audio"),
        video_ready=lambda: media_capability_ready("video"),
        cloud_media_enabled=cfg.cloud_media_enabled,
    )
    exports = ExportService(repository, blobs)
    visualizations = VisualizationService(
        repository,
        max_graph_nodes=cfg.visualization_graph_max_nodes,
        max_graph_edges=cfg.visualization_graph_max_edges,
    )

    def visualization_storage_ready() -> bool:
        if not cfg.visualizations_enabled:
            return False
        try:
            inspector = inspect(engine)
            return inspector.has_table("visualization_datasets") and inspector.has_table("visualizations")
        except Exception:
            return False

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if oidc is not None:
            await oidc.close()
        await asyncio.to_thread(telemetry_shutdown)
        await asyncio.to_thread(engine.dispose)

    app = FastAPI(title="ARES API", version="0.11.0", lifespan=lifespan)
    app.state.settings = cfg
    app.state.repository = repository
    app.state.db_engine = engine
    app.state.blobs = blobs
    app.add_middleware(
        PathAwareRequestBodyLimitMiddleware,
        default_max_body_size=cfg.max_request_body_bytes,
        path_max_body_sizes={"/api/v2/assets": cfg.max_asset_request_body_bytes},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(dict.fromkeys([cfg.frontend_origin, "http://127.0.0.1:5173", "http://localhost:5173"])) if cfg.deployment_environment == "local" else [cfg.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key", "Last-Event-ID", "X-Request-ID", "X-CSRF-Token", "Range"],
        expose_headers=["X-Request-ID", "X-Idempotent-Replay", "Retry-After", "Accept-Ranges", "Content-Range", "Content-Length"],
    )
    if cfg.deployment_environment == "production":
        public_host = urlsplit(cfg.public_base_url).hostname
        if not public_host:
            raise ValueError("PUBLIC_BASE_URL must contain a hostname in production")
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[public_host])

    public_paths = {"/health/live", "/health/ready", "/api/v1/auth/login", "/api/v1/auth/callback"}

    def _origin(value: str) -> str:
        parsed = urlsplit(value)
        return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""

    allowed_mutation_origins = {_origin(cfg.frontend_origin), _origin(cfg.public_base_url)} - {""}

    @app.middleware("http")
    async def authentication_boundary(request: Request, call_next):
        path = request.url.path
        principal: Principal | None = None
        browser_session = None
        if request.method == "OPTIONS":
            return await call_next(request)
        if cfg.auth_mode == "disabled":
            principal = local_principal()
        elif path.startswith("/api/") and path not in public_paths:
            browser_session = auth_store.resolve_session(request.cookies.get(cfg.session_cookie_name, ""))
            if browser_session is None:
                return JSONResponse(status_code=401, content={"detail": {"code": "AUTH_REQUIRED", "message": "sign in required"}})
            principal = browser_session.principal
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                origin = request.headers.get("origin", "")
                csrf_header = request.headers.get("x-csrf-token", "")
                csrf_cookie = request.cookies.get(cfg.csrf_cookie_name, "")
                if origin not in allowed_mutation_origins:
                    return JSONResponse(status_code=403, content={"detail": {"code": "CSRF_ORIGIN", "message": "mutation origin rejected"}})
                if not csrf_header or csrf_header != csrf_cookie or _sha256(csrf_header) != browser_session.csrf_hash:
                    return JSONResponse(status_code=403, content={"detail": {"code": "CSRF_TOKEN", "message": "CSRF token rejected"}})
                if path not in {"/api/v1/auth/logout", "/api/v1/auth/workspace"} and not principal.can_write:
                    return JSONResponse(status_code=403, content={"detail": {"code": "ROLE_FORBIDDEN", "message": "workspace role is read-only"}})
        request.state.principal = principal
        request.state.browser_session = browser_session
        if principal is None:
            return await call_next(request)
        with principal_scope(principal):
            return await call_next(request)

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "").strip()
        request_id = incoming if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", incoming) else str(uuid4())
        started = time.perf_counter()
        status = 500
        with request_context(request_id):
            try:
                response = await call_next(request)
                status = response.status_code
            except Exception:
                logger.exception(
                    "request failed",
                    extra={
                        "event": "http.request",
                        "fields": {"method": request.method, "path": request.url.path, "status": 500},
                    },
                )
                raise
            finally:
                logger.info(
                    "request completed",
                    extra={
                        "event": "http.request",
                        "fields": {
                            "method": request.method,
                            "path": request.url.path,
                            "status": status,
                            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                        },
                    },
                )
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", f"camera=(), microphone={'(self)' if cfg.microphone_enabled else '()'}, geolocation=()")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        if request.url.path.startswith("/api/v1/auth/"):
            response.headers.setdefault("Cache-Control", "no-store")
        if request.url.path.startswith("/api/") or request.url.path.startswith("/health/"):
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        else:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "font-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'self'; "
                "frame-ancestors 'none'; form-action 'self'",
            )
        if cfg.deployment_environment == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.get("/api/v1/auth/login")
    async def auth_login(return_path: str = "/") -> RedirectResponse:
        if oidc is None:
            raise HTTPException(status_code=404, detail={"code": "AUTH_DISABLED", "message": "OIDC is disabled"})
        try:
            url = await oidc.begin_login(return_path)
        except (AuthenticationError, httpx.HTTPError) as exc:
            raise HTTPException(status_code=503, detail={"code": "OIDC_UNAVAILABLE", "message": str(exc)}) from exc
        return RedirectResponse(url, status_code=302)

    @app.get("/api/v1/auth/callback")
    async def auth_callback(code: str, state: str) -> RedirectResponse:
        if oidc is None:
            raise HTTPException(status_code=404, detail={"code": "AUTH_DISABLED", "message": "OIDC is disabled"})
        try:
            result = await oidc.complete_login(code=code, state=state)
        except (AuthenticationError, httpx.HTTPError) as exc:
            auth_store.audit(None, "auth.login_failed", metadata={"reason": type(exc).__name__})
            raise HTTPException(status_code=401, detail={"code": "OIDC_LOGIN_FAILED", "message": str(exc)}) from exc
        response = RedirectResponse(f"{cfg.frontend_origin.rstrip('/')}{result.return_path}", status_code=303)
        response.set_cookie(
            cfg.session_cookie_name, result.session_token, httponly=True, secure=cfg.session_cookie_secure,
            samesite="lax", path="/", max_age=cfg.session_ttl_hours * 3600,
        )
        response.set_cookie(
            cfg.csrf_cookie_name, result.csrf_token, httponly=False, secure=cfg.session_cookie_secure,
            samesite="lax", path="/", max_age=cfg.session_ttl_hours * 3600,
        )
        return response

    @app.get("/api/v1/auth/me", response_model=AuthMeView)
    def auth_me(request: Request) -> AuthMeView:
        principal: Principal = request.state.principal
        return AuthMeView(
            user_id=principal.user_id, workspace_id=principal.workspace_id, role=principal.role.value,
            subject=principal.subject, email=principal.email, display_name=principal.display_name,
            auth_mode=cfg.auth_mode, csrf_required=cfg.auth_mode == "oidc",
        )

    @app.get("/api/v1/workspaces", response_model=list[WorkspaceView])
    def list_workspaces(request: Request) -> list[WorkspaceView]:
        principal: Principal = request.state.principal
        if cfg.auth_mode == "disabled":
            return [WorkspaceView(id=principal.workspace_id, name="Local workspace", role=principal.role.value)]
        return [WorkspaceView.model_validate(item) for item in auth_store.list_workspaces(principal)]

    @app.post("/api/v1/auth/workspace", response_model=AuthMeView)
    def switch_workspace(payload: WorkspaceSwitchRequest, request: Request) -> AuthMeView:
        principal: Principal = request.state.principal
        if cfg.auth_mode == "disabled":
            raise HTTPException(status_code=409, detail={"code": "AUTH_DISABLED", "message": "local mode has one workspace"})
        try:
            updated = auth_store.switch_workspace(principal, payload.workspace_id)
        except AuthenticationError as exc:
            raise HTTPException(status_code=404, detail={"code": "WORKSPACE_NOT_FOUND", "message": str(exc)}) from exc
        return AuthMeView(
            user_id=updated.user_id, workspace_id=updated.workspace_id, role=updated.role.value,
            subject=updated.subject, email=updated.email, display_name=updated.display_name,
            auth_mode=cfg.auth_mode, csrf_required=True,
        )

    @app.post("/api/v1/auth/logout", status_code=204)
    def auth_logout(request: Request) -> Response:
        principal: Principal = request.state.principal
        if cfg.auth_mode == "oidc":
            auth_store.revoke_session(principal)
        response = Response(status_code=204)
        response.delete_cookie(cfg.session_cookie_name, path="/")
        response.delete_cookie(cfg.csrf_cookie_name, path="/")
        return response

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> dict[str, str]:
        try:
            with engine.connect() as connection:
                connection.execute(text("select 1"))
                if cfg.deployment_environment == "production":
                    revision = connection.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
                    if revision != cfg.required_schema_revision:
                        raise RuntimeError(
                            f"database schema revision {revision!r} does not match required {cfg.required_schema_revision!r}"
                        )
            if cfg.ares_mode == "local_live":
                cfg.validate_live_mode()
            if cfg.readiness_requires_worker:
                profiles = repository.get_worker_profiles(stale_seconds=cfg.worker_stale_seconds)
                if profiles["research"] + profiles["combined"] < 1:
                    raise RuntimeError("no active research-capable worker is available")
            return {"status": "ready", "mode": cfg.ares_mode}
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"code": "NOT_READY", "message": str(exc)}) from exc

    @app.get("/api/v1/system/status")
    def system_status() -> dict[str, object]:
        postgres = cfg.database_url.startswith("postgresql")
        if cfg.local_embeddings_enabled or cfg.gemini_embeddings_enabled:
            retrieval_backend = "postgresql+pgvector-exact" if postgres else "sqlite-persisted-vector-exact"
        else:
            retrieval_backend = "persisted-lexical"
        fleet = repository.get_worker_fleet(stale_seconds=cfg.worker_stale_seconds)
        worker_profiles = repository.get_worker_profiles(stale_seconds=cfg.worker_stale_seconds)
        worker_capabilities = repository.get_worker_capabilities(stale_seconds=cfg.worker_stale_seconds)
        media_ready = (
            cfg.ares_mode == "demo"
            or bool(worker_capabilities.get("ingestion", False))
        )
        if cfg.ares_mode == "demo":
            local_media = local_media_runtime()
            docling_ready = importlib.util.find_spec("docling") is not None
            fastembed_ready = importlib.util.find_spec("fastembed") is not None
            audio_ready = bool(cfg.audio_enabled and local_media.transcription_ready)
            video_ready = bool(cfg.video_enabled and local_media.video_processing_ready)
            rich_parser_ready = bool(cfg.rich_parser_enabled and docling_ready)
            ocr_ready = bool(cfg.rich_parser_enabled and cfg.ocr_enabled and docling_ready)
            local_embeddings_ready = bool(cfg.local_embeddings_enabled and fastembed_ready)
        else:
            audio_ready = bool(cfg.audio_enabled and worker_capabilities.get("audio", False))
            video_ready = bool(cfg.video_enabled and worker_capabilities.get("video", False))
            rich_parser_ready = bool(
                cfg.rich_parser_enabled and worker_capabilities.get("rich_parser", False)
            )
            ocr_ready = bool(cfg.ocr_enabled and worker_capabilities.get("ocr", False))
            local_embeddings_ready = bool(
                cfg.local_embeddings_enabled and worker_capabilities.get("local_embeddings", False)
            )
        return {
            "mode": cfg.ares_mode,
            "deployment_environment": cfg.deployment_environment,
            "auth_mode": cfg.auth_mode,
            "worker_fleet": fleet,
            "worker_profiles": worker_profiles,
            "telemetry_export": telemetry_export_status(cfg.otel_exporter_otlp_endpoint),
            "strict_free_mode": cfg.strict_free_mode,
            "billable_fallback_allowed": cfg.allow_billable_providers,
            "gemini_model": cfg.gemini_model if cfg.ares_mode == "local_live" else None,
            "retrieval_backend": retrieval_backend,
            "visualizations": {
                "enabled": cfg.visualizations_enabled,
                "ready": visualization_storage_ready(),
                "max_graph_nodes": cfg.visualization_graph_max_nodes,
                "max_graph_edges": cfg.visualization_graph_max_edges,
            },
            "ingestion": {
                "enabled": cfg.async_ingestion_enabled,
                "ready": cfg.async_ingestion_enabled and media_ready,
                "accepted_mime_types": [
                    "application/pdf",
                    "text/csv",
                    *(["image/png", "image/jpeg", "image/webp"] if cfg.rich_parser_enabled and cfg.ocr_enabled else []),
                    *(["audio/wav", "audio/mpeg", "audio/mp4", "audio/webm", "audio/ogg"] if cfg.audio_enabled else []),
                    *(["video/mp4", "video/webm"] if cfg.video_enabled else []),
                ],
                "max_upload_bytes": cfg.max_upload_bytes,
                "max_image_bytes": cfg.max_image_bytes,
                "max_audio_bytes": cfg.max_audio_bytes,
                "max_video_bytes": cfg.max_video_bytes,
                "max_audio_duration_seconds": cfg.max_audio_duration_seconds,
                "max_video_duration_seconds": cfg.max_video_duration_seconds,
                "max_video_frames": cfg.max_video_frames,
                "audio_ready": audio_ready,
                "video_ready": video_ready,
                "microphone_enabled": bool(cfg.microphone_enabled and audio_ready),
                "max_image_pixels": cfg.max_image_pixels,
                "max_pdf_pages": cfg.max_rich_pdf_pages,
                "max_csv_rows": cfg.max_csv_rows,
                "max_table_cells": cfg.max_table_cells,
            },
            "tools": {
                "gemini": {
                    "configured": cfg.ares_mode == "local_live" and bool(cfg.gemini_api_key),
                    "metered": True,
                },
                "searxng": {"configured": bool(cfg.searxng_url), "metered": False},
                "openalex": {"configured": True, "authenticated": bool(cfg.openalex_api_key), "metered": False},
                "crossref": {"configured": True, "polite_pool": bool(cfg.crossref_mailto), "metered": False},
                "arxiv": {"configured": True, "metered": False},
                "github": {"configured": True, "authenticated": bool(cfg.github_read_token), "metered": False},
                "gemini_embeddings": {"configured": cfg.gemini_embeddings_enabled, "metered": False},
                "local_embeddings": {
                    "configured": cfg.local_embeddings_enabled,
                    "ready": local_embeddings_ready,
                    "metered": False,
                },
                "rich_parser": {
                    "configured": cfg.rich_parser_enabled,
                    "ready": rich_parser_ready,
                    "metered": False,
                },
                "ocr": {
                    "configured": cfg.ocr_enabled,
                    "ready": ocr_ready,
                    "metered": False,
                },
                "audio_transcription": {
                    "configured": cfg.audio_enabled,
                    "ready": audio_ready,
                    "degraded": cfg.audio_enabled and not audio_ready,
                    "metered": False,
                },
                "video_sampling": {
                    "configured": cfg.video_enabled,
                    "ready": video_ready,
                    "degraded": cfg.video_enabled and not video_ready,
                    "metered": False,
                },
                "jev": {"configured": cfg.jev_enabled, "metered": True},
            },
        }

    @app.post("/api/v1/conversations", response_model=ConversationView, status_code=201)
    def create_conversation(payload: ConversationCreate) -> ConversationView:
        return repository.create_conversation(payload.title)

    @app.get("/api/v1/conversations", response_model=list[ConversationView])
    def list_conversations() -> list[ConversationView]:
        return repository.list_conversations()

    @app.get("/api/v1/conversations/{conversation_id}/runs", response_model=list[RunSnapshot])
    def list_conversation_runs(conversation_id: UUID) -> list[RunSnapshot]:
        try:
            return repository.list_runs_for_conversation(conversation_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.get("/api/v2/assets", response_model=list[AssetView])
    def list_assets(limit: int = Query(default=100, ge=1, le=500)) -> list[AssetView]:
        return repository.list_assets(limit=limit)

    @app.post("/api/v2/assets", response_model=AssetAdmission, status_code=202)
    async def create_asset(file: Annotated[UploadFile, File(...)]) -> AssetAdmission:
        if not cfg.async_ingestion_enabled:
            raise HTTPException(
                status_code=503,
                detail={"code": "ASYNC_INGESTION_DISABLED", "message": "rich asset ingestion is disabled"},
            )
        name = Path(file.filename or "asset").name.strip()[:240] or "asset"
        supplied = file.content_type or "application/octet-stream"
        temporary_path: str | None = None
        received = 0
        try:
            with tempfile.NamedTemporaryFile(prefix="ares-upload-", suffix=".stage", delete=False) as staged:
                temporary_path = staged.name
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    max_asset_bytes = max(
                        cfg.max_upload_bytes,
                        cfg.max_audio_bytes if cfg.audio_enabled else 0,
                        cfg.max_video_bytes if cfg.video_enabled else 0,
                    )
                    if received > max_asset_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail={"code": "UPLOAD_TOO_LARGE", "message": "asset exceeds the configured upload limit"},
                        )
                    staged.write(chunk)
                staged.flush()
                os.fsync(staged.fileno())
            try:
                return await asyncio.to_thread(
                    asset_admission.admit_staged,
                    path=Path(temporary_path),
                    name=name,
                    supplied_mime=supplied,
                )
            except AssetAdmissionError as exc:
                message = str(exc)
                status = 415 if "unsupported file type" in message or "signature" in message else 422
                raise HTTPException(
                    status_code=status,
                    detail={"code": "ASSET_ADMISSION_REJECTED", "message": message},
                ) from exc
        finally:
            if temporary_path:
                try:
                    Path(temporary_path).unlink(missing_ok=True)
                except OSError:
                    logger.exception("failed to remove staged upload")

    @app.delete("/api/v2/assets/{asset_id}", status_code=204)
    async def delete_asset(asset_id: UUID) -> Response:
        try:
            blob_keys = await asyncio.to_thread(repository.delete_asset_with_blobs, asset_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
        for blob_key in blob_keys:
            await asyncio.to_thread(blobs.delete, blob_key)
        return Response(status_code=204)

    @app.get("/api/v2/ingestions", response_model=list[IngestionView])
    def list_ingestions(limit: int = Query(default=100, ge=1, le=500)) -> list[IngestionView]:
        return repository.list_ingestions(limit=limit)

    @app.get("/api/v2/ingestions/{ingestion_id}", response_model=IngestionView)
    def get_ingestion(ingestion_id: UUID) -> IngestionView:
        try:
            return repository.get_ingestion(ingestion_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.post("/api/v2/ingestions/{ingestion_id}/cancel", response_model=IngestionView, status_code=202)
    def cancel_ingestion(ingestion_id: UUID) -> IngestionView:
        try:
            return repository.request_ingestion_cancel(ingestion_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.post("/api/v2/ingestions/{ingestion_id}/retry", response_model=IngestionView, status_code=202)
    def retry_ingestion(ingestion_id: UUID) -> IngestionView:
        try:
            return repository.retry_ingestion(ingestion_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "INGESTION_NOT_RETRYABLE", "message": str(exc)}) from exc

    @app.get("/api/v2/ingestions/{ingestion_id}/events")
    async def ingestion_events(
        ingestion_id: UUID, request: Request, after: int | None = Query(default=None, ge=0)
    ) -> StreamingResponse:
        try:
            repository.get_ingestion(ingestion_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
        header = request.headers.get("last-event-id")
        try:
            header_cursor = max(0, int(header)) if header else 0
        except ValueError:
            header_cursor = 0
        cursor = max(header_cursor, after or 0)
        principal: Principal | None = request.state.principal
        session_token = request.cookies.get(cfg.session_cookie_name, "")

        def revalidate_ingestion() -> bool:
            if cfg.auth_mode == "disabled":
                return True
            if principal is None or not session_token:
                return False
            resolved = auth_store.resolve_session(session_token)
            return bool(
                resolved is not None
                and resolved.principal.session_id == principal.session_id
                and resolved.principal.user_id == principal.user_id
                and resolved.principal.workspace_id == principal.workspace_id
            )

        generator = stream_ingestion_events(
            repository=repository,
            ingestion_id=ingestion_id,
            request=request,
            principal=principal,
            after=cursor,
            revalidate=revalidate_ingestion,
            page_size=cfg.event_page_size,
            max_replay=cfg.event_max_replay,
            heartbeat_seconds=cfg.event_heartbeat_seconds,
            authorization_recheck_seconds=cfg.stream_authorization_recheck_seconds,
        )
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/v2/assets/{asset_id}/content")
    async def get_asset_content(asset_id: UUID, range_header: str | None = Header(default=None, alias="Range")) -> Response:
        try:
            asset = await asyncio.to_thread(repository.get_asset_record, asset_id)
            size = await asyncio.to_thread(blobs.get_size, asset.original_blob_key)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=410, detail={"code": "ASSET_GONE", "message": "asset bytes are unavailable"}) from exc
        base_headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{asset.original_name.replace(chr(34), "")}"',
            "Cache-Control": "private, no-store",
        }
        if not range_header:
            content = await asyncio.to_thread(blobs.get_bytes, asset.original_blob_key)
            return Response(content=content, media_type=asset.mime_type, headers={**base_headers, "Content-Length": str(len(content))})
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match or "," in range_header:
            raise HTTPException(status_code=416, detail={"code": "INVALID_RANGE", "message": "only one byte range is supported"})
        left, right = match.groups()
        if not left and not right:
            raise HTTPException(status_code=416, detail={"code": "INVALID_RANGE", "message": "invalid byte range"})
        if left:
            start = int(left)
            end = min(size - 1, int(right) if right else size - 1)
        else:
            suffix = int(right)
            if suffix <= 0:
                raise HTTPException(status_code=416, detail={"code": "INVALID_RANGE", "message": "invalid suffix range"})
            start = max(0, size - suffix)
            end = size - 1
        if start >= size or end < start:
            return Response(status_code=416, headers={**base_headers, "Content-Range": f"bytes */{size}"})
        content = await asyncio.to_thread(blobs.get_range, asset.original_blob_key, start, end)
        return Response(
            content=content,
            status_code=206,
            media_type=asset.mime_type,
            headers={
                **base_headers,
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(len(content)),
            },
        )

    @app.get("/api/v2/assets/{asset_id}/storyboard", response_model=MediaStoryboardView)
    @app.get(
        "/api/v2/assets/{asset_id}/timeline",
        response_model=MediaStoryboardView,
        include_in_schema=False,
    )
    def get_media_storyboard(asset_id: UUID) -> MediaStoryboardView:
        try:
            return repository.get_media_storyboard(asset_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.get("/api/v2/renditions/{rendition_id}/content")
    async def get_rendition_content(rendition_id: UUID) -> Response:
        try:
            rendition = await asyncio.to_thread(repository.get_rendition_record, rendition_id)
            content = await asyncio.to_thread(blobs.get_bytes, rendition.blob_key)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=410, detail={"code": "RENDITION_GONE", "message": "rendition bytes are unavailable"}) from exc
        return Response(
            content=content,
            media_type=rendition.mime_type,
            headers={
                "Content-Length": str(len(content)),
                "Cache-Control": "private, no-store",
                "Content-Disposition": "inline",
            },
        )

    @app.get("/api/v2/segments/{segment_id}", response_model=SegmentView)
    def get_segment(segment_id: UUID) -> SegmentView:
        try:
            return repository.get_segment(segment_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.get("/api/v2/segments/{segment_id}/table", response_model=TableView)
    def get_segment_table(segment_id: UUID) -> TableView:
        try:
            return repository.get_table_for_segment(segment_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.get("/api/v2/tables/{table_id}", response_model=TableView)
    def get_table(table_id: UUID) -> TableView:
        try:
            return repository.get_table(table_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.get("/api/v1/documents", response_model=list[DocumentView])
    def list_documents() -> list[DocumentView]:
        return repository.list_documents()

    @app.post("/api/v1/documents/text", response_model=DocumentView, status_code=201)
    async def create_text_document(payload: DocumentTextCreate) -> DocumentView:
        return await asyncio.to_thread(documents.ingest_text, payload)

    @app.post("/api/v1/documents/pdf", response_model=DocumentView, status_code=201)
    async def create_pdf_document(file: Annotated[UploadFile, File(...)]) -> DocumentView:
        name = Path(file.filename or "document.pdf").name.strip()[:255] or "document.pdf"
        if file.content_type not in {None, "", "application/pdf", "application/octet-stream"}:
            raise HTTPException(
                status_code=415,
                detail={"code": "UNSUPPORTED_MEDIA_TYPE", "message": "PDF upload must use application/pdf"},
            )
        chunks: list[bytes] = []
        received = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > cfg.max_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail={"code": "UPLOAD_TOO_LARGE", "message": "PDF exceeds the configured upload limit"},
                )
            chunks.append(chunk)
        raw = b"".join(chunks)
        try:
            return await asyncio.to_thread(documents.ingest_pdf, name=name, raw=raw)
        except PdfParseError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "PDF_PARSE_FAILED", "message": str(exc)},
            ) from exc

    @app.delete("/api/v1/documents/{document_id}", status_code=204)
    async def delete_document(document_id: UUID) -> Response:
        try:
            blob_keys = await asyncio.to_thread(repository.delete_document_with_blobs, document_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
        for blob_key in blob_keys:
            await asyncio.to_thread(blobs.delete, blob_key)
        return Response(status_code=204)

    @app.post("/api/v1/runs", response_model=RunSnapshot, status_code=202)
    def create_run(
        payload: RunCreate, response: Response, idempotency_key: str = Header(..., alias="Idempotency-Key")
    ) -> RunSnapshot:
        try:
            snapshot, created = repository.create_run(
                payload, idempotency_key=idempotency_key, max_active_runs=cfg.max_active_runs,
                max_active_runs_per_workspace=cfg.max_active_runs_per_workspace,
                max_active_runs_per_user=cfg.max_active_runs_per_user,
            )
        except RunAdmissionError as exc:
            raise HTTPException(
                status_code=429,
                detail={"code": "RUN_CAPACITY_REACHED", "message": str(exc)},
                headers={"Retry-After": "5"},
            ) from exc
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
        except IdempotencyConflictError as exc:
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": str(exc)}) from exc
        if not created:
            response.headers["X-Idempotent-Replay"] = "true"
        return snapshot

    @app.get("/api/v1/runs/{run_id}", response_model=RunSnapshot)
    def get_run(run_id: UUID) -> RunSnapshot:
        try:
            return repository.get_run(run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.get("/api/v1/runs/{run_id}/evidence", response_model=list[EvidenceView])
    def list_run_evidence(run_id: UUID) -> list[EvidenceView]:
        try:
            return repository.list_run_evidence(run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.get("/api/v1/runs/{run_id}/quality", response_model=RunQualityView)
    def get_run_quality(run_id: UUID) -> RunQualityView:
        try:
            return repository.get_run_quality(run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.get("/api/v2/runs/{run_id}/visualizations", response_model=list[VisualizationView])
    def get_run_visualizations(run_id: UUID) -> list[VisualizationView]:
        if not cfg.visualizations_enabled:
            return []
        if not visualization_storage_ready():
            raise HTTPException(
                status_code=503,
                detail={"code": "VISUALIZATIONS_NOT_READY", "message": "Visualization storage is not migrated or reachable."},
            )
        try:
            return visualizations.list_for_run(run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.get(
        "/api/v2/runs/{run_id}/visualizations/{visualization_id}/export.csv",
        response_class=Response,
        responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}, "description": "Lineage-bearing CSV export"}},
    )
    def export_run_visualization_csv(run_id: UUID, visualization_id: UUID) -> Response:
        if not cfg.visualizations_enabled:
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "visualization not found"},
            )
        if not visualization_storage_ready():
            raise HTTPException(
                status_code=503,
                detail={"code": "VISUALIZATIONS_NOT_READY", "message": "Visualization storage is not migrated or reachable."},
            )
        try:
            filename, content = visualizations.export_csv(run_id, visualization_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
        except VisualizationExportError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "VISUALIZATION_EXPORT_UNAVAILABLE", "message": str(exc)},
            ) from exc
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/api/v1/runs/{run_id}/cancel", response_model=RunSnapshot, status_code=202)
    def cancel_run(run_id: UUID) -> RunSnapshot:
        try:
            return repository.request_cancel(run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.get("/api/v1/evidence/{evidence_id}", response_model=EvidenceView)
    def get_evidence(evidence_id: UUID) -> EvidenceView:
        try:
            return repository.get_evidence(evidence_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    @app.post("/api/v1/runs/{run_id}/exports", response_model=ArtifactView, status_code=201)
    async def create_export(run_id: UUID, payload: ExportCreate) -> ArtifactView:
        try:
            return await asyncio.to_thread(exports.create, run_id, payload)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
        except ExportError as exc:
            raise HTTPException(status_code=409, detail={"code": "EXPORT_NOT_READY", "message": str(exc)}) from exc

    @app.get("/api/v1/artifacts/{artifact_id}")
    async def download_artifact(artifact_id: UUID) -> Response:
        try:
            record = await asyncio.to_thread(repository.get_artifact_record, artifact_id)
            content = await asyncio.to_thread(blobs.get_bytes, record.blob_key)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=410, detail={"code": "ARTIFACT_GONE", "message": "artifact bytes are unavailable"}) from exc
        return Response(
            content=content,
            media_type=record.content_type,
            headers={"Content-Disposition": f'attachment; filename="{record.file_name}"'},
        )

    @app.get("/api/v1/runs/{run_id}/events")
    async def events(
        run_id: UUID, request: Request, after: int | None = Query(default=None, ge=0)
    ) -> StreamingResponse:
        try:
            repository.get_run(run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
        header = request.headers.get("last-event-id")
        try:
            header_cursor = max(0, int(header)) if header else 0
        except ValueError:
            header_cursor = 0
        cursor = max(header_cursor, after or 0)
        principal: Principal | None = request.state.principal
        session_token = request.cookies.get(cfg.session_cookie_name, "")

        def revalidate() -> bool:
            if cfg.auth_mode == "disabled":
                return True
            if principal is None or not session_token:
                return False
            resolved = auth_store.resolve_session(session_token)
            return bool(
                resolved is not None
                and resolved.principal.session_id == principal.session_id
                and resolved.principal.user_id == principal.user_id
                and resolved.principal.workspace_id == principal.workspace_id
            )

        generator = stream_run_events(
            repository=repository, run_id=run_id, request=request, principal=principal, after=cursor,
            revalidate=revalidate, page_size=cfg.event_page_size, max_replay=cfg.event_max_replay,
            heartbeat_seconds=cfg.event_heartbeat_seconds,
            authorization_recheck_seconds=cfg.stream_authorization_recheck_seconds,
        )
        return StreamingResponse(
            generator, media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/v1/internal/worker/run-once", include_in_schema=False)
    def run_once() -> dict[str, object]:
        if cfg.ares_mode != "demo":
            raise HTTPException(status_code=403, detail="worker hook is demo-only")
        lease = repository.claim_next_job()
        if lease is not None:
            run_id = lease.run_id
            research = DemoResearchEngine(repository)
            research.execute(lease)
            repository.finish_job(lease)
            return {"processed": True, "kind": "research", "run_id": str(run_id)}
        ingestion_lease = repository.claim_next_ingestion(max_attempts=cfg.max_job_attempts)
        if ingestion_lease is None:
            return {"processed": False}
        rich_parser = None
        if cfg.rich_parser_enabled:
            rich_parser = DoclingSubprocessParser(
                timeout_seconds=cfg.docling_timeout_seconds,
                max_bytes=cfg.max_upload_bytes,
                max_pages=cfg.max_rich_pdf_pages,
                language=cfg.ocr_language,
                model_cache_dir=cfg.docling_model_cache_dir,
            )
        media_processor = None
        local_media = local_media_runtime()
        media_processor_ready = (
            (cfg.audio_enabled and local_media.transcription_ready)
            or (cfg.video_enabled and local_media.video_processing_ready)
        )
        if media_processor_ready:
            transcriber = (
                FasterWhisperSubprocessTranscriber(
                    model_path=cfg.whisper_model_path,
                    model_revision=cfg.whisper_model_revision,
                    compute_type=cfg.whisper_compute_type,
                    cpu_threads=cfg.whisper_cpu_threads,
                    beam_size=cfg.whisper_beam_size,
                    language=cfg.whisper_language or None,
                    timeout_seconds=cfg.whisper_timeout_seconds,
                    subprocess_memory_mb=cfg.media_subprocess_memory_mb,
                    subprocess_cpu_seconds=cfg.media_subprocess_cpu_seconds,
                )
                if local_media.transcription_ready
                else None
            )
            media_processor = FFmpegMediaProcessor(
                transcriber,
                ffmpeg_binary=cfg.ffmpeg_path,
                ffprobe_binary=cfg.ffprobe_path,
                max_audio_duration_seconds=cfg.max_audio_duration_seconds,
                max_video_duration_seconds=cfg.max_video_duration_seconds,
                max_video_source_pixels=cfg.max_video_source_pixels,
                max_selected_frames=cfg.max_video_frames,
                baseline_frames=cfg.video_baseline_frames,
                scene_threshold=cfg.video_scene_threshold,
                timeout_seconds=cfg.media_process_timeout_seconds,
                subprocess_memory_mb=cfg.media_subprocess_memory_mb,
                subprocess_cpu_seconds=cfg.media_subprocess_cpu_seconds,
            )
        media = AssetIngestionExecutor(
            repository,
            blobs,
            BuiltinRichExtractor(pdf_parser, max_csv_rows=cfg.max_csv_rows, max_table_cells=cfg.max_table_cells, max_cell_chars=cfg.max_cell_chars),
            DocumentEmbeddingIndexer(repository, None, model_id="", dimensions=cfg.local_embedding_dimensions),
            rich_parser=rich_parser,
            ocr_enabled=cfg.ocr_enabled,
            media_processor=media_processor,
            max_frame_ocr_frames=cfg.video_frame_ocr_limit,
            max_image_pixels=cfg.max_image_pixels,
            max_table_cells=cfg.max_table_cells,
        )
        media.execute(ingestion_lease)
        return {"processed": True, "kind": "ingestion", "ingestion_id": str(ingestion_lease.ingestion_id)}

    if cfg.web_dist_dir:
        web_root = Path(cfg.web_dist_dir)
        if web_root.is_dir():
            app.mount("/", SpaStaticFiles(directory=web_root, html=True), name="web")

    return app


app = create_app()
