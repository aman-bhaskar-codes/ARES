# Milestone 02 — Live web research + evidence RAG

## Delivered behavior

The live worker now executes:

`query -> bounded plan -> SearXNG -> safe fetch -> ranked evidence chunks -> immutable document version -> Gemini structured synthesis -> server-resolved claim citations`

The RAG layer is not an opening-page heuristic. It chunks extracted text, preserves exact offsets, computes lexical relevance, enforces source diversity, and exposes an embedding provider port for later hybrid semantic fusion.

## 1. Update local code

Use the Milestone 02 ZIP, or copy the changed files onto the Milestone 01 repository. Keep your existing `.env` secret values out of Git.

## 2. Refresh dependencies on your machine

Milestone 02 adds no Python or npm dependency, so the Milestone 01 lockfiles remain valid. Re-install from the committed locks to repair platform-specific native packages if the source tree moved between macOS/Linux/Windows:

```bash
uv sync --project backend --extra dev --frozen
pnpm install --frozen-lockfile
```

Do not copy `node_modules` or `backend/.venv` between operating systems.

## 3. Start local infrastructure

```bash
make infra
```

This starts PostgreSQL 18 and a loopback-only SearXNG container. The pinned cross-platform SearXNG tag is `2026.9.25-12f8b6515`. JSON output is explicitly enabled in `infra/local/searxng/settings.yml` because the SearXNG API returns 403 for formats not enabled in settings.

Verify:

```bash
docker compose -f infra/local/compose.yaml ps
curl 'http://127.0.0.1:8080/search?q=ARES&format=json'
```

The curl response must be JSON and contain a `results` array. If upstream engines temporarily block requests, SearXNG may return few/zero results; that is an external discovery limitation, not permission to fabricate results.

## 4. Configure strict-free live mode

Start from the provided profile:

```bash
cp .env.postgres.example .env
```

Set only your actual Gemini project values:

```env
ARES_MODE=local_live
STRICT_FREE_MODE=true
ALLOW_BILLABLE_PROVIDERS=false
DATABASE_URL=postgresql+psycopg://ares:ares@127.0.0.1:5432/ares
SEARXNG_URL=http://127.0.0.1:8080
GEMINI_API_KEY=YOUR_KEY
GEMINI_MODEL=gemini-3.8-flash
GEMINI_THINKING_LEVEL=low
GEMINI_RPM=YOUR_PROJECT_LIMIT
GEMINI_TPM=YOUR_PROJECT_LIMIT
GEMINI_RPD=YOUR_PROJECT_LIMIT
MAX_HTTP_CONCURRENCY=4
```

Use the quotas displayed for your own project. Do not guess large numbers. ARES reserves its configured allowance before Gemini calls and has no paid fallback.

Run:

```bash
python scripts/doctor.py
```

The doctor now reads `.env` automatically. It validates configuration but does not make external provider calls.

## 5. Apply the provenance migration

```bash
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend alembic -c backend/alembic.ini current
```

Required schema revision:

```text
0003 (head)
```

Migration 0003 adds source discovery metadata, immutable `document_versions`, and evidence offsets/version links.

## 6. Run all deterministic checks

```bash
PYTHONPATH=backend/src uv run --project backend pytest backend/tests -q -ra
PYTHONPATH=backend/src uv run --project backend python -m compileall -q backend/src backend/tests scripts
pnpm --filter @ares/web typecheck
pnpm --filter @ares/web test
pnpm --filter @ares/web build
```

In the implementation sandbox, backend result was **25 passed, 1 PostgreSQL-only test skipped**. On your PostgreSQL-enabled machine also run:

```bash
export ARES_TEST_POSTGRES_URL="$DATABASE_URL"
PYTHONPATH=backend/src uv run --project backend pytest backend/tests/integration/test_postgres_concurrency.py -q
```

Expected: `1 passed`.

## 7. Start all application processes

Terminal 1:

```bash
PYTHONPATH=backend/src uv run --project backend uvicorn ares.api.app:app --reload
```

Terminal 2:

```bash
PYTHONPATH=backend/src uv run --project backend python -m ares.worker.main
```

Terminal 3:

```bash
pnpm --filter @ares/web dev
```

Open `http://127.0.0.1:5173`. The header must say `Live · strict free`.

## 8. Run one explicit real-world smoke

With API + worker + SearXNG already running:

```bash
PYTHONPATH=backend/src uv run --project backend python scripts/live_smoke.py \
  'What is the latest stable Gemini Flash model and what are its documented capabilities?'
```

A successful run ends with something like:

```text
status=discovering
status=reading
status=extracting
status=synthesizing
status=completed
completed claims=N citations=N
```

Open the same run in the UI and inspect multiple citation buttons. Each citation must show a stored passage, source URL, document-version hash and exact source offsets.

## 9. Failure checks you should intentionally try

- stop a run while pages are being read: no new fetch should be admitted after cancellation;
- stop SearXNG: the run should fail as `SEARCH_UNAVAILABLE`, not invent sources;
- set Gemini RPM to `1`, run two requests close together: quota enforcement should reject excess work;
- remove the Gemini key: readiness/live worker should fail closed;
- ask a query with poor evidence: ARES should expose gaps or fail for insufficient evidence rather than synthesize unsupported claims.

## Known Milestone 02 boundaries

- web scope only;
- no browser-rendering fallback yet;
- no uploaded-document/academic/software RAG yet;
- semantic embeddings are an optional port, not enabled by default;
- SearXNG coverage depends on enabled/upstream engines;
- the implementation sandbox could not execute a real Gemini/SearXNG network smoke or frontend native build because of environment/network/platform constraints. The deterministic contracts are tested; your local live smoke is the release gate.
