from __future__ import annotations

import re
from datetime import UTC, datetime
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4
from typing import Callable

from ares.application.run_context import RunContext, RunDeadlineExceeded
from ares.application.observability import RunTelemetry
from ares.application.repository import (
    JobLease,
    RunBudgetExceededError,
)
from ares.domain.models import (
    FetchedDocument,
    SearchHit,
)
from ares.domain.research import ResearchPlan, SearchRequest
from ares.ports.errors import ProviderRateLimitError


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


class DiscoveryStage:
    def __init__(self, engine):
        self.engine = engine

    def _cache_slot(self, context: RunContext, resource_key: str):
        return self.engine._resource_slot(
            context, resource_key=resource_key, capacity=1, ttl_seconds=30
        )

    @staticmethod
    def _cache_window_payload(context: RunContext) -> dict[str, object] | None:
        return context.date_window.model_dump(mode="json") if context.date_window else None

    def _fetch_documents(
        self, lease: JobLease, context: RunContext, hits: list[SearchHit], concurrency: int
    ) -> list[tuple[SearchHit, FetchedDocument]]:
        def fetch_one(hit: SearchHit):
            context.check()
            cache_key = {
                "url": _canonical_url(str(hit.url)),
                "provider": hit.provider,
                "source_kind": hit.source_kind,
                "policy": "safe-http-v1",
            }

            def compute():
                with self.engine._http_slots:
                    with self.engine._resource_slot(
                        context,
                        resource_key="http:public",
                        capacity=self.engine.global_http_concurrency,
                    ):
                        timeout = context.clamp_timeout(self.engine.source_fetch_timeout_seconds)
                        try:
                            document = self.engine.fetcher.fetch(
                                str(hit.url), timeout_seconds=timeout
                            )
                        except TypeError as exc:
                            # M06-compatible third-party/test fetchers may not yet expose the additive timeout kwarg.
                            if "timeout_seconds" not in str(exc):
                                raise
                            document = self.engine.fetcher.fetch(str(hit.url))
                return {"document": document.model_dump(mode="json")}, document.fetched_at

            payload, cache_hit, retrieved_at = self.engine.research_cache.get_or_compute(
                context,
                namespace="web.source",
                key_payload=cache_key,
                ttl_seconds=self.engine.web_source_cache_ttl_seconds,
                compute=compute,
                acquire_slot=lambda key: self._cache_slot(context, key),
            )
            raw = payload.get("document")
            if not isinstance(raw, dict):
                raise ValueError("cached web source payload is invalid")
            # Source IDs are run-scoped provenance identities. Never reuse one from a cache record.
            document = FetchedDocument.model_validate(raw).model_copy(update={"source_id": uuid4()})
            if document.extraction_method.startswith("browser-fallback:"):
                self.engine.repository.record_event(
                    lease.run_id,
                    "browser.fallback",
                    {
                        "url": str(hit.url),
                        "final_url": str(document.final_url),
                        "method": document.extraction_method,
                    },
                    lease_token=lease.token,
                )
            if cache_hit:
                self.engine.repository.record_event(
                    lease.run_id,
                    "cache.hit",
                    {
                        "namespace": "web.source",
                        "url": str(hit.url),
                        "retrieved_at": retrieved_at.isoformat() if retrieved_at else None,
                    },
                    lease_token=lease.token,
                )
            return hit, document

        documents: list[tuple[SearchHit, FetchedDocument]] = []
        iterator = iter(hits)
        pool = ThreadPoolExecutor(max_workers=concurrency)
        pending: set[Future] = set()
        try:
            for _ in range(concurrency):
                self.engine._check_cancel(lease, context)
                try:
                    pending.add(pool.submit(fetch_one, next(iterator)))
                except StopIteration:
                    break
            while pending:
                self.engine._check_cancel(lease, context)
                done, pending = wait(
                    pending,
                    timeout=min(0.25, max(0.01, context.remaining_seconds())),
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    continue
                for future in done:
                    try:
                        documents.append(future.result())
                    except (RunDeadlineExceeded, RunBudgetExceededError):
                        raise
                    except Exception as exc:
                        self.engine.repository.record_event(
                            lease.run_id,
                            "source.read_failed",
                            {"error": type(exc).__name__},
                            lease_token=lease.token,
                        )
                    try:
                        pending.add(pool.submit(fetch_one, next(iterator)))
                    except StopIteration:
                        pass
            return documents
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _search_web_query(
        self,
        lease: JobLease,
        context: RunContext,
        *,
        query: str,
        limit: int,
        language: str | None = None,
        time_range: str | None = None,
        wave: int = 1,
    ) -> tuple[list[SearchHit], bool]:
        """Execute one cacheable SearXNG query under the shared budget/resource ledger.

        Returning the cache-hit flag lets callers account provider request budgets without
        charging cache reuse. Recovery waves intentionally use this same path so retries do not
        bypass fleet limits, tenant cache boundaries, or freshness disclosure.
        """
        key_payload = {
            "query": _normalize_cache_query(query),
            "limit": limit,
            "language": language,
            "time_range": time_range,
            "date_window": self._cache_window_payload(context),
            "provider": "searxng",
        }

        def compute():
            context.consume(search_requests=1)
            with self.engine._resource_slot(
                context,
                resource_key="provider:searxng",
                capacity=self.engine.global_http_concurrency,
            ):
                rows = self.engine.search.search(
                    SearchRequest(
                        query=query,
                        limit=limit,
                        language=language,
                        time_range=time_range,
                        published_after=context.date_window.start if context.date_window else None,
                        published_before=context.date_window.end if context.date_window else None,
                        timezone=context.date_window.timezone if context.date_window else "UTC",
                        timeout_seconds=context.clamp_timeout(
                            self.engine.provider_http_timeout_seconds
                        ),
                    )
                )
            return {"hits": [row.model_dump(mode="json") for row in rows]}, datetime.now(UTC)

        cache_ttl = (
            min(self.engine.web_search_cache_ttl_seconds, 300)
            if time_range in {"day", "week"}
            else self.engine.web_search_cache_ttl_seconds
        )
        payload, cache_hit, retrieved_at = self.engine.research_cache.get_or_compute(
            context,
            namespace="web.search",
            key_payload=key_payload,
            ttl_seconds=cache_ttl,
            compute=compute,
            acquire_slot=lambda key: self._cache_slot(context, key),
        )
        raw_hits = payload.get("hits", [])
        hits = [SearchHit.model_validate(item) for item in raw_hits if isinstance(item, dict)]
        hits = [hit for hit in hits if _in_date_window(hit.published_at, context.date_window)]
        if cache_hit:
            self.engine.repository.record_event(
                lease.run_id,
                "cache.hit",
                {
                    "namespace": "web.search",
                    "query": query,
                    "wave": wave,
                    "retrieved_at": retrieved_at.isoformat() if retrieved_at else None,
                },
                lease_token=lease.token,
            )
        return hits, cache_hit

    def _discover(
        self,
        lease: JobLease,
        context: RunContext,
        query: str,
        mode,
        budget,
        *,
        max_requests: int | None = None,
        plan: ResearchPlan | None = None,
    ) -> list[SearchHit]:
        plan = plan or self.engine.planner.plan(query, mode, context.date_window)
        by_url: dict[str, SearchHit] = {}
        remaining = (
            min(budget.max_search_requests, max_requests)
            if max_requests is not None
            else budget.max_search_requests
        )
        per_query_limit = max(3, min(8, budget.max_documents))
        for variant in plan.query_variants:
            if remaining <= 0:
                break
            self.engine._check_cancel(lease, context)
            hits, cache_hit = self._search_web_query(
                lease,
                context,
                query=variant,
                limit=per_query_limit,
                language=plan.language,
                time_range=plan.time_range,
                wave=1,
            )
            remaining -= 0 if cache_hit else 1
            for hit in hits:
                if not _in_date_window(hit.published_at, context.date_window):
                    continue
                key = _canonical_url(str(hit.url))
                if key not in by_url:
                    by_url[key] = hit
                    self.engine.repository.record_event(
                        lease.run_id,
                        "source.found",
                        {
                            "title": hit.title,
                            "url": str(hit.url),
                            "rank": hit.rank,
                            "provider": hit.provider,
                        },
                        lease_token=lease.token,
                    )
                if len(by_url) >= budget.max_documents:
                    break
            if len(by_url) >= budget.max_documents:
                break
        return list(by_url.values())[: budget.max_documents]

    def _cached_document_track(
        self,
        lease: JobLease,
        context: RunContext,
        *,
        track: str,
        provider,
        query: str,
        limit: int,
        ttl_seconds: int,
    ) -> list[tuple[SearchHit, FetchedDocument]]:
        key_payload = {
            "query": _normalize_cache_query(query),
            "limit": limit,
            "date_window": self._cache_window_payload(context),
            "provider": track,
        }

        def compute():
            context.consume(search_requests=1)
            timeout = context.clamp_timeout(self.engine.provider_http_timeout_seconds)
            with self.engine._resource_slot(context, resource_key=f"provider:{track}", capacity=1):
                try:
                    rows = provider.search_documents(
                        query,
                        limit=limit,
                        timeout_seconds=timeout,
                        published_after=context.date_window.start if context.date_window else None,
                        published_before=context.date_window.end if context.date_window else None,
                    )
                except TypeError as exc:
                    if "timeout_seconds" not in str(exc):
                        raise
                    rows = provider.search_documents(query, limit=limit)
            packed = [
                {"hit": hit.model_dump(mode="json"), "document": document.model_dump(mode="json")}
                for hit, document in rows
            ]
            retrieved_at = max((doc.fetched_at for _, doc in rows), default=datetime.now(UTC))
            return {"rows": packed}, retrieved_at

        payload, cache_hit, retrieved_at = self.engine.research_cache.get_or_compute(
            context,
            namespace=f"{track}.discovery",
            key_payload=key_payload,
            ttl_seconds=ttl_seconds,
            compute=compute,
            acquire_slot=lambda key: self._cache_slot(context, key),
        )
        raw_rows = payload.get("rows", [])
        rows: list[tuple[SearchHit, FetchedDocument]] = []
        for raw in raw_rows:
            if (
                not isinstance(raw, dict)
                or not isinstance(raw.get("hit"), dict)
                or not isinstance(raw.get("document"), dict)
            ):
                continue
            hit = SearchHit.model_validate(raw["hit"])
            document = FetchedDocument.model_validate(raw["document"]).model_copy(
                update={"source_id": uuid4()}
            )
            if _in_date_window(document.published_at or hit.published_at, context.date_window):
                rows.append((hit, document))
        rows = _prioritize_exact_identifiers(query, rows)
        if cache_hit:
            self.engine.repository.record_event(
                lease.run_id,
                "cache.hit",
                {
                    "namespace": f"{track}.discovery",
                    "retrieved_at": retrieved_at.isoformat() if retrieved_at else None,
                },
                lease_token=lease.token,
            )
        for hit, _ in rows:
            self.engine.repository.record_event(
                lease.run_id,
                "source.found",
                {
                    "title": hit.title,
                    "url": str(hit.url),
                    "rank": hit.rank,
                    "provider": hit.provider,
                },
                lease_token=lease.token,
            )
        return rows

    def _enrich_academic_full_text(
        self, lease: JobLease, context: RunContext, rows: list[tuple[SearchHit, FetchedDocument]]
    ) -> list[tuple[SearchHit, FetchedDocument]]:
        if (
            self.engine.academic_full_text_fetcher is None
            or self.engine.academic_full_text_limit <= 0
        ):
            return rows
        output: list[tuple[SearchHit, FetchedDocument]] = []
        attempted = 0
        for hit, metadata_document in rows:
            full_text_url = str(hit.full_text_url) if hit.full_text_url is not None else ""
            if (
                not full_text_url
                or hit.full_text_mime_type != "application/pdf"
                or attempted >= self.engine.academic_full_text_limit
            ):
                output.append((hit, metadata_document))
                continue
            attempted += 1
            key_payload = {
                "url": _canonical_url(full_text_url),
                "canonical_identifier": hit.canonical_identifier,
                "parser_profile": "bounded-pypdf-m10-v1",
                "max_pages": self.engine.academic_full_text_max_pages,
            }

            def compute():
                self.engine._check_cancel(lease, context)
                timeout = context.clamp_timeout(self.engine.academic_full_text_timeout_seconds)
                with self.engine._resource_slot(
                    context,
                    resource_key="http:academic-fulltext",
                    capacity=self.engine.global_http_concurrency,
                ):
                    with self.engine._http_slots:
                        document = self.engine.academic_full_text_fetcher.fetch_pdf(
                            full_text_url,
                            timeout_seconds=timeout,
                            max_bytes=self.engine.academic_full_text_max_bytes,
                            max_pages=self.engine.academic_full_text_max_pages,
                            max_text_chars=500_000,
                        )
                enriched = document.model_copy(
                    update={
                        "title": metadata_document.title,
                        "url": metadata_document.url,
                        "source_kind": "academic",
                        "canonical_identifier": metadata_document.canonical_identifier
                        or hit.canonical_identifier,
                        "published_at": metadata_document.published_at or hit.published_at,
                    }
                )
                return {"document": enriched.model_dump(mode="json")}, enriched.fetched_at

            try:
                payload, cache_hit, retrieved_at = self.engine.research_cache.get_or_compute(
                    context,
                    namespace="academic.fulltext",
                    key_payload=key_payload,
                    ttl_seconds=self.engine.web_source_cache_ttl_seconds,
                    compute=compute,
                    acquire_slot=lambda key: self._cache_slot(context, key),
                )
                raw = payload.get("document")
                if not isinstance(raw, dict):
                    raise ValueError("academic full-text cache returned invalid document")
                document = FetchedDocument.model_validate(raw).model_copy(
                    update={"source_id": uuid4()}
                )
                output.append((hit, document))
                self.engine.repository.record_event(
                    lease.run_id,
                    "academic.fulltext_ready",
                    {
                        "canonical_identifier": hit.canonical_identifier,
                        "url": full_text_url,
                        "pages": len(document.page_map),
                        "cache_hit": cache_hit,
                        "retrieved_at": retrieved_at.isoformat() if retrieved_at else None,
                    },
                    lease_token=lease.token,
                )
            except (RunDeadlineExceeded, RunBudgetExceededError, CancelledRun):
                raise
            except Exception as exc:
                # Metadata/abstract evidence stays usable when the optional lawful full-text read fails.
                output.append((hit, metadata_document))
                self.engine.repository.record_event(
                    lease.run_id,
                    "academic.fulltext_unavailable",
                    {
                        "canonical_identifier": hit.canonical_identifier,
                        "url": full_text_url,
                        "error": type(exc).__name__,
                    },
                    lease_token=lease.token,
                )
        return output

    def _discover_tracks(
        self, lease: JobLease, context: RunContext, run, budget, telemetry: RunTelemetry
    ):
        plan = self.engine.planner.plan(run.query, run.mode, context.date_window)
        self.engine.repository.record_event(
            lease.run_id,
            "plan.ready",
            {
                "query_variants": plan.query_variants,
                "facets": plan.facets,
                "time_range": plan.time_range,
                "date_window": self._cache_window_payload(context),
            },
            lease_token=lease.token,
        )

        tasks: dict[str, Callable[[], object]] = {}
        if "web" in run.source_scope:
            discovery_request_budget = budget.max_search_requests - (
                1 if run.mode.value == "research" else 0
            )
            tasks["web"] = lambda: self._discover(
                lease,
                context,
                run.query,
                run.mode,
                budget,
                max_requests=max(1, discovery_request_budget),
                plan=plan,
            )
        if "academic" in run.source_scope:
            academic_providers = (
                self.engine.registry.get_providers_by_kind("academic")
                if self.engine.registry
                else []
            )
            if not academic_providers:
                self.engine.repository.record_event(
                    lease.run_id,
                    "tool.unavailable",
                    {"tool": "academic", "reason": "not configured"},
                    lease_token=lease.token,
                )
            else:

                def academic_task():
                    all_rows = []
                    for provider in academic_providers:
                        rows = self._cached_document_track(
                            lease,
                            context,
                            track=f"academic:{provider.metadata.name}",
                            provider=provider,
                            query=run.query,
                            limit=min(8, budget.max_documents),
                            ttl_seconds=self.engine.academic_cache_ttl_seconds,
                        )
                        all_rows.extend(
                            self._enrich_academic_full_text(lease, context, rows)
                        )
                    return all_rows

                tasks["academic"] = academic_task
        if "software" in run.source_scope:
            software_providers = (
                self.engine.registry.get_providers_by_kind("software")
                if self.engine.registry
                else []
            )
            if not software_providers:
                self.engine.repository.record_event(
                    lease.run_id,
                    "tool.unavailable",
                    {"tool": "software", "reason": "not configured"},
                    lease_token=lease.token,
                )
            else:

                def software_task():
                    all_rows = []
                    for provider in software_providers:
                        rows = self._cached_document_track(
                            lease,
                            context,
                            track=f"software:{provider.metadata.name}",
                            provider=provider,
                            query=run.query,
                            limit=min(5, budget.max_documents),
                            ttl_seconds=self.engine.software_cache_ttl_seconds,
                        )
                        all_rows.extend(rows)
                    return all_rows

                tasks["software"] = software_task

        results: dict[str, object] = {"web": [], "academic": [], "software": []}
        if not tasks:
            return results["web"], results["academic"], results["software"], plan
        pool = ThreadPoolExecutor(max_workers=min(self.engine.discovery_concurrency, len(tasks)))
        futures = {}
        try:
            for name, task in tasks.items():
                futures[pool.submit(task)] = name
            pending = set(futures)
            while pending:
                self.engine._check_cancel(lease, context)
                done, pending = wait(
                    pending,
                    timeout=min(0.25, max(0.01, context.remaining_seconds())),
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    name = futures[future]
                    try:
                        with telemetry.stage(f"discovery.{name}.complete"):
                            results[name] = future.result()
                    except (RunDeadlineExceeded, RunBudgetExceededError):
                        raise
                    except ProviderRateLimitError as exc:
                        self.engine.repository.record_event(
                            lease.run_id,
                            "provider.backoff",
                            {
                                "track": name,
                                "reason": "rate_limited",
                                "retry_after_seconds": exc.retry_after_seconds,
                                "message": str(exc)[:300],
                            },
                            lease_token=lease.token,
                        )
                        self.engine.repository.record_event(
                            lease.run_id,
                            "discovery.track_failed",
                            {"track": name, "error": type(exc).__name__, "message": str(exc)[:300]},
                            lease_token=lease.token,
                        )
                    except Exception as exc:
                        self.engine.repository.record_event(
                            lease.run_id,
                            "discovery.track_failed",
                            {"track": name, "error": type(exc).__name__, "message": str(exc)[:300]},
                            lease_token=lease.token,
                        )
            return results["web"], results["academic"], results["software"], plan
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
