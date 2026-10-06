from __future__ import annotations

import threading
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

from ares.application.planning import DeterministicResearchPlanner
from ares.application.checkpoints import CheckpointStore
from ares.application.run_context import RunCancelled, RunContext, RunDeadlineExceeded
from ares.application.finalization import compose_checked_markdown
from ares.application.observability import RunTelemetry
from ares.application.security import RemoteContentRiskScanner
from ares.application.decisions import ResilientDecisionProvider
from ares.application.rag import HybridRAGRetriever
from ares.application.research_cache import RunResearchCache
from ares.application.providers import ProviderRegistry
from ares.application.persistent_rag import PersistentDocumentRAG
from ares.application.research_stages.discovery import DiscoveryStage
from ares.application.research_stages.synthesis import SynthesisStage
from ares.application.repository import (
    JobLease,
    QuotaExceededError,
    Repository,
    ResourceCapacityError,
    RunAuthorizationError,
    RunBudgetExceededError,
)
from ares.domain.budgets import BUDGETS, calculate_provider_cost
from ares.domain.models import (
    AssessmentState,
    FetchedDocument,
    FinalizedClaim,
    RunStatus,
    SearchHit,
    SupportStatus,
    SynthesisResult,
)
from ares.ports.errors import LLMProviderError, SearchProviderError
from ares.ports.research import AcademicFullTextFetcher, Fetcher, LLMProvider, SearchProvider
from ares.ports.decisions import DecisionProvider
from ares.ports.semantic import SemanticClaimChecker


class CancelledRun(RuntimeError):
    pass


_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
}


def _normalize_cache_query(value: str) -> str:
    """Normalize only cache identity; provider requests retain the user's original text."""
    return " ".join(value.split()).casefold()


def _canonical_url(value: str) -> str:
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host
    if port and not (
        (parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.casefold() not in _TRACKING_PARAMS
        ],
        doseq=True,
    )
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def _document_identity_keys(document: FetchedDocument) -> set[str]:
    """Return every stable identity alias available for a fetched document.

    A source can have more than one useful identity: a DOI/arXiv/repository identifier, the
    immutable fetched-content hash, and its normalized final URL. Dedupe must compare all of
    them. Picking only the strongest key lets a canonical source and a byte-identical mirror
    survive as separate evidence, which can falsely inflate apparent source independence.
    """
    keys = {f"url:{_canonical_url(str(document.final_url))}"}
    if document.canonical_identifier:
        keys.add(f"id:{document.canonical_identifier.casefold()}")
    if document.content_hash:
        keys.add(f"content:{document.content_hash.casefold()}")
    return keys


def _document_dedup_key(document: FetchedDocument) -> str:
    """Compatibility helper returning the strongest stable identity for one document."""
    keys = _document_identity_keys(document)
    for prefix in ("id:", "content:", "url:"):
        for key in keys:
            if key.startswith(prefix):
                return key
    raise AssertionError("document identity keys are never empty")


def _deduplicate_fetched(
    items: list[tuple[SearchHit, FetchedDocument]],
    *,
    existing_keys: set[str] | None = None,
) -> tuple[list[tuple[SearchHit, FetchedDocument]], int]:
    """Collapse canonical, byte-identical and URL duplicates before retrieval.

    Every identity alias from every admitted document is retained in ``seen``. This makes the
    operation transitive across heterogeneous metadata: e.g. DOI source A can suppress a
    byte-identical mirror B even when B lacks the DOI, and B's normalized URL remains known for
    later recovery waves.
    """
    seen: set[str] = set(existing_keys or ())
    output: list[tuple[SearchHit, FetchedDocument]] = []
    duplicates = 0
    for hit, document in items:
        keys = _document_identity_keys(document)
        if keys & seen:
            duplicates += 1
            seen.update(keys)
            continue
        seen.update(keys)
        output.append((hit, document))
    return output, duplicates


def _in_date_window(value: datetime | None, window) -> bool:
    if window is None or value is None:
        return True
    candidate = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    start = (
        window.start
        if window.start is None or window.start.tzinfo is not None
        else window.start.replace(tzinfo=UTC)
    )
    end = (
        window.end
        if window.end is None or window.end.tzinfo is not None
        else window.end.replace(tzinfo=UTC)
    )
    return (start is None or candidate >= start) and (end is None or candidate <= end)


