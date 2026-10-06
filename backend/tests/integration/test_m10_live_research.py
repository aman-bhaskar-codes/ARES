from __future__ import annotations

import threading
import pytest
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ares.adapters.db import Base, build_session_factory
from ares.application.engine import ResearchEngine
from ares.application.observability import RunTelemetry
from ares.application.providers import ProviderRegistry
from ares.application.providers import ProviderCapabilities, ProviderMetadata
from ares.application.repository import Repository
from ares.application.run_context import RunContext
from ares.domain.budgets import BUDGETS
from ares.domain.models import (
    FetchedDocument,
    RunCreate,
    RunMode,
    RunStatus,
    SearchHit,
    SynthesizedClaim,
    SynthesisResult,
)
from ares.domain.research import EvidencePacket, ResearchPlan, SearchRequest


class OneVariantPlanner:
    def plan(self, query, mode, date_window=None):
        return ResearchPlan(query_variants=[query], facets=["answer"], language="all")


class ConcurrencyProbe:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def enter(self) -> None:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    def leave(self) -> None:
        with self.lock:
            self.active -= 1


class SlowWebSearch:
    def __init__(self, probe: ConcurrencyProbe, *, calls=None) -> None:
        self.probe = probe
        self.calls = calls if calls is not None else []

    @property
    def metadata(self):
        return ProviderMetadata(
            name="fixture-web",
            source_kind="web",
            capabilities=ProviderCapabilities(supports_time_range=False, supports_full_text=False, supports_exact_id=False),
            cost_class="free",
            timeout_seconds=10.0,
            rate_limit_rpm=None,
            cache_ttl_seconds=0,
        )

    def search(self, request: SearchRequest):
        self.calls.append(request.query)
        self.probe.enter()
        try:
            time.sleep(0.08)
            return [
                SearchHit(
                    title="web", url="https://example.com/web", rank=1, provider="fixture-web"
                )
            ]
        finally:
            self.probe.leave()


class SlowDocumentProvider:
    def __init__(self, probe: ConcurrencyProbe, kind: str, *, calls=None) -> None:
        self.probe = probe
        self.kind = kind
        self.calls = calls if calls is not None else []

    @property
    def metadata(self):
        return ProviderMetadata(
            name=f"fixture-{self.kind}",
            source_kind="academic" if self.kind == "academic" else "software",
            capabilities=ProviderCapabilities(supports_time_range=True, supports_full_text=True, supports_exact_id=False),
            cost_class="free",
            timeout_seconds=10.0,
            rate_limit_rpm=None,
            cache_ttl_seconds=0,
        )

    def search_documents(self, query: str, **kwargs):
        self.calls.append(query)
        self.probe.enter()
        try:
            time.sleep(0.08)
            url = f"https://example.com/{self.kind}"
            hit = SearchHit(
                title=self.kind,
                url=url,
                rank=1,
                provider=f"fixture-{self.kind}",
                source_kind="academic" if self.kind == "academic" else "software",
            )
            doc = FetchedDocument(
                title=self.kind,
                url=url,
                final_url=url,
                text=f"The {self.kind} fixture contains enough evidence for bounded concurrent discovery testing. "
                * 3,
                content_hash=(self.kind[0] * 64),
                fetched_at=datetime.now(UTC),
                extraction_method="fixture",
                source_kind=hit.source_kind,
            )
            return [(hit, doc)]
        finally:
            self.probe.leave()


class FixtureFetcher:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, url: str, **kwargs):
        self.calls += 1
        return FetchedDocument(
            source_id=uuid4(),
            title="web",
            url=url,
            final_url=url,
            text="The web fixture supports this claim with sufficient source text for retrieval. "
            * 4,
            content_hash="f" * 64,
            fetched_at=datetime.now(UTC),
            extraction_method="fixture",
        )


class FixtureLLM:
    def synthesize(
        self, query: str, evidence: list[EvidencePacket], *, max_output_tokens: int, **kwargs
    ):
        return SynthesisResult(
            summary_markdown="fixture",
            claims=[
                SynthesizedClaim(
                    text="The web fixture supports this claim.",
                    evidence_ids=[evidence[0].evidence_id],
                )
            ],
            gaps=[],
        )


