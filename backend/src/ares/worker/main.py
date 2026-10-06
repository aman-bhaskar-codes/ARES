from __future__ import annotations

import importlib.util
import logging
import os
import signal
import socket
import threading
import time
from pathlib import Path
from collections.abc import Callable

from ares.adapters.db import Base, build_session_factory
from ares.adapters.docling_parser import DoclingSubprocessParser
from ares.adapters.filesystem_blob import FilesystemBlobStore
from ares.adapters.pdf_parser import BoundedPdfParser
from ares.adapters.faster_whisper import FasterWhisperSubprocessTranscriber
from ares.api.settings import get_settings
from ares.application.repository import IngestionLease, JobLease, Repository, StaleLeaseError
from ares.application.observability import configure_logging, configure_telemetry
from ares.application.runtime import build_embedding_runtime, build_research_runtime
from ares.application.asset_ingestion import AssetIngestionExecutor, BuiltinRichExtractor
from ares.application.indexing import DocumentEmbeddingIndexer
from ares.application.media_ingestion import FFmpegMediaProcessor
from ares.application.media_capabilities import probe_local_media_runtime
from ares.application.visualizations import VisualizationService

logger = logging.getLogger("ares.worker")


class LeaseKeepAlive:
    def __init__(self, repository: Repository, lease: JobLease, interval_seconds: float = 10.0):
        self.repository = repository
        self.lease = lease
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"lease-{lease.run_id}")

    @property
    def lease_lost(self) -> bool:
        return self._lost.is_set()

    def __enter__(self) -> "LeaseKeepAlive":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        delay = self.interval_seconds
        retry_delay = max(0.1, min(2.0, self.interval_seconds / 2))
        while not self._stop.wait(delay):
            try:
                self.lease = self.repository.heartbeat(self.lease)
                delay = self.interval_seconds
            except StaleLeaseError:
                logger.warning("lease lost run_id=%s; worker result is fenced", self.lease.run_id)
                self._lost.set()
                self._stop.set()
            except Exception:
                # A transient DB/network failure is not proof the lease is lost. Retry faster than
                # the normal heartbeat cadence so a brief outage does not unnecessarily permit
                # another worker to reclaim an otherwise healthy in-flight job.
                logger.exception("lease heartbeat transient failure run_id=%s", self.lease.run_id)
                delay = retry_delay


class IngestionLeaseKeepAlive:
    def __init__(
        self, repository: Repository, lease: IngestionLease, interval_seconds: float = 10.0
    ):
        self.repository = repository
        self.lease = lease
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"ingestion-lease-{lease.ingestion_id}"
        )

    @property
    def lease_lost(self) -> bool:
        return self._lost.is_set()

    def __enter__(self) -> "IngestionLeaseKeepAlive":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        delay = self.interval_seconds
        retry_delay = max(0.1, min(2.0, self.interval_seconds / 2))
        while not self._stop.wait(delay):
            try:
                self.lease = self.repository.heartbeat_ingestion(self.lease)
                delay = self.interval_seconds
            except StaleLeaseError:
                logger.warning(
                    "ingestion lease lost ingestion_id=%s; publication is fenced",
                    self.lease.ingestion_id,
                )
                self._lost.set()
                self._stop.set()
            except Exception:
                logger.exception(
                    "ingestion lease heartbeat transient failure ingestion_id=%s",
                    self.lease.ingestion_id,
                )
                delay = retry_delay


