# Milestone 05 — Evaluation, security and reliability hardening

Milestone 5 turns the M4 research application into a system whose important failure modes are measurable and regression-gated.

## 1. Development regression suite

Run the offline gate:

```bash
PYTHONPATH=backend/src python evals/run_suite.py \
  --suite all \
  --decision-provider deterministic \
  --retrieval-mode lexical \
  --report evals/reports/regression_latest.json
```

The checked-in cases are development fixtures, not an external benchmark. Read `docs/evaluation/METHODOLOGY.md` before publishing any results.

## 2. Security regression

Relevant controls now include:

- instruction/data separation for Gemini synthesis;
- stateless Gemini interaction storage configuration (`store=False`);
- no model-side tool authority;
- indirect-injection risk telemetry for instruction override, role override, prompt exfiltration, tool manipulation, suspicious delimiters, invisible Unicode and decoded instruction-like blobs;
- SSRF blocking for private/loopback/link-local addresses, mixed public/private DNS answers, userinfo, non-standard ports and control characters;
- DNS pinning and redirect revalidation remain from earlier milestones;
- narrow deterministic secret-shaped-material CI gate.

Run:

```bash
PYTHONPATH=backend/src pytest backend/tests/security -q
python scripts/check_secrets.py
```

## 3. Backpressure and worker recovery

`MAX_ACTIVE_RUNS` limits non-terminal runs. PostgreSQL serializes admission with an advisory transaction lock so multiple API processes cannot each admit beyond the same cap. Idempotent replay is checked before capacity rejection.

When full, the API returns:

```text
HTTP 429
Retry-After: 5
code = RUN_CAPACITY_REACHED
```

Durable jobs also have `MAX_JOB_ATTEMPTS`. Expired leases beyond the configured retry budget fail the run with `WORKER_RETRY_EXHAUSTED` instead of retrying forever.

The PostgreSQL concurrency test requires a real test database:

```bash
export ARES_TEST_POSTGRES_URL="$DATABASE_URL"
PYTHONPATH=backend/src pytest \
  backend/tests/integration/test_postgres_concurrency.py \
  backend/tests/integration/test_postgres_pgvector.py -q
```

## 4. Per-run diagnostics

For a terminal run:

```bash
curl http://127.0.0.1:8000/api/v1/runs/<RUN_ID>/quality
```

The React thread renders the same endpoint in **Run diagnostics**. These are factual signals, not a product score.

## 5. Operator load smoke

Run API + worker first, preferably in demo mode for a quota-free queue/backpressure check:

```bash
PYTHONPATH=backend/src python scripts/load_smoke.py \
  --requests 12 \
  --concurrency 12 \
  --expect-backpressure
```

It reports observed submission/terminal latency and HTTP 429 counts. It is intentionally named a smoke harness: do not publish its output as a capacity benchmark.

## 6. Jev comparison

Jev stays outside strict-free mode. In an explicitly authorized evaluation environment:

```bash
export JEV_API_KEY='...'
PYTHONPATH=backend/src python evals/run_suite.py \
  --suite routing --decision-provider jev --no-gate \
  --report evals/reports/jev-routing.json
```

Use the same fixtures and compare the full confusion/metric output rather than selected examples.

## 7. Hybrid retrieval ablation

Lexical is the offline gate. Semantic/hybrid ablations require an explicitly configured embedding provider:

```bash
export GEMINI_API_KEY='...'
PYTHONPATH=backend/src python evals/run_suite.py \
  --suite retrieval \
  --retrieval-mode hybrid \
  --embedding-provider gemini \
  --no-gate \
  --report evals/reports/hybrid-live.json
```

Do not add HNSW merely because hybrid search exists. M4 still intentionally uses exact pgvector cosine retrieval until measured scale/latency justifies approximate indexing.

## 8. Full machine gate

Once dependencies and PostgreSQL are available:

```bash
uv lock --project backend --check
uv sync --project backend --extra dev --frozen
uv run --project backend ruff check backend/src backend/tests evals scripts
PYTHONPATH=backend/src uv run --project backend pytest backend/tests -q
PYTHONPATH=backend/src uv run --project backend python evals/run_suite.py --suite all
PYTHONPATH=backend/src uv run --project backend python -m compileall -q backend/src backend/tests evals scripts
PYTHONPATH=backend/src uv run --project backend python scripts/export_openapi.py
git diff --exit-code -- backend/openapi.json
python scripts/check_secrets.py

corepack enable pnpm
pnpm install --frozen-lockfile
pnpm --filter @ares/web typecheck
pnpm --filter @ares/web test
pnpm --filter @ares/web build
```

Then perform the PostgreSQL-specific gate and a live provider smoke using only the quotas/providers you intentionally configured.