def repository_for(tmp_path: Path):
    engine, sessions = build_session_factory(f"sqlite+pysqlite:///{tmp_path / 'm10.sqlite3'}")
    Base.metadata.create_all(engine)
    return Repository(sessions)


def make_engine(repository: Repository, search, fetcher, *, academic=None, software=None):
    registry = ProviderRegistry()
    registry.register(search)
    if academic:
        registry.register(academic)
    if software:
        registry.register(software)
        
    return ResearchEngine(
        repository,
        search,
        fetcher,
        FixtureLLM(),
        gemini_model="fixture",
        gemini_rpm=20,
        gemini_tpm=100_000,
        gemini_rpd=100,
        planner=OneVariantPlanner(),
        registry=registry,
        discovery_concurrency=3,
        research_cache_enabled=True,
    )


def test_independent_discovery_tracks_overlap_in_time(tmp_path: Path) -> None:
    repository = repository_for(tmp_path)
    conversation = repository.create_conversation("M10 discovery")
    run, _ = repository.create_run(
        RunCreate(
            conversation_id=conversation.id,
            query="compare discovery tracks",
            mode=RunMode.QUICK,
            source_scope=["web", "academic", "software"],
        ),
        idempotency_key="m10-concurrent-discovery",
    )
    lease = repository.claim_next_job()
    assert lease is not None
    context = RunContext.create(repository, lease, BUDGETS[RunMode.QUICK])
    probe = ConcurrencyProbe()
    engine = make_engine(
        repository,
        SlowWebSearch(probe),
        FixtureFetcher(),
        academic=SlowDocumentProvider(probe, "academic"),
        software=SlowDocumentProvider(probe, "software"),
    )
    hits, academic, software, plan = engine.discovery._discover_tracks(
        lease,
        context,
        repository.get_run(run.id),
        BUDGETS[RunMode.QUICK],
        RunTelemetry(repository, lease),
    )
    assert hits and academic and software
    assert plan.facets == ["answer"]
    assert probe.max_active >= 2  # A sequential implementation can never exceed one active track.
    assert repository.get_run(run.id).usage_ledger["search_requests"] == 3


def test_workspace_scoped_cache_avoids_duplicate_provider_and_source_calls(tmp_path: Path) -> None:
    repository = repository_for(tmp_path)
    probe = ConcurrencyProbe()
    search_calls: list[str] = []
    search = SlowWebSearch(probe, calls=search_calls)
    fetcher = FixtureFetcher()
    engine = make_engine(repository, search, fetcher)

    for index in range(2):
        conversation = repository.create_conversation(f"Cache run {index}")
        run, _ = repository.create_run(
            RunCreate(
                conversation_id=conversation.id,
                query="same cached research",
                mode=RunMode.QUICK,
                source_scope=["web"],
            ),
            idempotency_key=f"m10-cache-{index}",
        )
        lease = repository.claim_next_job()
        assert lease is not None
        engine.execute(lease)
        repository.finish_job(lease)
        snapshot = repository.get_run(run.id)
        assert snapshot.status is RunStatus.COMPLETED
        if index == 1:
            assert any(event.event_type == "cache.hit" for event in repository.list_events(run.id))
            # Provider attempts, not cache reuse, consume the search-request budget.
            assert int(snapshot.usage_ledger.get("search_requests", 0)) == 0

    assert search_calls == ["same cached research"]
    assert fetcher.calls == 1


