#!/usr/bin/env python3
"""Operator smoke/load harness for ARES admission, cancellation, and queue behavior.

This is deliberately not a benchmark. It exercises the public HTTP contract and reports observed
latencies/statuses for one local run so backpressure regressions are visible before deployment.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import math
import statistics
import time
from dataclasses import dataclass
from uuid import uuid4

import httpx


@dataclass(frozen=True, slots=True)
class Submission:
    run_id: str | None
    status_code: int
    latency_ms: float
    admitted_at: float | None = None
    detail: str | None = None


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(percentile_value * len(ordered)) - 1))
    return ordered[rank]


def submit_run(base_url: str, conversation_id: str, query: str, timeout: float) -> Submission:
    started = time.perf_counter()
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        response = client.post(
            "/api/v1/runs",
            headers={"Idempotency-Key": f"load-smoke-{uuid4()}"},
            json={
                "conversation_id": conversation_id,
                "query": query,
                "mode": "quick",
                "source_scope": ["web"],
                "document_ids": [],
            },
        )
    latency_ms = (time.perf_counter() - started) * 1000
    if 200 <= response.status_code < 300:
        return Submission(response.json()["id"], response.status_code, latency_ms, admitted_at=time.perf_counter())
    try:
        payload = response.json()
        detail = payload.get("detail", payload)
        detail_text = detail.get("code") if isinstance(detail, dict) else str(detail)
    except Exception:
        detail_text = response.text[:160]
    return Submission(None, response.status_code, latency_ms, detail=detail_text)


def poll_terminal(base_url: str, admitted_at: dict[str, float], timeout: float) -> tuple[dict[str, int], list[float]]:
    terminal = {"completed", "partial", "failed", "cancelled"}
    pending = dict(admitted_at)
    counts: dict[str, int] = {}
    durations: list[float] = []
    deadline = time.monotonic() + timeout
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        while pending and time.monotonic() < deadline:
            for run_id in list(pending):
                response = client.get(f"/api/v1/runs/{run_id}")
                response.raise_for_status()
                status = response.json()["status"]
                if status in terminal:
                    counts[status] = counts.get(status, 0) + 1
                    durations.append((time.perf_counter() - pending.pop(run_id)) * 1000)
            if pending:
                time.sleep(0.25)
    if pending:
        counts["timed_out"] = len(pending)
    return counts, durations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--query", default="Explain retrieval augmented generation with inspectable citations.")
    parser.add_argument("--request-timeout", type=float, default=15.0)
    parser.add_argument("--terminal-timeout", type=float, default=120.0)
    parser.add_argument("--expect-backpressure", action="store_true")
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive")

    with httpx.Client(base_url=args.base_url, timeout=args.request_timeout) as client:
        ready = client.get("/health/ready")
        ready.raise_for_status()
        conversation = client.post("/api/v1/conversations", json={"title": "M5 load smoke"})
        conversation.raise_for_status()
        conversation_id = conversation.json()["id"]

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(submit_run, args.base_url, conversation_id, f"{args.query} [case {index + 1}]", args.request_timeout)
            for index in range(args.requests)
        ]
        submissions = [future.result() for future in futures]
    submission_wall_ms = (time.perf_counter() - started) * 1000

    admitted = [item.run_id for item in submissions if item.run_id]
    rejected = [item for item in submissions if item.status_code == 429]
    other_errors = [item for item in submissions if item.run_id is None and item.status_code != 429]
    create_latencies = [item.latency_ms for item in submissions]
    admitted_at = {
        item.run_id: item.admitted_at
        for item in submissions
        if item.run_id is not None and item.admitted_at is not None
    }
    terminal_counts, terminal_latencies = poll_terminal(
        args.base_url, admitted_at, args.terminal_timeout
    ) if admitted_at else ({}, [])

    print("ARES operator load smoke (not a benchmark)")
    print(f"submitted={len(submissions)} admitted={len(admitted)} backpressured={len(rejected)} other_errors={len(other_errors)}")
    print(
        "create_latency_ms "
        f"median={statistics.median(create_latencies):.1f} p95={percentile(create_latencies, 0.95):.1f} "
        f"wall={submission_wall_ms:.1f}"
    )
    if terminal_latencies:
        print(
            "terminal_latency_ms "
            f"median={statistics.median(terminal_latencies):.1f} p95={percentile(terminal_latencies, 0.95):.1f}"
        )
    print(f"terminal_statuses={terminal_counts}")
    if other_errors:
        print("unexpected_submission_errors=" + repr([(item.status_code, item.detail) for item in other_errors]))
        return 2
    if args.expect_backpressure and not rejected:
        print("expected at least one HTTP 429 capacity rejection but observed none")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
