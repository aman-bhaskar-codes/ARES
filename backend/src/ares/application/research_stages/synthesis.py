from __future__ import annotations

import re
from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ares.application.run_context import RunContext, RunDeadlineExceeded
from ares.application.observability import RunTelemetry
from ares.domain.budgets import calculate_provider_cost
from ares.domain.models import (
    FetchedDocument,
    SearchHit,
)


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


class SynthesisStage:
    def __init__(self, engine):
        self.engine = engine

    def _synthesize(self, context: RunContext, query: str, evidence, max_output_tokens: int):
        context.check()
        timeout = context.clamp_timeout(self.engine.gemini_timeout_seconds)
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(
            self.engine.llm.synthesize, query, evidence, max_output_tokens=max_output_tokens, timeout_seconds=timeout
        )
        try:
            result = future.result(timeout=timeout)
            context.check()
            return result
        except TimeoutError as exc:
            future.cancel()
            raise RunDeadlineExceeded(
                "Gemini synthesis exceeded the remaining run deadline"
            ) from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _semantic_assess_claim(
        self, context: RunContext, *, claim: str, evidence, telemetry: RunTelemetry
    ):
        if self.engine.semantic_checker is None:
            return None
        estimated_input_tokens = max(
            1, (len(claim) + sum(len(packet.text) for packet in evidence) + 1200) // 4
        )
        context.consume(llm_calls=1, model_input_tokens=estimated_input_tokens)
        estimated_output_tokens = 500
        cost_usd = calculate_provider_cost(
            self.engine.semantic_checker_model,
            estimated_input_tokens,
            estimated_output_tokens
        )
        usage_id = self.engine.repository.reserve_provider_usage(
            provider="gemini",
            model=self.engine.semantic_checker_model,
            rpm=self.engine.gemini_rpm,
            tpm=self.engine.gemini_tpm,
            rpd=self.engine.gemini_rpd,
            input_tokens=estimated_input_tokens,
            output_tokens=estimated_output_tokens,
            cost_usd=cost_usd,
            max_daily_spend_usd=self.engine.gemini_max_daily_spend_usd,
            run_id=context.lease.run_id,
        )
        try:
            with self.engine._resource_slot(
                context,
                resource_key=f"provider:gemini:{self.engine.semantic_checker_model}",
                capacity=self.engine.gemini_concurrency,
                ttl_seconds=max(30, int(context.remaining_seconds())),
            ):
                with telemetry.stage("evaluation.semantic_claim", evidence=len(evidence)):
                    context.check()
                    timeout = context.clamp_timeout(self.engine.semantic_checker_timeout_seconds)
                    pool = ThreadPoolExecutor(max_workers=1)
                    future = pool.submit(
                        self.engine.semantic_checker.assess_claim,
                        claim,
                        evidence,
                        timeout_seconds=timeout,
                    )
                    try:
                        decision = future.result(timeout=timeout)
                        context.check()
                    except TimeoutError as exc:
                        future.cancel()
                        raise RunDeadlineExceeded(
                            "Semantic claim assessment exceeded the remaining run deadline"
                        ) from exc
                    finally:
                        pool.shutdown(wait=False, cancel_futures=True)
            self.engine.repository.reconcile_provider_usage(
                usage_id, input_tokens_actual=None, output_tokens_actual=None
            )
            return decision
        except Exception:
            # The conservative reservation remains recorded even when the remote call fails.
            self.engine.repository.reconcile_provider_usage(
                usage_id, input_tokens_actual=None, output_tokens_actual=None
            )
            raise