def test_claim_evidence_edges_persist_relation_rationale_and_checker_version(
    tmp_path: Path,
) -> None:
    from sqlalchemy import select
    from ares.adapters.db import ClaimEvidenceRow
    from ares.domain.models import FinalizedClaim, SupportStatus

    repository = repository_for(tmp_path)
    conversation = repository.create_conversation("M10 edges")
    run, _ = repository.create_run(
        RunCreate(conversation_id=conversation.id, query="edge semantics", mode=RunMode.QUICK),
        idempotency_key="m10-edge-semantics",
    )
    lease = repository.claim_next_job()
    assert lease is not None
    # Use the normal evidence persistence path so answer finalization cannot reference foreign IDs.
    doc = FixtureFetcher().fetch("https://example.com/edge")
    from ares.domain.research import EvidenceCandidate

    candidate = EvidenceCandidate(
        source_id=doc.source_id,
        title=doc.title,
        url=doc.url,
        text=doc.text,
        locator="fixture",
        char_start=0,
        char_end=len(doc.text),
    )
    evidence = repository.persist_document_evidence(
        run.id, document=doc, candidates=[candidate], provider="fixture", lease_token=lease.token
    )[0]
    repository.finalize_answer(
        run.id,
        "checked",
        [
            FinalizedClaim(
                text="A checked claim",
                evidence_ids=[evidence.evidence_id],
                support_status=SupportStatus.CONFLICTING,
                checker_method="gemini_semantic",
                checker_version="m10-v1",
                assessment_state="semantic_assessed",
                assessment_rationale="conflicting benchmark",
                evidence_relations={str(evidence.evidence_id): "contradicts"},
                evidence_rationales={
                    str(evidence.evidence_id): "This source reports the opposing result."
                },
            )
        ],
        [],
        lease_token=lease.token,
    )
    with repository._sessions() as session:
        edge = session.scalar(select(ClaimEvidenceRow))
        assert edge is not None
        assert edge.relation == "contradicts"
        assert edge.checker_method == "gemini_semantic"
        assert edge.checker_version == "m10-v1"
        assert "opposing" in edge.rationale


def test_quality_view_exposes_m10_facets_and_edge_semantics(tmp_path: Path) -> None:
    from ares.domain.decisions import FacetAssessment, FacetStatus
    from ares.domain.models import FinalizedClaim, SupportStatus
    from ares.domain.research import EvidenceCandidate

    repository = repository_for(tmp_path)
    conversation = repository.create_conversation("M10 quality")
    run, _ = repository.create_run(
        RunCreate(conversation_id=conversation.id, query="quality semantics", mode=RunMode.QUICK),
        idempotency_key="m10-quality-semantics",
    )
    lease = repository.claim_next_job()
    assert lease is not None
    doc = FixtureFetcher().fetch("https://example.com/quality")
    candidate = EvidenceCandidate(
        source_id=doc.source_id,
        title=doc.title,
        url=doc.url,
        text=doc.text,
        locator="fixture",
        char_start=0,
        char_end=len(doc.text),
    )
    evidence = repository.persist_document_evidence(
        run.id, document=doc, candidates=[candidate], provider="fixture", lease_token=lease.token
    )[0]
    repository.persist_facet_coverage(
        run.id,
        [
            FacetAssessment(
                facet="answer",
                status=FacetStatus.CONFLICTING,
                supporting_evidence_ids=[evidence.evidence_id],
                conflicting_evidence_ids=[evidence.evidence_id],
                rationale="fixture conflict retained",
            )
        ],
        checker_method="deterministic",
        checker_version="m10-v1",
        lease_token=lease.token,
    )
    repository.finalize_answer(
        run.id,
        "checked",
        [
            FinalizedClaim(
                text="A checked claim",
                evidence_ids=[evidence.evidence_id],
                support_status=SupportStatus.CONFLICTING,
                checker_method="gemini_semantic",
                checker_version="m10-v1",
                assessment_state="semantic_assessed",
                assessment_rationale="fixture conflict retained",
                evidence_relations={str(evidence.evidence_id): "contradicts"},
                evidence_rationales={str(evidence.evidence_id): "Opposing result."},
            )
        ],
        [],
        lease_token=lease.token,
    )
    quality = repository.get_run_quality(run.id)
    assert quality.evidence_relation_counts == {"contradicts": 1}
    assert quality.evidence_relations[0].checker_method == "gemini_semantic"
    assert quality.facets[0].facet_key == "answer"
    assert quality.facets[0].status == "conflicting"
    assert quality.facets[0].independent_origin_count == 1
    assert quality.facets[0].supporting_evidence_ids == [evidence.evidence_id]
    assert quality.facets[0].conflicting_evidence_ids == [evidence.evidence_id]


