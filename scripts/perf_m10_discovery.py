#!/usr/bin/env python3
"""M10 same-fixture sequential-vs-bounded-concurrent Quick-run benchmark.

The sequential control (`discovery_concurrency=1`) reproduces the M07-shaped discovery
ordering on the *same current contracts and fixture providers*. It is not a claim about live
internet/provider latency and it is not a historical M07 binary benchmark.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ares.adapters.db import Base, build_session_factory
from ares.application.engine import ResearchEngine
from ares.application.repository import Repository
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


class Planner:
    def plan(self, query, mode, date_window=None):
        return ResearchPlan(query_variants=[query], facets=[], language="all")


class DelayProbe:
    def __init__(self, delay_seconds: float):
        self.delay = delay_seconds
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def work(self) -> None:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay)
        finally:
            with self.lock:
                self.active -= 1


class Search:
    def __init__(self, probe: DelayProbe):
        self.probe = probe

    def search(self, request: SearchRequest):
        self.probe.work()
        return [
            SearchHit(
                title="web fixture",
                url="https://fixture.example/web",
                rank=1,
                provider="fixture-web",
            )
        ]


class Documents:
    def __init__(self, probe: DelayProbe, kind: str):
        self.probe, self.kind = probe, kind

    def search_documents(self, query: str, **kwargs):
        self.probe.work()
        url = f"https://fixture.example/{self.kind}"
        hit = SearchHit(
            title=f"{self.kind} fixture",
            url=url,
            rank=1,
            provider=f"fixture-{self.kind}",
            source_kind="academic" if self.kind == "academic" else "software",
            canonical_identifier=(
                "doi:10.5555/fixture" if self.kind == "academic" else "github:fixture/research"
            ),
        )
        text = (
            f"Fixture research latency evidence from the {self.kind} source supports bounded discovery. "
            * 14
        )
        doc = FetchedDocument(
            title=hit.title,
            url=url,
            final_url=url,
            text=text,
            content_hash=(self.kind[0] * 64),
            fetched_at=datetime.now(UTC),
            extraction_method="fixture",
            source_kind=hit.source_kind,
            canonical_identifier=hit.canonical_identifier,
        )
        return [(hit, doc)]


class Fetcher:
    def fetch(self, url: str, **kwargs):
        text = (
            "Fixture research latency evidence from the web source supports bounded discovery. "
            * 14
        )
        return FetchedDocument(
            source_id=uuid4(),
            title="web fixture",
            url=url,
            final_url=url,
            text=text,
            content_hash="w" * 64,
            fetched_at=datetime.now(UTC),
            extraction_method="fixture",
        )


class LLM:
    def synthesize(
        self, query: str, evidence: list[EvidencePacket], *, max_output_tokens: int, **kwargs
    ):
        # Use a short source-grounded statement so deterministic checking stays identical in both arms.
        packet = evidence[0]
        return SynthesisResult(
            summary_markdown="fixture",
            claims=[
                SynthesizedClaim(
                    text="Fixture research latency evidence supports bounded discovery.",
                    evidence_ids=[packet.evidence_id],
                )
            ],
            gaps=[],
        )


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))]


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(percentile(values, 0.95), 3),
        "max_ms": round(max(values), 3),
    }


def run_arm(
    root: Path, *, runs: int, concurrency: int, delay_seconds: float
) -> tuple[list[float], int]:
    db_engine, sessions = build_session_factory(
        f"sqlite+pysqlite:///{root / f'arm-{concurrency}.sqlite3'}"
    )
    Base.metadata.create_all(db_engine)
    repository = Repository(sessions)
    probe = DelayProbe(delay_seconds)
    engine = ResearchEngine(
        repository,
        Search(probe),
        Fetcher(),
        LLM(),
        gemini_model="fixture",
        gemini_rpm=10_000,
        gemini_tpm=10_000_000,
        gemini_rpd=10_000,
        planner=Planner(),
        academic=Documents(probe, "academic"),
        software=Documents(probe, "software"),
        discovery_concurrency=concurrency,
        research_cache_enabled=False,
    )
    conversation = repository.create_conversation(f"M10 perf concurrency={concurrency}")
    elapsed: list[float] = []
    try:
        for index in range(runs):
            run, _ = repository.create_run(
                RunCreate(
                    conversation_id=conversation.id,
                    query="fixture research latency evidence",
                    mode=RunMode.QUICK,
                    source_scope=["web", "academic", "software"],
                ),
                idempotency_key=f"m10-perf-{concurrency}-{index}",
            )
            lease = repository.claim_next_job()
            if lease is None:
                raise RuntimeError("fixture worker could not claim run")
            started = time.perf_counter()
            engine.execute(lease)
            elapsed.append((time.perf_counter() - started) * 1000.0)
            repository.finish_job(lease)
            snapshot = repository.get_run(run.id)
            if snapshot.status is not RunStatus.COMPLETED:
                raise RuntimeError(f"fixture run ended as {snapshot.status}")
    finally:
        engine.close()
        db_engine.dispose()
    return elapsed, probe.max_active


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--provider-delay-ms", type=float, default=50.0)
    parser.add_argument("--output", default="evals/reports/m10_discovery_perf.json")
    parser.add_argument("--target-percent", type=float, default=20.0)
    args = parser.parse_args()
    if args.runs < 5:
        parser.error("--runs must be >= 5")
    with tempfile.TemporaryDirectory(prefix="ares-m10-perf-") as temp:
        root = Path(temp)
        sequential, sequential_max = run_arm(
            root, runs=args.runs, concurrency=1, delay_seconds=args.provider_delay_ms / 1000.0
        )
        concurrent, concurrent_max = run_arm(
            root, runs=args.runs, concurrency=3, delay_seconds=args.provider_delay_ms / 1000.0
        )
    seq = summarize(sequential)
    conc = summarize(concurrent)
    reduction = ((seq["p95_ms"] - conc["p95_ms"]) / seq["p95_ms"] * 100.0) if seq["p95_ms"] else 0.0
    passed = reduction >= args.target_percent and sequential_max == 1 and concurrent_max >= 2
    report = {
        "schema_version": 1,
        "scope": "same-fixture Quick-run A/B; sequential M07-shaped control vs M10 bounded concurrent discovery",
        "important_limit": "Synthetic provider delays and local SQLite. This does not establish live-provider or production p95 and is not a historical M07 binary measurement.",
        "runs_per_arm": args.runs,
        "provider_delay_ms": args.provider_delay_ms,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "sequential_control": {
            "discovery_concurrency": 1,
            "max_observed_parallel_tracks": sequential_max,
            **seq,
        },
        "m10_concurrent": {
            "discovery_concurrency": 3,
            "max_observed_parallel_tracks": concurrent_max,
            **conc,
        },
        "p95_reduction_percent": round(reduction, 2),
        "target_percent": args.target_percent,
        "gate_passed": passed,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