_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_ARXIV_RE = re.compile(r"\b(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.IGNORECASE)
_GITHUB_RE = re.compile(r"(?:github\.com/)?([A-Z0-9_.-]+/[A-Z0-9_.-]+)", re.IGNORECASE)


def _query_identifiers(query: str) -> set[str]:
    """Extract exact source identifiers that should outrank fuzzy metadata matches.

    This is deliberately conservative: it only recognizes DOI, arXiv and explicit GitHub
    repository forms already represented by ARES canonical identifiers.
    """
    values: set[str] = set()
    for match in _DOI_RE.findall(query):
        values.add(f"doi:{match.rstrip('.,;').casefold()}")
    for match in _ARXIV_RE.findall(query):
        values.add(f"arxiv:{match.casefold()}")
    for match in _GITHUB_RE.findall(query):
        # Avoid treating prose fractions such as 2/3 as repository identifiers.
        owner, repo = match.split("/", 1)
        if any(ch.isalpha() for ch in owner + repo):
            values.add(f"github:{owner.casefold()}/{repo.casefold()}")
    return values


def _prioritize_exact_identifiers(
    query: str, rows: list[tuple[SearchHit, FetchedDocument]]
) -> list[tuple[SearchHit, FetchedDocument]]:
    exact = _query_identifiers(query)
    if not exact:
        return rows
    return sorted(
        rows,
        key=lambda pair: (
            0
            if (pair[1].canonical_identifier or pair[0].canonical_identifier or "").casefold()
            in exact
            else 1,
            pair[0].rank,
        ),
    )



class ResearchEngine:
    def __init__(
        self,
        repository: Repository,
        search: SearchProvider,
        fetcher: Fetcher,
        llm: LLMProvider,
        *,
        gemini_model: str,
        gemini_rpm: int,
        gemini_tpm: int,
        gemini_rpd: int,
        gemini_max_daily_spend_usd: float | None = None,
        planner: DeterministicResearchPlanner | None = None,
        retriever: HybridRAGRetriever | None = None,
        global_http_concurrency: int = 4,
        gemini_concurrency: int = 1,
        provider_http_timeout_seconds: float = 20.0,
        source_fetch_timeout_seconds: float = 12.0,
        gemini_timeout_seconds: float = 45.0,
        decisions: DecisionProvider | None = None,
        registry: ProviderRegistry | None = None,
        persistent_documents: PersistentDocumentRAG | None = None,
        discovery_concurrency: int = 3,
        research_cache_enabled: bool = True,
        web_search_cache_ttl_seconds: int = 3600,
        web_source_cache_ttl_seconds: int = 21600,
        academic_cache_ttl_seconds: int = 604800,
        software_cache_ttl_seconds: int = 3600,
        semantic_checker: SemanticClaimChecker | None = None,
        semantic_checker_model: str = "gemini-3.8-flash",
        semantic_checker_max_claims: int = 6,
        semantic_checker_timeout_seconds: float = 30.0,
        academic_full_text_fetcher: AcademicFullTextFetcher | None = None,
        academic_full_text_limit: int = 2,
        academic_full_text_timeout_seconds: float = 20.0,
        academic_full_text_max_bytes: int = 20 * 1024 * 1024,
        academic_full_text_max_pages: int = 100,
    ):
        self.repository = repository
        self.search = search
        self.fetcher = fetcher
        self.llm = llm
        self.gemini_model = gemini_model
        self.gemini_rpm = gemini_rpm
        self.gemini_tpm = gemini_tpm
        self.gemini_rpd = gemini_rpd
        self.gemini_max_daily_spend_usd = gemini_max_daily_spend_usd
        self.planner = planner or DeterministicResearchPlanner()
        self.retriever = retriever or HybridRAGRetriever()
        self.decisions = ResilientDecisionProvider(decisions)
        self.registry = registry
        self.persistent_documents = persistent_documents
        self.content_risk = RemoteContentRiskScanner()
        self.global_http_concurrency = global_http_concurrency
        self.gemini_concurrency = gemini_concurrency
        self.provider_http_timeout_seconds = provider_http_timeout_seconds
        self.source_fetch_timeout_seconds = source_fetch_timeout_seconds
        self.gemini_timeout_seconds = gemini_timeout_seconds
        self.discovery_concurrency = max(1, min(3, discovery_concurrency))
        self.web_search_cache_ttl_seconds = web_search_cache_ttl_seconds
        self.web_source_cache_ttl_seconds = web_source_cache_ttl_seconds
        self.academic_cache_ttl_seconds = academic_cache_ttl_seconds
        self.software_cache_ttl_seconds = software_cache_ttl_seconds
        self.research_cache = RunResearchCache(repository, enabled=research_cache_enabled)
        self.semantic_checker = semantic_checker
        self.semantic_checker_model = semantic_checker_model
        self.semantic_checker_max_claims = max(1, semantic_checker_max_claims)
        self.semantic_checker_timeout_seconds = semantic_checker_timeout_seconds
        self.academic_full_text_fetcher = academic_full_text_fetcher
        self.academic_full_text_limit = max(0, academic_full_text_limit)
        self.academic_full_text_timeout_seconds = academic_full_text_timeout_seconds
        self.academic_full_text_max_bytes = academic_full_text_max_bytes
        self.academic_full_text_max_pages = academic_full_text_max_pages
        self._http_slots = threading.BoundedSemaphore(global_http_concurrency)
        self.discovery = DiscoveryStage(self)
        self.synthesis = SynthesisStage(self)

    def close(self) -> None:
        seen: set[int] = set()
        objects = [
            self.search,
            self.fetcher,
            self.llm,
            self.decisions,
            self.semantic_checker,
            *(self.registry.get_providers_by_kind("academic") if self.registry else []),
            *(self.registry.get_providers_by_kind("software") if self.registry else []),
            getattr(self.retriever, "embedder", None),
            getattr(self.persistent_documents, "embedder", None)
            if self.persistent_documents is not None
            else None,
            self.academic_full_text_fetcher,
        ]
        for value in objects:
            if value is None or id(value) in seen:
                continue
            seen.add(id(value))
            close = getattr(value, "close", None)
            if callable(close):
                close()

    def _check_cancel(self, lease: JobLease, context: RunContext | None = None) -> None:
        try:
            if context is not None:
                context.check()
            elif self.repository.is_cancel_requested(lease.run_id, lease_token=lease.token):
                raise RunCancelled("run cancellation requested")
        except RunCancelled:
            self.repository.set_status(lease.run_id, RunStatus.CANCELLED, lease_token=lease.token)
            raise CancelledRun

    @contextmanager
    def _resource_slot(
        self, context: RunContext, *, resource_key: str, capacity: int, ttl_seconds: int = 30
    ):
        # SQLite is the single-process demo/test fallback. Concurrent write transactions used
        # for fleet leases can serialize or lock each other there, while they are required on
        # PostgreSQL production workers. Process-local thread/semaphore bounds still apply in
        # SQLite; fleet-visible leases remain authoritative on PostgreSQL.
        if self.repository.dialect_name == "sqlite":
            context.check()
            yield None
            return
        while True:
            context.check()
            try:
                lease = self.repository.acquire_resource_lease(
                    context.lease.run_id,
                    resource_key=resource_key,
                    capacity=capacity,
                    ttl_seconds=max(1, min(ttl_seconds, int(max(1, context.remaining_seconds())))),
                    lease_token=context.lease.token,
                )
                break
            except ResourceCapacityError:
                import time

                time.sleep(0.05)
        try:
            yield lease
        finally:
            self.repository.release_resource_lease(lease)

    def _partial_or_fail(self, lease: JobLease, *, code: str, message: str) -> None:
        if self.repository.count_run_evidence(
            lease.run_id
        ) and self.repository.finalize_partial_report(
            lease.run_id, reason=message, gaps=[], lease_token=lease.token
        ):
            snapshot = self.repository.get_run(lease.run_id)
            if not snapshot.status.terminal:
                self.repository.set_status(
                    lease.run_id,
                    RunStatus.PARTIAL,
                    lease_token=lease.token,
                    payload={"code": code, "message": message[:500]},
                )
            return
        self.repository.fail_run(lease.run_id, code, message, lease_token=lease.token)

    def execute(self, lease: JobLease) -> None:
        run_id = lease.run_id
        try:
            self.repository.authorize_run_execution(run_id, lease_token=lease.token)
            self.repository.prepare_run_resume(lease)
            run = self.repository.get_run(run_id)
            budget = BUDGETS[run.mode]
            context = RunContext.create(self.repository, lease, budget)
            checkpoints = CheckpointStore(self.repository, run_id, lease.token)
            telemetry = RunTelemetry(self.repository, lease)
            context.consume(waves=1)
            route = self.decisions.route(run.query)
            self.repository.record_event(
                run_id,
                "route.decided",
                {
                    "task": route.task.value,
                    "needs_academic": route.needs_academic,
                    "needs_software": route.needs_software,
                    "needs_current_web": route.needs_current_web,
                    "confidence": route.confidence,
                    "provider": route.provider,
                },
                lease_token=lease.token,
            )
            supported_scope = {"web", "academic", "software", "documents"}
            if not set(run.source_scope) & supported_scope:
                self.repository.fail_run(
                    run_id,
                    "UNSUPPORTED_SCOPE",
                    "No supported source scope was selected.",
                    lease_token=lease.token,
                )
                return
            self._check_cancel(lease, context)
            self.repository.set_status(run_id, RunStatus.PLANNING, lease_token=lease.token)
            self.repository.set_status(run_id, RunStatus.DISCOVERING, lease_token=lease.token)
            hits, academic_docs, software_docs, plan = self.discovery._discover_tracks(
                lease, context, run, budget, telemetry
            )
            document_docs: list[tuple[SearchHit, FetchedDocument]] = []
            document_rows = []
            source_id_by_document: dict[UUID, UUID] = {}
            if "documents" in run.source_scope:
                if not run.document_ids:
                    self.repository.fail_run(
                        run_id,
                        "DOCUMENTS_REQUIRED",
                        "Document scope requires at least one document_id.",
                        lease_token=lease.token,
                    )
                    return
                self._check_cancel(lease, context)
                document_rows = self.repository.get_documents_for_run(
                    run_id, run.document_ids, lease_token=lease.token
                )
                for rank, row in enumerate(document_rows, start=1):
                    if row.status not in {"ready", "partial"}:
                        self.repository.record_event(
                            run_id,
                            "document.unavailable",
                            {"document_id": str(row.id), "name": row.name, "status": row.status},
                            lease_token=lease.token,
                        )
                        continue
                    url = f"https://ares.local/documents/{row.id}"
                    source_id = (
                        uuid4()
                    )  # run-scoped provenance identity, never the reusable document UUID
                    source_id_by_document[row.id] = source_id
                    hit = SearchHit(
                        title=row.name,
                        url=url,
                        snippet=row.text[:500],
                        rank=rank,
                        provider="documents",
                        engine="local-document-store",
                        source_kind="document",
                        canonical_identifier=f"ares:document:{row.id}",
                    )
                    document = FetchedDocument(
                        source_id=source_id,
                        user_document_id=row.id,
                        title=row.name,
                        url=url,
                        final_url=url,
                        text=row.text,
                        content_hash=row.content_hash,
                        fetched_at=row.created_at,
                        extraction_method=row.parser_version or "user-document",
                        mime_type=row.mime_type,
                        byte_count=row.byte_count,
                        source_kind="document",
                        canonical_identifier=f"ares:document:{row.id}",
                        page_map=list(row.page_map or []),
                    )
                    document_docs.append((hit, document))
                    self.repository.record_event(
                        run_id,
                        "source.found",
                        {
                            "title": row.name,
                            "url": url,
                            "rank": rank,
                            "provider": "documents",
                            "document_id": str(row.id),
                        },
                        lease_token=lease.token,
                    )
            if not hits and not academic_docs and not software_docs and not document_docs:
                self.repository.fail_run(
                    run_id, "NO_RESULTS", "No matching sources were found.", lease_token=lease.token
                )
                return

            self._check_cancel(lease, context)
            self.repository.set_status(run_id, RunStatus.READING, lease_token=lease.token)
            if hits:
                with telemetry.stage("reading.web", discovered=len(hits)):
                    fetched = self.discovery._fetch_documents(
                        lease, context, hits, budget.per_run_http_concurrency
                    )
            else:
                fetched = []
            fetched.extend(academic_docs)
            fetched.extend(software_docs)
            fetched.extend(document_docs)
            fetched, duplicate_count = _deduplicate_fetched(fetched)
            if len(fetched) > budget.max_documents:
                fetched = fetched[: budget.max_documents]
            if fetched:
                context.consume(documents=len(fetched))
            if duplicate_count:
                self.repository.record_event(
                    run_id,
                    "sources.deduplicated",
                    {"duplicates_removed": duplicate_count, "remaining": len(fetched)},
                    lease_token=lease.token,
                )
            for hit, document in fetched:
                risk = self.content_risk.inspect(document.text)
                if risk.suspicious:
                    self.repository.record_event(
                        run_id,
                        "security.content_risk",
                        {
                            "source_id": str(document.source_id),
                            "provider": hit.provider,
                            "score": risk.score,
                            "categories": list(risk.categories),
                        },
                        lease_token=lease.token,
                    )
            if not fetched:
                self.repository.fail_run(
                    run_id,
                    "SOURCE_BLOCKED",
                    "Sources were discovered but none could be read safely.",
                    lease_token=lease.token,
                )
                return

            self._check_cancel(lease, context)
            self.repository.set_status(run_id, RunStatus.EXTRACTING, lease_token=lease.token)
            max_evidence = 8 if run.mode.value == "quick" else 16
            network_documents = [
                document for hit, document in fetched if hit.provider != "documents"
            ]
            if network_documents:
                with telemetry.stage("retrieval.network", documents=len(network_documents)):
                    network_result = self.retriever.retrieve_with_trace(
                        run.query, network_documents, limit=max_evidence
                    )
                network_ranked = network_result.candidates
                self.repository.record_event(
                    run_id,
                    "retrieval.network",
                    {
                        "mode": network_result.mode,
                        "semantic_used": network_result.semantic_used,
                        "candidates": len(network_result.trace),
                        "selected": len(network_result.candidates),
                    },
                    lease_token=lease.token,
                )
            else:
                network_ranked = []
            document_ranked = []
            if document_docs:
                if self.persistent_documents is not None:
                    persistent = self.persistent_documents.retrieve(
                        run.query,
                        documents=[row for row in document_rows if row.id in source_id_by_document],
                        source_id_by_document=source_id_by_document,
                        limit=max_evidence,
                    )
                    document_ranked = persistent.candidates
                    self.repository.record_event(
                        run_id,
                        "retrieval.documents",
                        {
                            "semantic_used": persistent.semantic_used,
                            "embedded_chunks": persistent.embedded_chunks,
                            "degraded_reason": persistent.degraded_reason,
                            "selected_passages": len(document_ranked),
                        },
                        lease_token=lease.token,
                    )
                else:
                    document_ranked = self.retriever.retrieve(
                        run.query, [document for _, document in document_docs], limit=max_evidence
                    )

            # Interleave source classes instead of comparing incomparable raw score scales.
            ranked = []
            for index in range(max(len(network_ranked), len(document_ranked))):
                if index < len(network_ranked):
                    ranked.append(network_ranked[index])
                if index < len(document_ranked):
                    ranked.append(document_ranked[index])
                if len(ranked) >= max_evidence:
                    break
            if not ranked:
                self.repository.fail_run(
                    run_id,
                    "INSUFFICIENT_EVIDENCE",
                    "Readable sources contained no relevant evidence passages.",
                    lease_token=lease.token,
                )
                return

            by_source: dict[UUID, list] = {}
            for candidate in ranked:
                by_source.setdefault(candidate.source_id, []).append(candidate)
            hit_by_requested = {_canonical_url(str(hit.url)): hit for hit, _ in fetched}
            evidence_packets = []
            for hit, document in fetched:
                candidates = by_source.get(document.source_id, [])
                if not candidates:
                    continue
                metadata_hit = hit_by_requested.get(_canonical_url(str(document.url)), hit)
                evidence_packets.extend(
                    self.repository.persist_document_evidence(
                        run_id,
                        document=document,
                        candidates=candidates,
                        provider=metadata_hit.provider,
                        discovery_rank=metadata_hit.rank,
                        snippet=metadata_hit.snippet,
                        lease_token=lease.token,
                    )
                )

            if not evidence_packets:
                self.repository.fail_run(
                    run_id,
                    "INSUFFICIENT_EVIDENCE",
                    "No evidence could be persisted safely.",
                    lease_token=lease.token,
                )
                return

            self._check_cancel(lease, context)
            self.repository.set_status(run_id, RunStatus.CHECKING, lease_token=lease.token)
            with telemetry.stage("evaluation.coverage", evidence=len(evidence_packets)):
                coverage = self.decisions.evaluate_coverage(
                    run.query, plan.facets, evidence_packets
                )
            self.repository.persist_facet_coverage(
                run_id,
                coverage.facets,
                checker_method=coverage.provider,
                checker_version="m10-v1",
                lease_token=lease.token,
            )
            self.repository.record_event(
                run_id,
                "coverage.updated",
                {
                    "evidence_passages": len(evidence_packets),
                    "sources_read": len(fetched),
                    "independent_origins": len(
                        {packet.origin_group_id or packet.source_id for packet in evidence_packets}
                    ),
                    "sufficient": coverage.sufficient,
                    "missing_facets": coverage.missing_facets,
                    "facets": [facet.model_dump(mode="json") for facet in coverage.facets],
                    "provider": coverage.provider,
                    "confidence": coverage.confidence,
                },
                lease_token=lease.token,
            )

            # Research mode gets one bounded targeted recovery wave in M3. A second/third wave can
            # be added later without changing contracts; deterministic budgets remain authoritative.
            if run.mode.value == "research" and not coverage.sufficient and coverage.missing_facets:
                context.consume(waves=1)
                self.repository.set_status(run_id, RunStatus.DISCOVERING, lease_token=lease.token)
                targeted_query = f"{run.query} {' '.join(coverage.missing_facets[:2])}"
                self._check_cancel(lease, context)
                with telemetry.stage("discovery.web.wave2"):
                    extra_hits, _ = self.discovery._search_web_query(
                        lease,
                        context,
                        query=targeted_query,
                        limit=min(6, budget.max_documents),
                        wave=2,
                    )
                known_urls = {_canonical_url(str(hit.url)) for hit, _ in fetched}
                extra_hits = [
                    hit for hit in extra_hits if _canonical_url(str(hit.url)) not in known_urls
                ][:6]
                for hit in extra_hits:
                    self.repository.record_event(
                        run_id,
                        "source.found",
                        {
                            "title": hit.title,
                            "url": str(hit.url),
                            "rank": hit.rank,
                            "provider": hit.provider,
                            "wave": 2,
                        },
                        lease_token=lease.token,
                    )
                if extra_hits:
                    self.repository.set_status(run_id, RunStatus.READING, lease_token=lease.token)
                    with telemetry.stage("reading.web.wave2", discovered=len(extra_hits)):
                        extra_fetched = self.discovery._fetch_documents(
                            lease, context, extra_hits, budget.per_run_http_concurrency
                        )
                    existing_keys = {
                        key for _, document in fetched for key in _document_identity_keys(document)
                    }
                    extra_fetched, wave_duplicates = _deduplicate_fetched(
                        extra_fetched, existing_keys=existing_keys
                    )
                    remaining_documents = max(
                        0, budget.max_documents - int(context.run.usage_ledger.get("documents", 0))
                    )
                    extra_fetched = extra_fetched[:remaining_documents]
                    if extra_fetched:
                        context.consume(documents=len(extra_fetched))
                    if wave_duplicates:
                        self.repository.record_event(
                            run_id,
                            "sources.deduplicated",
                            {
                                "wave": 2,
                                "duplicates_removed": wave_duplicates,
                                "remaining": len(extra_fetched),
                            },
                            lease_token=lease.token,
                        )
                    for extra_hit, extra_document in extra_fetched:
                        risk = self.content_risk.inspect(extra_document.text)
                        if risk.suspicious:
                            self.repository.record_event(
                                run_id,
                                "security.content_risk",
                                {
                                    "source_id": str(extra_document.source_id),
                                    "provider": extra_hit.provider,
                                    "score": risk.score,
                                    "categories": list(risk.categories),
                                    "wave": 2,
                                },
                                lease_token=lease.token,
                            )
                    self.repository.set_status(
                        run_id, RunStatus.EXTRACTING, lease_token=lease.token
                    )
                    with telemetry.stage("retrieval.network.wave2", documents=len(extra_fetched)):
                        extra_result = self.retriever.retrieve_with_trace(
                            targeted_query, [doc for _, doc in extra_fetched], limit=8
                        )
                    extra_ranked = extra_result.candidates
                    self.repository.record_event(
                        run_id,
                        "retrieval.network",
                        {
                            "wave": 2,
                            "mode": extra_result.mode,
                            "semantic_used": extra_result.semantic_used,
                            "candidates": len(extra_result.trace),
                            "selected": len(extra_ranked),
                        },
                        lease_token=lease.token,
                    )
                    extra_by_source: dict[UUID, list] = {}
                    for candidate in extra_ranked:
                        extra_by_source.setdefault(candidate.source_id, []).append(candidate)
                    for hit, document in extra_fetched:
                        candidates = extra_by_source.get(document.source_id, [])
                        if candidates:
                            evidence_packets.extend(
                                self.repository.persist_document_evidence(
                                    run_id,
                                    document=document,
                                    candidates=candidates,
                                    provider=hit.provider,
                                    discovery_rank=hit.rank,
                                    snippet=hit.snippet,
                                    lease_token=lease.token,
                                )
                            )
                    self.repository.set_status(run_id, RunStatus.CHECKING, lease_token=lease.token)
                    with telemetry.stage(
                        "evaluation.coverage.wave2", evidence=len(evidence_packets)
                    ):
                        coverage = self.decisions.evaluate_coverage(
                            run.query, plan.facets, evidence_packets
                        )
                    self.repository.persist_facet_coverage(
                        run_id,
                        coverage.facets,
                        checker_method=coverage.provider,
                        checker_version="m10-v1",
                        lease_token=lease.token,
                    )
                    self.repository.record_event(
                        run_id,
                        "coverage.updated",
                        {
                            "wave": 2,
                            "evidence_passages": len(evidence_packets),
                            "independent_origins": len(
                                {
                                    packet.origin_group_id or packet.source_id
                                    for packet in evidence_packets
                                }
                            ),
                            "sufficient": coverage.sufficient,
                            "missing_facets": coverage.missing_facets,
                            "facets": [facet.model_dump(mode="json") for facet in coverage.facets],
                            "provider": coverage.provider,
                            "confidence": coverage.confidence,
                        },
                        lease_token=lease.token,
                    )

            self.repository.set_status(run_id, RunStatus.SYNTHESIZING, lease_token=lease.token)
            estimated_input_tokens = max(
                1,
                (len(run.query) + sum(len(packet.text) for packet in evidence_packets) + 3_000)
                // 4,
            )
            if estimated_input_tokens > budget.model_input_tokens:
                self.repository.fail_run(
                    run_id,
                    "BUDGET_EXCEEDED",
                    "Selected evidence exceeded the configured model input budget.",
                    lease_token=lease.token,
                )
                return
            synthesis_key = checkpoints.key(
                "synthesis.final",
                {
                    "query": run.query,
                    "max_output_tokens": budget.model_output_tokens,
                    "llm_manifest": self.llm.manifest() if hasattr(self.llm, "manifest") else {"model": self.gemini_model},
                    "evidence_hashes": [packet.content_hash for packet in evidence_packets],
                    "provenance_policy": "m12-v1",
                },
            )
            restored = checkpoints.start(synthesis_key)
            if restored is not None and isinstance(restored.get("result"), dict):
                result = SynthesisResult.model_validate(restored["result"])
                self.repository.record_event(
                    run_id,
                    "run.checkpoint.restored",
                    {"step": synthesis_key.step},
                    lease_token=lease.token,
                )
            else:
                context.consume(llm_calls=1, model_input_tokens=estimated_input_tokens)
                estimated_output_tokens = budget.model_output_tokens
                cost_usd = calculate_provider_cost(self.gemini_model, estimated_input_tokens, estimated_output_tokens)
                usage_id = self.repository.reserve_provider_usage(
                    provider="gemini",
                    model=self.gemini_model,
                    rpm=self.gemini_rpm,
                    tpm=self.gemini_tpm,
                    rpd=self.gemini_rpd,
                    input_tokens=estimated_input_tokens,
                    output_tokens=estimated_output_tokens,
                    cost_usd=cost_usd,
                    max_daily_spend_usd=self.gemini_max_daily_spend_usd,
                    run_id=run_id,
                )
                with self._resource_slot(
                    context,
                    resource_key=f"provider:gemini:{self.gemini_model}",
                    capacity=self.gemini_concurrency,
                    ttl_seconds=max(30, int(context.remaining_seconds())),
                ):
                    with telemetry.stage("synthesis", evidence=len(evidence_packets)):
                        result = self.synthesis._synthesize(
                            context, run.query, evidence_packets, budget.model_output_tokens
                        )
                self.repository.reconcile_provider_usage(
                    usage_id,
                    input_tokens_actual=result.provider_input_tokens,
                    output_tokens_actual=result.provider_output_tokens,
                )
                if result.provider_output_tokens is not None:
                    context.consume(model_output_tokens=result.provider_output_tokens)
                checkpoints.complete(synthesis_key, {"result": result.model_dump(mode="json")})
            persisted_claims: list[FinalizedClaim] = []
            packet_by_id = {packet.evidence_id: packet for packet in evidence_packets}
            available = set(packet_by_id)
            semantic_calls = 0
            semantic_budget_exhausted = False
            with telemetry.stage("evaluation.claims", claims=len(result.claims)):
                for claim in result.claims:
                    ids = list(dict.fromkeys(claim.evidence_ids))
                    if not ids or not all(evidence_id in available for evidence_id in ids):
                        continue
                    claim_evidence = [packet_by_id[evidence_id] for evidence_id in ids]
                    decision = self.decisions.evaluate_claim(claim.text, claim_evidence)
                    # Exact numeric/unit/polarity guards remain authoritative. Semantic checking
                    # is reserved for material claims that only received heuristic screening.
                    if (
                        self.semantic_checker is not None
                        and decision.assessment_state is AssessmentState.HEURISTIC_SCREENED
                        and semantic_calls < self.semantic_checker_max_claims
                        and not semantic_budget_exhausted
                    ):
                        try:
                            semantic = self.synthesis._semantic_assess_claim(
                                context,
                                claim=claim.text,
                                evidence=claim_evidence,
                                telemetry=telemetry,
                            )
                            semantic_calls += 1
                            if semantic is not None:
                                decision = semantic
                        except RunBudgetExceededError:
                            semantic_budget_exhausted = True
                            self.repository.record_event(
                                run_id,
                                "semantic_checker.skipped",
                                {"reason": "run_budget_exhausted"},
                                lease_token=lease.token,
                            )
                        except Exception as exc:
                            self.repository.record_event(
                                run_id,
                                "semantic_checker.degraded",
                                {"error": type(exc).__name__},
                                lease_token=lease.token,
                            )
                    status_by_verdict = {
                        "supported": SupportStatus.SUPPORTED,
                        "partially_supported": SupportStatus.PARTIALLY_SUPPORTED,
                        "conflicting": SupportStatus.CONFLICTING,
                        "insufficient_evidence": SupportStatus.INSUFFICIENT_EVIDENCE,
                    }
                    support_status = status_by_verdict[decision.verdict.value]
                    self.repository.record_event(
                        run_id,
                        "claim.checked",
                        {
                            "claim": claim.text[:240],
                            "status": support_status.value,
                            "confidence": decision.confidence,
                            "provider": decision.provider,
                            "checker_method": decision.checker_method,
                            "checker_version": decision.checker_version,
                            "assessment_state": decision.assessment_state,
                            "supporting_evidence_ids": [
                                str(value) for value in decision.supporting_evidence_ids
                            ],
                            "conflicting_evidence_ids": [
                                str(value) for value in decision.conflicting_evidence_ids
                            ],
                            "rationale": decision.rationale[:500],
                        },
                        lease_token=lease.token,
                    )
                    if support_status is not SupportStatus.INSUFFICIENT_EVIDENCE:
                        supporting = set(decision.supporting_evidence_ids)
                        conflicting = set(decision.conflicting_evidence_ids)
                        relations = {}
                        rationales = {}
                        for evidence_id in ids:
                            if evidence_id in conflicting:
                                relation = "contradicts"
                            elif evidence_id in supporting:
                                relation = "supports"
                            elif support_status is SupportStatus.CONFLICTING:
                                relation = "contextualizes"
                            else:
                                relation = "supports"
                            relations[str(evidence_id)] = relation
                            rationales[str(evidence_id)] = decision.rationale[:1000]
                        persisted_claims.append(
                            FinalizedClaim(
                                text=claim.text,
                                evidence_ids=ids,
                                support_status=support_status,
                                checker_method=decision.checker_method,
                                checker_version=decision.checker_version,
                                assessment_state=decision.assessment_state,
                                assessment_rationale=decision.rationale,
                                evidence_relations=relations,
                                evidence_rationales=rationales,
                            )
                        )
            if not persisted_claims:
                self._partial_or_fail(
                    lease,
                    code="INSUFFICIENT_EVIDENCE",
                    message="Synthesis produced no claim that passed the current evidence checks.",
                )
                return
            checked_markdown = compose_checked_markdown(persisted_claims)
            self.repository.finalize_answer(
                run_id, checked_markdown, persisted_claims, result.gaps, lease_token=lease.token
            )
            self.repository.set_status(run_id, RunStatus.COMPLETED, lease_token=lease.token)
        except CancelledRun:
            return
        except RunCancelled:
            try:
                self.repository.set_status(run_id, RunStatus.CANCELLED, lease_token=lease.token)
            except Exception:
                pass
        except RunAuthorizationError as exc:
            self.repository.fail_run(run_id, "ACCESS_REVOKED", str(exc), lease_token=lease.token)
        except RunDeadlineExceeded as exc:
            self._partial_or_fail(lease, code="DEADLINE_EXCEEDED", message=str(exc))
        except RunBudgetExceededError as exc:
            self._partial_or_fail(lease, code="BUDGET_EXCEEDED", message=str(exc))
        except QuotaExceededError as exc:
            self._partial_or_fail(lease, code="QUOTA_EXHAUSTED", message=str(exc))
        except SearchProviderError as exc:
            self.repository.fail_run(
                run_id, "SEARCH_UNAVAILABLE", str(exc), lease_token=lease.token
            )
        except LLMProviderError as exc:
            self.repository.fail_run(run_id, "MODEL_UNAVAILABLE", str(exc), lease_token=lease.token)
        except Exception as exc:
            self.repository.fail_run(run_id, "UNEXPECTED_ERROR", str(exc), lease_token=lease.token)


class DemoResearchEngine:
    """A keyless, deterministic vertical slice using recorded fixture-like evidence."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def execute(self, lease: JobLease) -> None:
        run_id = lease.run_id
        run = self.repository.get_run(run_id)
        stages = [
            RunStatus.PLANNING,
            RunStatus.DISCOVERING,
            RunStatus.READING,
            RunStatus.EXTRACTING,
            RunStatus.CHECKING,
            RunStatus.SYNTHESIZING,
        ]
        for stage in stages:
            if self.repository.is_cancel_requested(run_id, lease_token=lease.token):
                self.repository.set_status(run_id, RunStatus.CANCELLED, lease_token=lease.token)
                return
            self.repository.set_status(run_id, stage, lease_token=lease.token)

        captured = datetime.now(UTC)
        first = self.repository.add_source_and_evidence(
            run_id,
            title="ARES Blueprint — Evidence Architecture",
            url="https://example.invalid/ares-blueprint/evidence",
            domain="example.invalid",
            fetched_at=captured,
            extraction_method="recorded-demo",
            content_hash="demo-evidence-v1",
            passage=(
                "An evidence span must match the stored normalized document version. Immutable content "
                "hashes allow citations to remain inspectable after a page changes."
            ),
            locator="Blueprint §26 · recorded demo excerpt",
            lease_token=lease.token,
        )
        second = self.repository.add_source_and_evidence(
            run_id,
            title="ARES Blueprint — Citation Architecture",
            url="https://example.invalid/ares-blueprint/citations",
            domain="example.invalid",
            fetched_at=captured,
            extraction_method="recorded-demo",
            content_hash="demo-citations-v1",
            passage=(
                "The model returns structured answer blocks referencing existing claim/evidence IDs. "
                "The server assigns display numbers and resolves titles/URLs from records."
            ),
            locator="Blueprint §28 · recorded demo excerpt",
            lease_token=lease.token,
        )
        markdown = (
            "### Recorded demo\n\nARES is designed so answers stay traceable to stored evidence rather than "
            f"model-invented links. For your query — **{run.query}** — this keyless run demonstrates the "
            "same durable run, event, evidence, and citation path used by live mode.\n\n"
            "The demo intentionally does **not** claim to have searched the live web or called Gemini."
        )
        self.repository.finalize_answer(
            run_id,
            markdown,
            [
                ("ARES preserves evidence as immutable, inspectable records.", [first]),
                (
                    "Citation display numbers are assigned by the server from stored evidence IDs.",
                    [second],
                ),
            ],
            [],
            lease_token=lease.token,
        )
        self.repository.set_status(run_id, RunStatus.COMPLETED, lease_token=lease.token)