def test_web_cache_identity_normalizes_case_and_whitespace(tmp_path: Path) -> None:
    repository = repository_for(tmp_path)
    probe = ConcurrencyProbe()
    calls: list[str] = []
    engine = make_engine(repository, SlowWebSearch(probe, calls=calls), FixtureFetcher())
    for index, query in enumerate(["Same   Research Query", " same research query "]):
        conversation = repository.create_conversation(f"normalized cache {index}")
        run, _ = repository.create_run(
            RunCreate(
                conversation_id=conversation.id,
                query=query,
                mode=RunMode.QUICK,
                source_scope=["web"],
            ),
            idempotency_key=f"m10-normalized-cache-{index}",
        )
        lease = repository.claim_next_job()
        assert lease is not None
        engine.execute(lease)
        repository.finish_job(lease)
        assert repository.get_run(run.id).status is RunStatus.COMPLETED
    assert calls == ["Same   Research Query"]


class FixtureAcademicFullTextFetcher:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_pdf(self, url: str, **kwargs):
        self.calls += 1
        text = "Full paper evidence supports the requested academic claim. " * 20
        return FetchedDocument(
            title="paper.pdf",
            url=url,
            final_url=url,
            text=text,
            content_hash="a" * 64,
            fetched_at=datetime.now(UTC),
            extraction_method="academic-pdf:fixture",
            mime_type="application/pdf",
            byte_count=len(text),
            page_map=[{"page": 1, "char_start": 0, "char_end": len(text)}],
        )


def test_academic_open_full_text_replaces_metadata_but_keeps_provenance_and_cache(
    tmp_path: Path,
) -> None:
    repository = repository_for(tmp_path)
    fulltext = FixtureAcademicFullTextFetcher()
    metadata_text = "Title: Paper\n\nAbstract\nMetadata abstract only."
    hit = SearchHit(
        title="Paper",
        url="https://example.org/paper",
        rank=1,
        provider="fixture-academic",
        source_kind="academic",
        canonical_identifier="doi:10.1/example",
        full_text_url="https://example.org/paper.pdf",
        full_text_mime_type="application/pdf",
    )
    metadata = FetchedDocument(
        title="Paper",
        url=hit.url,
        final_url=hit.url,
        text=metadata_text,
        content_hash="m" * 64,
        fetched_at=datetime.now(UTC),
        extraction_method="fixture-metadata-abstract",
        source_kind="academic",
        canonical_identifier="doi:10.1/example",
    )

    class Academic:
        @property
        def metadata(self):
            return ProviderMetadata(
                name="fixture-academic",
                source_kind="academic",
                capabilities=ProviderCapabilities(supports_time_range=True, supports_full_text=True, supports_exact_id=False),
                cost_class="free",
                timeout_seconds=10.0,
                rate_limit_rpm=None,
                cache_ttl_seconds=0,
            )
            
        def search_documents(self, query: str, **kwargs):
            return [(hit, metadata)]

    registry = ProviderRegistry()
    registry.register(SlowWebSearch(ConcurrencyProbe()))
    registry.register(Academic())
    
    engine = ResearchEngine(
        repository,
        SlowWebSearch(ConcurrencyProbe()),
        FixtureFetcher(),
        FixtureLLM(),
        gemini_model="fixture",
        gemini_rpm=20,
        gemini_tpm=100_000,
        gemini_rpd=100,
        planner=OneVariantPlanner(),
        registry=registry,
        discovery_concurrency=3,
        research_cache_enabled=True,
        academic_full_text_fetcher=fulltext,
        academic_full_text_limit=1,
    )
    for index in range(2):
        conversation = repository.create_conversation(f"fulltext {index}")
        run, _ = repository.create_run(
            RunCreate(
                conversation_id=conversation.id,
                query="academic full text",
                mode=RunMode.QUICK,
                source_scope=["academic"],
            ),
            idempotency_key=f"m10-fulltext-{index}",
        )
        lease = repository.claim_next_job()
        assert lease is not None
        context = RunContext.create(repository, lease, BUDGETS[RunMode.QUICK])
        # Academic documents are returned as the second discovery track result.
        _, academic_rows, _, _ = engine.discovery._discover_tracks(
            lease,
            context,
            repository.get_run(run.id),
            BUDGETS[RunMode.QUICK],
            RunTelemetry(repository, lease),
        )
        assert academic_rows[0][1].extraction_method == "academic-pdf:fixture"
        assert academic_rows[0][1].canonical_identifier == "doi:10.1/example"
        assert academic_rows[0][1].page_map[0]["page"] == 1
        repository.finish_job(lease)
    # Both the metadata query and parsed full text are workspace-scoped cached artifacts.
    assert fulltext.calls == 1