class WorkerPresence:
    def __init__(
        self,
        repository: Repository,
        *,
        interval_seconds: float,
        health_file: str,
        profile: str = "research",
        capabilities: dict[str, object] | None = None,
        capabilities_provider: Callable[[], dict[str, object]] | None = None,
    ):
        self.repository = repository
        self.interval_seconds = interval_seconds
        self.health_file = Path(health_file)
        self.profile = profile
        self.capabilities_provider = capabilities_provider
        self._capabilities = dict(capabilities or {})
        self.worker_id = repository.register_worker(
            f"{socket.gethostname()}:{os.getpid()}:{profile}", capabilities=self._capabilities
        )
        self._state = "active"
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="worker-presence")

    def start(self) -> None:
        self.health_file.parent.mkdir(parents=True, exist_ok=True)
        self._write_health()
        self._thread.start()

    def draining(self) -> None:
        self._state = "draining"
        try:
            self.repository.heartbeat_worker(
                self.worker_id, state="draining", capabilities=self._current_capabilities()
            )
        except Exception:
            logger.exception("failed to publish worker draining state")
        self._write_health()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(2.0, self.interval_seconds + 1.0))
        try:
            self.repository.stop_worker(self.worker_id)
        except Exception:
            logger.exception("failed to publish worker stop state")
        try:
            self.health_file.unlink(missing_ok=True)
        except OSError:
            logger.exception("failed to remove worker health file")

    def _current_capabilities(self) -> dict[str, object]:
        if self.capabilities_provider is None:
            return dict(self._capabilities)
        capabilities = dict(self.capabilities_provider())
        self._capabilities = capabilities
        return capabilities

    def _write_health(self) -> None:
        try:
            self.health_file.write_text(f"{self._state}\n", encoding="utf-8")
        except OSError:
            logger.exception("failed to update worker health file")

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.repository.heartbeat_worker(
                    self.worker_id,
                    state=self._state,
                    capabilities=self._current_capabilities(),
                )
                self._write_health()
            except Exception:
                logger.exception("worker presence heartbeat failed")


def _media_capabilities(settings) -> dict[str, object]:
    local_media = probe_local_media_runtime(
        ffmpeg_binary=settings.ffmpeg_path,
        ffprobe_binary=settings.ffprobe_path,
        whisper_model_path=settings.whisper_model_path,
    )
    docling_ready = importlib.util.find_spec("docling") is not None
    fastembed_ready = importlib.util.find_spec("fastembed") is not None
    media_profile = settings.worker_profile in {"media", "combined"}
    asr_ready = media_profile and local_media.transcription_ready
    video_processing_ready = media_profile and local_media.video_processing_ready
    return {
        "research": settings.worker_profile in {"research", "combined"},
        "ingestion": media_profile,
        "rich_parser": bool(media_profile and settings.rich_parser_enabled and docling_ready),
        "ocr": bool(
            media_profile
            and settings.rich_parser_enabled
            and settings.ocr_enabled
            and docling_ready
        ),
        "local_embeddings": bool(
            media_profile and settings.local_embeddings_enabled and fastembed_ready
        ),
        "audio": bool(settings.audio_enabled and asr_ready),
        "video": bool(settings.video_enabled and video_processing_ready),
        # Raw cloud media intentionally remains outside the no-egress media worker.
        "cloud_media": False,
        "ffmpeg": local_media.ffmpeg,
        "whisper_runtime": local_media.whisper_runtime,
        "whisper_model": local_media.whisper_model,
    }


