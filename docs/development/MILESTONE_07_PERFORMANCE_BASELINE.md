# M07 Performance Baseline

**Date:** 4 October 2026  
**Scope:** deterministic/keyless demo path only; this is not a live-provider throughput claim.

## Reproduction

Run from the repository root after the backend environment is installed:

```bash
make perf-baseline
```

Equivalent direct command:

```bash
PYTHONPATH=backend/src python scripts/perf_baseline.py --runs 60
```

The harness creates an isolated temporary SQLite database, submits 60 sequential Quick-mode demo runs through the public API contract, executes each through the durable worker-once path, and replays the run event stream after completion.

## Environment

- Linux 6.18.44 x86_64, glibc 2.41
- Python 3.13.5
- Local container storage / temporary SQLite database
- 60 sequential Quick-mode deterministic demo runs
- No Gemini, SearXNG, PostgreSQL/pgvector, OIDC, browser, or remote network latency included

## Results

| Metric | Median | p95 | Max |
|---|---:|---:|---:|
| Run admission | 5.331 ms | 6.056 ms | 14.797 ms |
| Deterministic demo execution | 22.750 ms | 26.579 ms | 34.328 ms |
| Durable event replay | 5.808 ms | 6.824 ms | 8.372 ms |

These measurements establish a reproducible local regression reference only. They include TestClient/API overhead and therefore supersede the earlier ad-hoc in-process M07 numbers. M10's Quick-run latency target must compare identical live/fixture-backed scenarios against an appropriately matched M07 baseline rather than treating these SQLite demo numbers as production performance.