def test_rate_limited_web_track_does_not_discard_successful_academic_track(tmp_path: Path) -> None:
    from ares.ports.errors import ProviderRateLimitError

    class RateLimitedWeb:
        @property
        def metadata(self):
            return ProviderMetadata(
                name="fixture-ratelimited-web",
                source_kind="web",
                capabilities=ProviderCapabilities(supports_time_range=False, supports_full_text=False, supports_exact_id=False),
                cost_class="free",
                timeout_seconds=10.0,
                rate_limit_rpm=None,
                cache_ttl_seconds=0,
            )
            
        def search(self, request: SearchRequest):
            raise ProviderRateLimitError("fixture 429", retry_after_seconds=7.0)

    repository = repository_for(tmp_path)
    conversation = repository.create_conversation("M10 429")
    run, _ = repository.create_run(
        RunCreate(
            conversation_id=conversation.id,
            query="provider backoff",
            mode=RunMode.QUICK,
            source_scope=["web", "academic"],
        ),
        idempotency_key="m10-provider-429",
    )
    lease = repository.claim_next_job()
    assert lease is not None
    context = RunContext.create(repository, lease, BUDGETS[RunMode.QUICK])
    probe = ConcurrencyProbe()
    engine = make_engine(
        repository,
        RateLimitedWeb(),
        FixtureFetcher(),
        academic=SlowDocumentProvider(probe, "academic"),
    )
    web_rows, academic_rows, software_rows, _ = engine.discovery._discover_tracks(
        lease,
        context,
        repository.get_run(run.id),
        BUDGETS[RunMode.QUICK],
        RunTelemetry(repository, lease),
    )
    assert web_rows == [] and software_rows == []
    assert academic_rows
    events = repository.list_events(run.id)
    backoffs = [event for event in events if event.event_type == "provider.backoff"]
    assert len(backoffs) == 1
    assert backoffs[0].payload["track"] == "web"
    assert backoffs[0].payload["retry_after_seconds"] == 7.0


def test_date_window_is_part_of_academic_cache_identity(tmp_path: Path) -> None:
    from ares.domain.models import DateWindow

    calls: list[tuple[object, object]] = []

    class WindowedAcademic:
        @property
        def metadata(self):
            return ProviderMetadata(
                name="fixture-windowed",
                source_kind="academic",
                capabilities=ProviderCapabilities(supports_time_range=True, supports_full_text=True, supports_exact_id=False),
                cost_class="free",
                timeout_seconds=10.0,
                rate_limit_rpm=None,
                cache_ttl_seconds=0,
            )
            
        def search_documents(self, query: str, **kwargs):
            calls.append((kwargs.get("published_after"), kwargs.get("published_before")))
            return []

    repository = repository_for(tmp_path)
    engine = make_engine(
        repository, SlowWebSearch(ConcurrencyProbe()), FixtureFetcher(), academic=WindowedAcademic()
    )
    windows = [
        DateWindow(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 12, 31, tzinfo=UTC)),
        DateWindow(start=datetime(2025, 1, 1, tzinfo=UTC), end=datetime(2025, 12, 31, tzinfo=UTC)),
    ]
    for index, window in enumerate(windows):
        conversation = repository.create_conversation(f"window {index}")
        run, _ = repository.create_run(
            RunCreate(
                conversation_id=conversation.id,
                query="same query",
                mode=RunMode.QUICK,
                source_scope=["academic"],
                date_window=window,
            ),
            idempotency_key=f"m10-window-{index}",
        )
        lease = repository.claim_next_job()
        assert lease is not None
        context = RunContext.create(repository, lease, BUDGETS[RunMode.QUICK])
        engine.discovery._cached_document_track(
            lease,
            context,
            track="academic",
            provider=engine.registry.get_provider("fixture-windowed"),
            query="same query",
            limit=3,
            ttl_seconds=3600,
        )
        repository.finish_job(lease)
    assert len(calls) == 2
    assert calls[0] != calls[1]


