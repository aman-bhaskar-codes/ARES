from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ares_mode: Literal["demo", "local_live"] = "demo"
    deployment_environment: Literal["local", "production"] = "local"
    auth_mode: Literal["disabled", "oidc"] = "disabled"
    strict_free_mode: bool = True
    allow_billable_providers: bool = False
    database_url: str = "sqlite+pysqlite:///./.data/ares-dev.sqlite3"
    worker_database_url: str = ""
    blob_root: str = ".data/blobs"

    public_base_url: str = "http://127.0.0.1:8000"
    frontend_origin: str = "http://127.0.0.1:5173"
    session_cookie_name: str = "ares_session"
    csrf_cookie_name: str = "ares_csrf"
    session_cookie_secure: bool = False
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_state_ttl_seconds: int = Field(default=600, ge=60, le=1800)

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_thinking_level: Literal["low", "medium", "high"] = "low"
    gemini_rpm: int | None = Field(default=None, ge=1)
    gemini_tpm: int | None = Field(default=None, ge=1)
    gemini_rpd: int | None = Field(default=None, ge=1)
    gemini_concurrency: int = Field(default=1, ge=1, le=8)
    local_llm_enabled: bool = False
    local_llm_url: str = "http://127.0.0.1:11434"
    local_llm_model: str = "qwen3:4b"
    local_llm_timeout_seconds: float = Field(default=120.0, ge=5.0, le=120.0)
    gemini_timeout_seconds: float = Field(default=45.0, ge=5.0, le=120.0)
    gemini_billing_mode: Literal["free", "paid"] = "free"
    gemini_max_daily_spend_usd: float = Field(default=0.0, ge=0.0)
    searxng_url: str = "http://127.0.0.1:8080"
    max_http_concurrency: int = Field(default=4, ge=1, le=16)
    provider_http_timeout_seconds: float = Field(default=20.0, ge=2.0, le=120.0)
    source_fetch_timeout_seconds: float = Field(default=12.0, ge=2.0, le=120.0)

    # M10 live-research coordination. Cache records are workspace-scoped and never shared
    # across tenants. TTLs are deliberately bounded so cache reuse does not masquerade as a
    # fresh retrieval.
    discovery_concurrency: int = Field(default=3, ge=1, le=3)
    research_cache_enabled: bool = True
    web_search_cache_ttl_seconds: int = Field(default=3600, ge=30, le=86400)
    web_source_cache_ttl_seconds: int = Field(default=21600, ge=60, le=604800)
    academic_cache_ttl_seconds: int = Field(default=604800, ge=300, le=2592000)
    software_cache_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    academic_full_text_enabled: bool = True
    academic_full_text_limit: int = Field(default=2, ge=0, le=6)
    academic_full_text_timeout_seconds: float = Field(default=20.0, ge=2.0, le=60.0)
    academic_full_text_max_bytes: int = Field(
        default=20 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024
    )
    academic_full_text_max_pages: int = Field(default=100, ge=1, le=300)
    semantic_checker_enabled: bool = False
    semantic_checker_model: str = "gemini-3.8-flash"
    semantic_checker_max_claims: int = Field(default=6, ge=1, le=20)
    semantic_checker_timeout_seconds: float = Field(default=30.0, ge=5.0, le=90.0)
    # Browser rendering is an optional *external sandbox service*. Enabling this client does not
    # make an in-process Chromium safe; production must apply the documented sidecar network policy.
    browser_enabled: bool = False
    browser_service_url: str = "http://browser:8090"
    browser_service_token: str = ""
    browser_timeout_seconds: float = Field(default=20.0, ge=2.0, le=60.0)

    # M11 evidence-linked workspace visualizations. Visual artifacts are generated only from
    # persisted, authorized evidence and validated deterministic datasets.
    visualizations_enabled: bool = True
    visualization_graph_max_nodes: int = Field(default=100, ge=1, le=100)
    visualization_graph_max_edges: int = Field(default=200, ge=1, le=200)

    jev_enabled: bool = False
    jev_api_key: str = ""
    jev_model: str = "jev-latest"
    jev_base_url: str = "https://api.typesafe.ai"

    openalex_api_key: str = ""
    crossref_mailto: str = ""
    arxiv_min_interval_seconds: float = Field(default=3.0, ge=0.0, le=30.0)
    github_read_token: str = ""

    # M08/M09 document and media capability gates. Optional ML dependencies are intentionally
    # disabled by default so the V1 text research profile remains lightweight.
    async_ingestion_enabled: bool = True
    rich_parser_enabled: bool = False
    ocr_enabled: bool = False
    local_embeddings_enabled: bool = False
    local_embedding_model: str = "BAAI/bge-small-en-v1.5"
    local_embedding_dimensions: int = Field(default=384, ge=128, le=3072)
    local_embedding_cache_dir: str = ".data/models/fastembed"
    local_embedding_threads: int | None = Field(default=None, ge=1, le=32)
    local_embedding_batch_size: int = Field(default=32, ge=1, le=256)
    max_background_embed_chunks: int = Field(default=5_000, ge=1, le=50_000)
    docling_timeout_seconds: float = Field(default=120.0, ge=10.0, le=600.0)
    docling_model_cache_dir: str = ".data/models/docling"
    ocr_language: str = "iso:en"
    max_image_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    max_image_pixels: int = Field(default=20_000_000, ge=1_000_000, le=100_000_000)
    max_csv_rows: int = Field(default=5_000, ge=1, le=100_000)
    max_table_cells: int = Field(default=50_000, ge=1, le=1_000_000)
    max_cell_chars: int = Field(default=10_000, ge=128, le=100_000)

    # M09 local media evidence. Heavy decoders/ASR remain isolated in the media worker.
    audio_enabled: bool = False
    video_enabled: bool = False
    cloud_media_enabled: bool = False
    microphone_enabled: bool = False
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    media_process_timeout_seconds: float = Field(default=420.0, ge=10.0, le=900.0)
    media_subprocess_memory_mb: int = Field(default=3072, ge=512, le=32768)
    media_subprocess_cpu_seconds: int = Field(default=420, ge=10, le=1800)
    max_audio_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    max_audio_duration_seconds: int = Field(default=600, ge=1, le=3600)
    max_video_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)
    max_video_duration_seconds: int = Field(default=300, ge=1, le=1800)
    max_video_source_pixels: int = Field(default=12_000_000, ge=1_000_000, le=100_000_000)
    max_video_frames: int = Field(default=60, ge=2, le=240)
    video_baseline_frames: int = Field(default=31, ge=2, le=120)
    video_scene_threshold: float = Field(default=0.35, ge=0.05, le=0.95)
    video_frame_ocr_limit: int = Field(default=8, ge=0, le=60)
    whisper_model_path: str = ".data/models/whisper-small-ct2"
    whisper_model_revision: str = "small-multilingual-provisioned"
    whisper_compute_type: Literal["int8", "int8_float16", "float32"] = "int8"
    whisper_cpu_threads: int = Field(default=2, ge=1, le=32)
    whisper_beam_size: int = Field(default=5, ge=1, le=10)
    whisper_language: str = ""
    whisper_timeout_seconds: float = Field(default=360.0, ge=10.0, le=900.0)
    worker_profile: Literal["research", "media", "combined"] = "research"

    gemini_embeddings_enabled: bool = False
    gemini_embedding_model: str = "gemini-embedding-2"
    gemini_embedding_dimensions: int = Field(default=768, ge=128, le=3072)
    gemini_embedding_rpm: int | None = Field(default=None, ge=1)
    gemini_embedding_tpm: int | None = Field(default=None, ge=1)
    gemini_embedding_rpd: int | None = Field(default=None, ge=1)
    max_embed_chunks_per_run: int = Field(default=240, ge=1, le=1000)

    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)
    max_request_body_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    max_asset_request_body_bytes: int = Field(default=105 * 1024 * 1024, ge=1024)
    max_pdf_pages: int = Field(default=200, ge=1, le=1000)
    max_rich_pdf_pages: int = Field(default=100, ge=1, le=500)
    pdf_parse_timeout_seconds: float = Field(default=25.0, ge=2.0, le=120.0)

    json_logs: bool = True
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "ares"
    otel_trace_sample_ratio: float = Field(default=0.10, ge=0.0, le=1.0)
    otel_export_timeout_seconds: float = Field(default=3.0, ge=0.5, le=15.0)
    web_dist_dir: str = ""
    max_active_runs: int = Field(default=4, ge=1, le=64)
    max_active_runs_per_workspace: int = Field(default=3, ge=1, le=64)
    max_active_runs_per_user: int = Field(default=2, ge=1, le=32)
    max_job_attempts: int = Field(default=3, ge=1, le=20)
    worker_heartbeat_seconds: float = Field(default=10.0, ge=2.0, le=60.0)
    worker_stale_seconds: int = Field(default=45, ge=10, le=300)
    worker_health_file: str = ".data/worker-health"
    readiness_requires_worker: bool = False
    event_page_size: int = Field(default=100, ge=10, le=500)
    event_max_replay: int = Field(default=1000, ge=100, le=10_000)
    event_heartbeat_seconds: float = Field(default=15.0, ge=5.0, le=60.0)
    stream_authorization_recheck_seconds: float = Field(default=10.0, ge=2.0, le=15.0)
    required_schema_revision: str = "0013"

    @field_validator(
        "gemini_rpm",
        "gemini_tpm",
        "gemini_rpd",
        "gemini_embedding_rpm",
        "gemini_embedding_tpm",
        "gemini_embedding_rpd",
        mode="before",
    )
    @classmethod
    def blank_optional_quota_is_none(cls, value: str | int | None) -> str | int | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    def validate_live_mode(self) -> None:
        self.validate_security_mode()
        
        # Legacy normalization
        if not self.strict_free_mode and self.gemini_billing_mode == "free":
            self.gemini_billing_mode = "paid"
            
        if self.allow_billable_providers:
            raise ValueError("ARES strict-free mode refuses ALLOW_BILLABLE_PROVIDERS=true")
            
        if self.ares_mode != "local_live":
            return
            
        if not self.gemini_api_key and not self.local_llm_enabled:
            raise ValueError("Configure GEMINI_API_KEY or enable LOCAL_LLM_ENABLED for local_live mode")
        if self.gemini_api_key and None in {self.gemini_rpm, self.gemini_tpm, self.gemini_rpd}:
            raise ValueError("GEMINI_RPM, GEMINI_TPM and GEMINI_RPD must be explicit in live mode")
            
        if self.jev_enabled:
            raise ValueError(
                "Jev is a metered external service; ARES V3 policy rejects JEV_ENABLED=true. "
                "Only Gemini paid billing is permitted."
            )
        if self.gemini_embeddings_enabled and None in {
            self.gemini_embedding_rpm,
            self.gemini_embedding_tpm,
            self.gemini_embedding_rpd,
        }:
            raise ValueError(
                "GEMINI_EMBEDDING_RPM, GEMINI_EMBEDDING_TPM and GEMINI_EMBEDDING_RPD "
                "must be explicit when embeddings are enabled"
            )

    def validate_security_mode(self) -> None:
        if self.max_request_body_bytes < self.max_upload_bytes:
            raise ValueError("MAX_REQUEST_BODY_BYTES must be >= MAX_UPLOAD_BYTES")
        if self.max_image_bytes > self.max_upload_bytes:
            raise ValueError("MAX_IMAGE_BYTES must be <= MAX_UPLOAD_BYTES")
        required_asset_body = self.max_upload_bytes
        if self.audio_enabled:
            required_asset_body = max(required_asset_body, self.max_audio_bytes)
        if self.video_enabled:
            required_asset_body = max(required_asset_body, self.max_video_bytes)
        if self.max_asset_request_body_bytes < required_asset_body:
            raise ValueError(
                "MAX_ASSET_REQUEST_BODY_BYTES must cover every enabled asset upload type"
            )
        if (self.audio_enabled or self.video_enabled) and not self.async_ingestion_enabled:
            raise ValueError("AUDIO_ENABLED/VIDEO_ENABLED require ASYNC_INGESTION_ENABLED=true")
        if self.microphone_enabled and not self.audio_enabled:
            raise ValueError("MICROPHONE_ENABLED requires AUDIO_ENABLED=true")
        if self.cloud_media_enabled and not (self.audio_enabled or self.video_enabled):
            raise ValueError("CLOUD_MEDIA_ENABLED requires at least one media modality")
        if self.video_baseline_frames > self.max_video_frames:
            raise ValueError("VIDEO_BASELINE_FRAMES cannot exceed MAX_VIDEO_FRAMES")
        if self.video_frame_ocr_limit > self.max_video_frames:
            raise ValueError("VIDEO_FRAME_OCR_LIMIT cannot exceed MAX_VIDEO_FRAMES")
        if self.ocr_enabled and not self.rich_parser_enabled:
            raise ValueError("OCR_ENABLED requires RICH_PARSER_ENABLED=true")
        if self.local_embeddings_enabled and self.gemini_embeddings_enabled:
            raise ValueError(
                "Choose exactly one embedding profile: LOCAL_EMBEDDINGS_ENABLED or GEMINI_EMBEDDINGS_ENABLED"
            )
        if self.local_embeddings_enabled and self.local_embedding_dimensions <= 0:
            raise ValueError("LOCAL_EMBEDDING_DIMENSIONS must be positive")
        if self.browser_enabled:
            if len(self.browser_service_token.strip()) < 32:
                raise ValueError(
                    "BROWSER_ENABLED requires BROWSER_SERVICE_TOKEN with at least 32 characters"
                )
            browser = urlsplit(self.browser_service_url)
            if (
                browser.scheme not in {"http", "https"}
                or not browser.hostname
                or browser.username
                or browser.password
            ):
                raise ValueError(
                    "BROWSER_SERVICE_URL must be an http(s) origin without embedded credentials"
                )
            if browser.path not in {"", "/"} or browser.query or browser.fragment:
                raise ValueError(
                    "BROWSER_SERVICE_URL must be an origin without path, query or fragment"
                )
        if self.auth_mode == "oidc":
            if not self.oidc_issuer or not self.oidc_client_id:
                raise ValueError("OIDC_ISSUER and OIDC_CLIENT_ID are required when AUTH_MODE=oidc")
            if not self.public_base_url:
                raise ValueError("PUBLIC_BASE_URL is required when AUTH_MODE=oidc")
        if self.deployment_environment == "production":
            if self.auth_mode != "oidc":
                raise ValueError("production requires AUTH_MODE=oidc")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("production requires PostgreSQL")
            if not self.worker_database_url or self.worker_database_url == self.database_url:
                raise ValueError(
                    "production requires a distinct WORKER_DATABASE_URL for the privileged worker role"
                )
            if not self.session_cookie_secure:
                raise ValueError("production requires SESSION_COOKIE_SECURE=true")
            if not self.public_base_url.startswith(
                "https://"
            ) or not self.frontend_origin.startswith("https://"):
                raise ValueError("production public URLs must use HTTPS")
            if not self.oidc_issuer.startswith("https://"):
                raise ValueError("production OIDC_ISSUER must use HTTPS")
            public = urlsplit(self.public_base_url)
            frontend = urlsplit(self.frontend_origin)
            if (public.scheme, public.netloc) != (frontend.scheme, frontend.netloc):
                raise ValueError(
                    "production requires FRONTEND_ORIGIN and PUBLIC_BASE_URL to share one origin"
                )
            if public.path not in {"", "/"} or frontend.path not in {"", "/"}:
                raise ValueError("production public origins must not contain path prefixes")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
