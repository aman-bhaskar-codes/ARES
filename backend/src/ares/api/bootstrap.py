from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ares.adapters.db import Base, build_session_factory
from ares.adapters.filesystem_blob import FilesystemBlobStore
from ares.adapters.pdf_parser import BoundedPdfParser
from ares.api.body_limit import PathAwareRequestBodyLimitMiddleware
from ares.api.settings import Settings, get_settings
from ares.application.asset_ingestion import AssetAdmissionService
from ares.application.auth import AuthStore, OidcClient, _sha256
from ares.application.documents import DocumentIngestService
from ares.application.exports import ExportService
from ares.application.identity import Principal, local_principal, principal_scope
from ares.application.media_capabilities import probe_local_media_runtime
from ares.application.observability import configure_logging, configure_telemetry, request_context
from ares.application.repository import Repository
from ares.application.visualizations import VisualizationService
from ares.version import VERSION


def create_application(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    cfg.validate_security_mode()
    configure_logging(json_logs=cfg.json_logs)
    logger = logging.getLogger("ares.api")
    telemetry_shutdown = configure_telemetry(
        endpoint=cfg.otel_exporter_otlp_endpoint,
        service_name=f"{cfg.otel_service_name}-api",
        sample_ratio=cfg.otel_trace_sample_ratio,
        export_timeout_seconds=cfg.otel_export_timeout_seconds,
    )
    Path(".data").mkdir(exist_ok=True)
    engine, sessions = build_session_factory(cfg.database_url)
    if cfg.ares_mode == "demo" and cfg.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    repository = Repository(sessions)
    auth_store = AuthStore(sessions)
    oidc = None
    if cfg.auth_mode == "oidc":
        oidc = OidcClient(
            issuer=cfg.oidc_issuer,
            client_id=cfg.oidc_client_id,
            client_secret=cfg.oidc_client_secret,
            redirect_uri=f"{cfg.public_base_url.rstrip('/')}/api/v1/auth/callback",
            scopes=cfg.oidc_scopes,
            state_ttl_seconds=cfg.oidc_state_ttl_seconds,
            session_ttl_hours=cfg.session_ttl_hours,
            store=auth_store,
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
            return inspector.has_table("visualization_datasets") and inspector.has_table(
                "visualizations"
            )
        except Exception as _boundary_error:
            logging.getLogger(__name__).warning("bootstrap: recovery boundary (%s)", type(_boundary_error).__name__)
            return False

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if oidc is not None:
            await oidc.close()
        await asyncio.to_thread(telemetry_shutdown)
        await asyncio.to_thread(engine.dispose)

    app = FastAPI(
        title="ARES API",
        version=VERSION,
        lifespan=lifespan,
        docs_url=None if cfg.deployment_environment == "production" else "/docs",
        redoc_url=None if cfg.deployment_environment == "production" else "/redoc",
        openapi_url=None if cfg.deployment_environment == "production" else "/openapi.json",
    )
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
    app.add_middleware(
        PathAwareRequestBodyLimitMiddleware,
        default_max_body_size=cfg.max_request_body_bytes,
        path_max_body_sizes={"/api/v2/assets": cfg.max_asset_request_body_bytes},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(
            dict.fromkeys([cfg.frontend_origin, "http://127.0.0.1:5173", "http://localhost:5173"])
        )
        if cfg.deployment_environment == "local"
        else [cfg.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=[
            "Content-Type",
            "Idempotency-Key",
            "Last-Event-ID",
            "X-Request-ID",
            "X-CSRF-Token",
            "Range",
        ],
        expose_headers=[
            "X-Request-ID",
            "X-Idempotent-Replay",
            "Retry-After",
            "Accept-Ranges",
            "Content-Range",
            "Content-Length",
        ],
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
            browser_session = auth_store.resolve_session(
                request.cookies.get(cfg.session_cookie_name, "")
            )
            if browser_session is None:
                return JSONResponse(
                    status_code=401,
                    content={"detail": {"code": "AUTH_REQUIRED", "message": "sign in required"}},
                )
            principal = browser_session.principal
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                origin = request.headers.get("origin", "")
                csrf_header = request.headers.get("x-csrf-token", "")
                csrf_cookie = request.cookies.get(cfg.csrf_cookie_name, "")
                if origin not in allowed_mutation_origins:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": {"code": "CSRF_ORIGIN", "message": "mutation origin rejected"}
                        },
                    )
                if (
                    not csrf_header
                    or csrf_header != csrf_cookie
                    or _sha256(csrf_header) != browser_session.csrf_hash
                ):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": {"code": "CSRF_TOKEN", "message": "CSRF token rejected"}
                        },
                    )
                if path not in {"/api/v1/auth/logout", "/api/v1/auth/workspace"} and (
                    not principal.can_write
                ):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": {
                                "code": "ROLE_FORBIDDEN",
                                "message": "workspace role is read-only",
                            }
                        },
                    )
        request.state.principal = principal
        request.state.browser_session = browser_session
        if principal is None:
            return await call_next(request)
        with principal_scope(principal):
            return await call_next(request)

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "").strip()
        request_id = incoming if re.fullmatch("[A-Za-z0-9._:-]{1,128}", incoming) else str(uuid4())
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
                        "fields": {
                            "method": request.method,
                            "path": request.url.path,
                            "status": 500,
                        },
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
        response.headers.setdefault(
            "Permissions-Policy",
            f"camera=(), microphone={('(self)' if cfg.microphone_enabled else '()')}, geolocation=()",
        )
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        if request.url.path.startswith("/api/v1/auth/"):
            response.headers.setdefault("Cache-Control", "no-store")
        if request.url.path.startswith("/api/") or request.url.path.startswith("/health/"):
            response.headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
        else:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
            )
        if cfg.deployment_environment == "production":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    return app