class FailingSemanticChecker:
    def assess_claim(self, claim, evidence, **kwargs):
        raise RuntimeError("fixture semantic outage")


class SlowSemanticChecker:
    def assess_claim(self, claim, evidence, **kwargs):
        time.sleep(0.20)
        raise AssertionError("slow semantic call should be fenced by worker timeout")


def test_semantic_checker_outage_keeps_conservative_deterministic_result(tmp_path: Path) -> None:
    repository = repository_for(tmp_path)
    conversation = repository.create_conversation("semantic outage")
    run, _ = repository.create_run(
        RunCreate(
            conversation_id=conversation.id,
            query="web fixture supports claim",
            mode=RunMode.QUICK,
            source_scope=["web"],
        ),
        idempotency_key="m10-semantic-outage",
    )
    lease = repository.claim_next_job()
    assert lease is not None
    engine = ResearchEngine(
        repository,
        SlowWebSearch(ConcurrencyProbe()),
        FixtureFetcher(),
        FixtureLLM(),
        gemini_model="fixture",
        gemini_rpm=100,
        gemini_tpm=100_000,
        gemini_rpd=100,
        planner=OneVariantPlanner(),
        research_cache_enabled=False,
        semantic_checker=FailingSemanticChecker(),
        semantic_checker_model="fixture-semantic",
        semantic_checker_max_claims=2,
    )
    engine.execute(lease)
    repository.finish_job(lease)
    snapshot = repository.get_run(run.id)
    assert snapshot.status is RunStatus.COMPLETED
    assert any(
        event.event_type == "semantic_checker.degraded" for event in repository.list_events(run.id)
    )
    answer = repository.get_run(run.id).answer_blocks
    assert answer and answer[0].claims
    assert answer[0].claims[0].assessment_state == "heuristic_screened"


def test_semantic_checker_has_worker_enforced_deadline_even_if_adapter_blocks(
    tmp_path: Path,
) -> None:
    from ares.application.run_context import RunDeadlineExceeded

    repository = repository_for(tmp_path)
    conversation = repository.create_conversation("semantic timeout")
    run, _ = repository.create_run(
        RunCreate(conversation_id=conversation.id, query="semantic timeout", mode=RunMode.QUICK),
        idempotency_key="m10-semantic-timeout",
    )
    lease = repository.claim_next_job()
    assert lease is not None
    context = RunContext.create(repository, lease, BUDGETS[RunMode.QUICK])
    engine = ResearchEngine(
        repository,
        SlowWebSearch(ConcurrencyProbe()),
        FixtureFetcher(),
        FixtureLLM(),
        gemini_model="fixture",
        gemini_rpm=100,
        gemini_tpm=100_000,
        gemini_rpd=100,
        planner=OneVariantPlanner(),
        semantic_checker=SlowSemanticChecker(),
        semantic_checker_model="fixture-semantic",
        semantic_checker_timeout_seconds=0.05,
    )
    packet = EvidencePacket(
        evidence_id=uuid4(),
        source_id=uuid4(),
        title="fixture",
        url="https://example.com/e",
        domain="example.com",
        text="bounded evidence text " * 20,
        locator="fixture",
        captured_at=datetime.now(UTC),
        content_hash="e" * 64,
    )
    started = time.perf_counter()
    with pytest.raises(RunDeadlineExceeded):
        engine.synthesis._semantic_assess_claim(
            context,
            claim="bounded evidence",
            evidence=[packet],
            telemetry=RunTelemetry(repository, lease),
        )
    assert time.perf_counter() - started < 0.15
