#!/usr/bin/env python3
"""Reproducible M07 keyless-demo latency baseline.

This deliberately measures only in-process deterministic demo behavior. It is a
regression reference, not a live-provider or production throughput benchmark.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import platform
import statistics
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from ares.api.app import create_app
from ares.api.settings import Settings


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))]


def summary(values: list[float]) -> dict[str, float]:
    return {
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(percentile(values, 0.95), 3),
        "max_ms": round(max(values), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=60)
    parser.add_argument("--output", help="optional JSON report path")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")

    logging.getLogger("ares.api").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    admission: list[float] = []
    execution: list[float] = []
    replay: list[float] = []
    with tempfile.TemporaryDirectory(prefix="ares-m07-perf-") as temp:
        db = Path(temp) / "baseline.sqlite3"
        client = TestClient(
            create_app(Settings(ares_mode="demo", database_url=f"sqlite+pysqlite:///{db}"))
        )
        conversation = client.post("/api/v1/conversations", json={"title": "M07 perf baseline"})
        conversation.raise_for_status()
        conversation_id = conversation.json()["id"]
        for index in range(args.runs):
            started = time.perf_counter()
            created = client.post(
                "/api/v1/runs",
                headers={"Idempotency-Key": f"m07-perf-{index}"},
                json={
                    "conversation_id": conversation_id,
                    "query": f"Explain evidence provenance fixture {index}",
                    "mode": "quick",
                    "source_scope": ["web"],
                    "document_ids": [],
                },
            )
            admission.append((time.perf_counter() - started) * 1000)
            created.raise_for_status()
            run_id = created.json()["id"]

            started = time.perf_counter()
            worker = client.post("/api/v1/internal/worker/run-once")
            execution.append((time.perf_counter() - started) * 1000)
            worker.raise_for_status()
            assert worker.json().get("processed") is True

            started = time.perf_counter()
            events = client.get(f"/api/v1/runs/{run_id}/events", headers={"Last-Event-ID": "0"})
            replay.append((time.perf_counter() - started) * 1000)
            events.raise_for_status()
            if "run.completed" not in events.text:
                raise RuntimeError(f"run {run_id} did not produce a terminal replay")

    report = {
        "scope": "keyless deterministic demo only",
        "runs": args.runs,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.machine(),
        },
        "metrics": {
            "run_admission": summary(admission),
            "demo_execution": summary(execution),
            "durable_event_replay": summary(replay),
        },
    }
    encoded = json.dumps(report, indent=2, sort_keys=True)
    print(encoded)
    if args.output:
        Path(args.output).write_text(encoded + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