def main() -> None:
    settings = get_settings()
    configure_logging(json_logs=settings.json_logs)
    telemetry_shutdown = configure_telemetry(
        endpoint=settings.otel_exporter_otlp_endpoint,
        service_name=f"{settings.otel_service_name}-worker",
        sample_ratio=settings.otel_trace_sample_ratio,
        export_timeout_seconds=settings.otel_export_timeout_seconds,
    )
    settings.validate_security_mode()
    worker_database_url = settings.worker_database_url or settings.database_url
    engine, sessions = build_session_factory(worker_database_url)
    if settings.ares_mode == "demo" and worker_database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    repository = Repository(sessions)
    embedder = None
    embedding_model_id = ""
    embedding_dimensions = settings.local_embedding_dimensions
    embedding_runtime = None
    if settings.worker_profile in {"media", "combined"}:
        embedding_runtime = build_embedding_runtime(settings)
        embedder, embedding_model_id, embedding_dimensions = embedding_runtime
    research = (
        build_research_runtime(
            settings,
            repository,
            embedding_runtime=embedding_runtime if settings.worker_profile == "combined" else None,
        )
        if settings.worker_profile in {"research", "combined"}
        else None
    )
    profile_id = None
    if embedding_model_id:
        profile = repository.get_retrieval_profile_by_model(embedding_model_id)
        if profile:
            profile_id = profile["id"]

    ingestion = None
    if settings.worker_profile in {"media", "combined"}:
        indexer = DocumentEmbeddingIndexer(
            repository,
            embedder,
            profile_id=profile_id,
            model_id=embedding_model_id,
            dimensions=embedding_dimensions,
            batch_size=settings.local_embedding_batch_size
            if settings.local_embeddings_enabled
            else 16,
            max_chunks=settings.max_background_embed_chunks,
            remote_provider="gemini-embeddings"
            if settings.gemini_embeddings_enabled and not settings.local_embeddings_enabled
            else None,
            rpm=settings.gemini_embedding_rpm or 1,
            tpm=settings.gemini_embedding_tpm or 1,
            rpd=settings.gemini_embedding_rpd or 1,
        )
        pdf_parser = BoundedPdfParser(
            max_bytes=settings.max_upload_bytes,
            max_pages=settings.max_pdf_pages,
            timeout_seconds=settings.pdf_parse_timeout_seconds,
        )
        rich_parser = None
        if settings.rich_parser_enabled:
            rich_parser = DoclingSubprocessParser(
                timeout_seconds=settings.docling_timeout_seconds,
                max_bytes=settings.max_upload_bytes,
                max_pages=settings.max_rich_pdf_pages,
                language=settings.ocr_language,
                model_cache_dir=settings.docling_model_cache_dir,
            )
        media_processor = None
        capabilities = _media_capabilities(settings)
        if settings.audio_enabled or settings.video_enabled:
            if capabilities["audio"] or capabilities["video"]:
                transcriber = (
                    FasterWhisperSubprocessTranscriber(
                        model_path=settings.whisper_model_path,
                        model_revision=settings.whisper_model_revision,
                        compute_type=settings.whisper_compute_type,
                        cpu_threads=settings.whisper_cpu_threads,
                        beam_size=settings.whisper_beam_size,
                        language=settings.whisper_language or None,
                        timeout_seconds=settings.whisper_timeout_seconds,
                        subprocess_memory_mb=settings.media_subprocess_memory_mb,
                        subprocess_cpu_seconds=settings.media_subprocess_cpu_seconds,
                    )
                    if capabilities["audio"]
                    else None
                )
                media_processor = FFmpegMediaProcessor(
                    transcriber,
                    ffmpeg_binary=settings.ffmpeg_path,
                    ffprobe_binary=settings.ffprobe_path,
                    max_audio_duration_seconds=settings.max_audio_duration_seconds,
                    max_video_duration_seconds=settings.max_video_duration_seconds,
                    max_video_source_pixels=settings.max_video_source_pixels,
                    max_selected_frames=settings.max_video_frames,
                    baseline_frames=settings.video_baseline_frames,
                    scene_threshold=settings.video_scene_threshold,
                    timeout_seconds=settings.media_process_timeout_seconds,
                    subprocess_memory_mb=settings.media_subprocess_memory_mb,
                    subprocess_cpu_seconds=settings.media_subprocess_cpu_seconds,
                )
            else:
                logger.warning(
                    "media modality configured but unavailable capabilities=%s", capabilities
                )
        ingestion = AssetIngestionExecutor(
            repository,
            FilesystemBlobStore(settings.blob_root),
            BuiltinRichExtractor(
                pdf_parser,
                max_csv_rows=settings.max_csv_rows,
                max_table_cells=settings.max_table_cells,
                max_cell_chars=settings.max_cell_chars,
            ),
            indexer,
            rich_parser=rich_parser,
            ocr_enabled=settings.ocr_enabled,
            max_image_pixels=settings.max_image_pixels,
            max_table_cells=settings.max_table_cells,
            media_processor=media_processor,
            max_frame_ocr_frames=settings.video_frame_ocr_limit,
            config_hash=(
                f"m09:{settings.ocr_language}:"
                f"{settings.local_embedding_model if settings.local_embeddings_enabled else 'no-local-embed'}:"
                f"{settings.whisper_model_revision if (settings.audio_enabled or settings.video_enabled) else 'no-asr'}:"
                f"frames={settings.max_video_frames}:scene={settings.video_scene_threshold}"
            ),
        )
    visualization_service = (
        VisualizationService(
            repository,
            max_graph_nodes=settings.visualization_graph_max_nodes,
            max_graph_edges=settings.visualization_graph_max_edges,
        )
        if settings.visualizations_enabled and research is not None
        else None
    )
    capabilities = _media_capabilities(settings)
    presence = WorkerPresence(
        repository,
        interval_seconds=settings.worker_heartbeat_seconds,
        health_file=settings.worker_health_file,
        profile=settings.worker_profile,
        capabilities=capabilities,
        capabilities_provider=lambda: _media_capabilities(settings),
    )
    presence.start()
    stopping = threading.Event()

    def request_shutdown(signum, _frame) -> None:
        if not stopping.is_set():
            logger.info("shutdown requested signal=%s; stopping new job admission", signum)
            presence.draining()
            stopping.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, request_shutdown)
        except (ValueError, OSError):
            pass

    logger.info("worker started mode=%s profile=%s", settings.ares_mode, settings.worker_profile)
    last_cache_maintenance = 0.0
    try:
        while not stopping.is_set():
            # Cache reads fail closed on expiry. This bounded maintenance only removes cold
            # expired records so a busy multi-tenant instance cannot accumulate dead rows.
            now_monotonic = time.monotonic()
            if now_monotonic - last_cache_maintenance >= 60.0:
                try:
                    repository.purge_expired_research_cache(limit=500)
                except Exception:
                    logger.exception("research cache maintenance failed")
                last_cache_maintenance = now_monotonic
            # Combined workers always prefer interactive research. Dedicated media workers
            # prevent OCR/embedding CPU work from starving research admission.
            lease = (
                repository.claim_next_job(max_attempts=settings.max_job_attempts)
                if research is not None
                else None
            )
            if lease is not None:
                try:
                    with LeaseKeepAlive(
                        repository, lease, interval_seconds=settings.worker_heartbeat_seconds
                    ) as keepalive:
                        research.execute(lease)
                    if keepalive.lease_lost:
                        raise StaleLeaseError(f"lease lost while processing run {lease.run_id}")
                    if visualization_service is not None:
                        try:
                            generated = visualization_service.generate_for_run(lease.run_id)
                            repository.record_event(
                                lease.run_id,
                                "visualization.ready",
                                {"count": len(generated), "schema_version": 1},
                                lease_token=lease.token,
                            )
                        except Exception:
                            # Visual artifacts are optional release UX. A completed research run
                            # remains valid if visualization derivation fails; surface the degraded
                            # state without rewriting the research result as failed.
                            logger.exception(
                                "visualization generation failed run_id=%s", lease.run_id
                            )
                            repository.record_event(
                                lease.run_id,
                                "visualization.failed",
                                {"schema_version": 1},
                                lease_token=lease.token,
                            )
                    repository.finish_job(lease)
                except Exception:
                    logger.exception("worker failure run_id=%s", lease.run_id)
                    try:
                        repository.finish_job(lease, final_state="failed")
                    except Exception:
                        logger.exception("failed to close lease run_id=%s", lease.run_id)
                    stopping.wait(1)
                continue

            ingestion_lease = (
                repository.claim_next_ingestion(max_attempts=settings.max_job_attempts)
                if ingestion is not None
                else None
            )
            if ingestion_lease is None:
                stopping.wait(0.4)
                continue
            try:
                with IngestionLeaseKeepAlive(
                    repository, ingestion_lease, interval_seconds=settings.worker_heartbeat_seconds
                ) as keepalive:
                    ingestion.execute(ingestion_lease)
                if keepalive.lease_lost:
                    raise StaleLeaseError(
                        f"lease lost while processing ingestion {ingestion_lease.ingestion_id}"
                    )
            except StaleLeaseError:
                logger.warning(
                    "stale ingestion result fenced ingestion_id=%s", ingestion_lease.ingestion_id
                )
            except Exception:
                # AssetIngestionExecutor records a durable failed state when it still owns
                # the lease. A second failure here should not attempt another publication.
                logger.exception(
                    "ingestion worker failure ingestion_id=%s", ingestion_lease.ingestion_id
                )
                stopping.wait(1)
        logger.info("worker admission stopped; shutdown complete")
    finally:
        presence.close()
        close = getattr(research, "close", None) if research is not None else None
        if callable(close):
            try:
                close()
            except Exception:
                logger.exception("research runtime cleanup failed")
        embedding_owned_by_research = bool(
            research is not None and settings.ares_mode != "demo" and embedder is not None
        )
        embed_close = getattr(embedder, "close", None) if embedder is not None else None
        if callable(embed_close) and not embedding_owned_by_research:
            try:
                embed_close()
            except Exception:
                logger.exception("embedding runtime cleanup failed")
        try:
            telemetry_shutdown()
        except Exception:
            logger.exception("telemetry shutdown failed")
        engine.dispose()


if __name__ == "__main__":
    main()
