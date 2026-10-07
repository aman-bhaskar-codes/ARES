# ARES — Autonomous Research & Evidence System

> Research you can trace back to evidence.

ARES is an evidence-first research application built as a React/Vite client, FastAPI API, durable Python worker, PostgreSQL/pgvector data layer, bounded research tool fabric, and Gemini synthesis layer. The full design baseline is retained at `docs/architecture/ARES_Master_Blueprint.html`.

## Current milestone

**Milestone 15 — Professional workspace, documents and V3 release proof** is implemented in source as ARES `0.15.0`. It advances the V2 release by introducing robust agentic workflows, deterministic reporting, and immutable artifact generation.

M15 completes the V3 product surface around the evidence contracts:

- **Immutable Reports:** Generated `ReportDocument` artifacts securely combining generated summaries, evaluated claims, and extracted evidence in Markdown, JSON, HTML, and optional PDF.
- **Workflow Executor:** Enforced, bounded research agents with DAG states, retry bounds, scope restrictions, and transparent UX via `AgentPlanPanel`.
- **Verified Free Tools:** Extensible adapter integrations including Wikimedia, Europe PMC, RSS feeds, deterministic table operations, alongside legacy SearXNG and arXiv sources.
- **Watchlists & Subscriptions:** Change-detection monitoring, assessing only deltas via background PostgreSQL scheduler.
- **E2E & Resilience Verification:** Integrated `verify_v3_release.py` gating contract tests, schema constraints, and browser E2E workflows.

## Research flow

```text
query
  │
  ├─ deterministic policy / optional Jev decision adapter
  │
  ├─ bounded concurrent discovery
  │    ├─ web ─────── SearXNG -> SafeFetcher -> optional isolated browser fallback
  │    ├─ academic ── OpenAlex / Crossref / arXiv -> optional safe OA PDF enrichment
  │    └─ software ── GitHub public repository/release/license/README evidence
  └─ local assets ─ PDF / image / CSV / audio / short video / legacy text
                    │
                    ├─ immutable extraction + page/cell/time/frame evidence
                    ├─ local ASR + bounded PTS frame sampling for configured media
                    ├─ lexical retrieval
                    └─ background local/versioned embeddings -> exact pgvector search
                                      │
                              reciprocal-rank fusion
                                      │
                               stored evidence spans
                                      │
                       facet coverage / deterministic + optional semantic checks
                                      │
                            Gemini structured synthesis
                                      │
                       server-resolved claim citations
                                      │
                     finalized run + evidence relations
                                      │
             validated comparison / chart / timeline / evidence map
```

The invariant is `answer claim -> evidence span -> immutable document/source version`. Retrieved content is untrusted data and never receives tool authority.

## Quickstart — keyless demo

Prerequisites: Python 3.12+ and `uv`; Node 22.16+ and pnpm for the web client.

```bash
cp .env.example .env
python scripts/doctor.py
uv sync --project backend --extra dev
uv run --project backend uvicorn ares.api.app:app --app-dir backend/src --reload
```

Second terminal:

```bash
PYTHONPATH=backend/src uv run --project backend python -m ares.worker.main
```

Web client:

```bash
corepack enable pnpm
pnpm install --frozen-lockfile
pnpm --filter @ares/web dev
```

The UI labels demo output **Recorded demo · keyless**. Demo mode does not claim live web/Gemini execution.

## Local live mode

Start local infrastructure:

```bash
make infra
```

The local PostgreSQL service uses the pgvector PostgreSQL 18 image. Copy the PostgreSQL example environment and configure the quotas shown by your own provider project:

```bash
cp .env.postgres.example .env
```

Required live policy remains:

```env
ARES_MODE=local_live
STRICT_FREE_MODE=true
ALLOW_BILLABLE_PROVIDERS=false
```

Then:

```bash
uv run --project backend alembic -c backend/alembic.ini upgrade head
```

`JEV_ENABLED` stays false under strict-free live mode because Jev is a metered provider. It can be enabled only in a separately authorized evaluation profile; deterministic routing remains available without it.

## Verification

Backend:

```bash
PYTHONPATH=backend/src pytest backend/tests -q
PYTHONPATH=backend/src python -m compileall -q backend/src backend/tests
PYTHONPATH=backend/src python scripts/export_openapi.py
```

With the local PostgreSQL/pgvector test database, run the complete release database gate:

```bash
export ARES_TEST_POSTGRES_URL="$DATABASE_URL"
make test-postgres
```

This covers provider-quota concurrency, active-run concurrency, exact pgvector ordering, production readiness/Trusted Host, direct RLS isolation and pooled-connection tenant reset.

Frontend:

```bash
pnpm install --frozen-lockfile
pnpm --filter @ares/web typecheck
pnpm --filter @ares/web test
pnpm --filter @ares/web build
```

Production/source release checks also include:

```bash
PYTHONPATH=backend/src python scripts/verify_migrations.py
python scripts/production_doctor.py --env-file .env.production
python scripts/check_secrets.py
make perf-baseline
python scripts/verify_v3_release.py
make sbom
# Builds the deterministic source archive under dist/ after source-level gates pass:
make release-v3
```

For the browser gate, verify E2E testing passes as integrated into `scripts/verify_v3_release.py`.

After populating `.env`, validate live service/API wiring with bounded read-only probes:

```bash
make connectivity-doctor
# Release/operator gate including optional research providers:
make connectivity-doctor-strict
```

Do not promote the RC to a public production release until the PostgreSQL/RLS gate, native frontend test/build, Docker image/Compose gate and live OIDC/provider smoke tests pass on the target environment.

## Repository map

- `apps/web/` — responsive React/Vite research workspace.
- `backend/src/ares/domain/` — typed run/evidence/document/budget models.
- `backend/src/ares/application/` — orchestration, persistent RAG, documents, exports and repository services.
- `backend/src/ares/adapters/` — Gemini, Jev, SearXNG, safe HTTP, OpenAlex, Crossref, arXiv, GitHub, PDF, blob and SQL adapters.
- `backend/src/ares/api/` — REST/SSE boundary and runtime status.
- `backend/src/ares/worker/` — durable lease worker with graceful admission stop/drain.
- `backend/migrations/` — additive Alembic history through M11; current head is `0012` (`0012_visual_artifacts`).
- `backend/tests/` — unit/integration/security/provider contracts.
- `evals/` — versioned routing/evaluation fixtures and reports.
- `docs/adr/` — architectural decisions.
- `infra/local/` — local PostgreSQL/pgvector + SearXNG infrastructure.
- `infra/production/` — hardened production Compose contract; `infra/postgres/` contains privilege-group provisioning.
- `docs/operations/` — production, backup/restore and rollout/rollback runbooks.

## Engineering stance

ARES is Perplexity-inspired in workflow, not a claim of proprietary parity or benchmark superiority. Exact source passages, known gaps and conflicts are preferred over polished unsupported prose. M11 adds validated visual projections over the same evidence store: a chart point, comparison cell, timeline item or graph edge cannot bypass evidence authorization or provenance. Source code is not equivalent to a proven public deployment: PostgreSQL/RLS, production containers, browser/network isolation, model provisioning, live providers, independent held-out evaluation and external testing still require target-environment verification before public promotion.

### Choosing an answer model

The composer’s **Answer model** selector chooses **Gemini · Cloud** or **Qwen · Local** for each query and follow-up. The run header shows the saved choice. Switching does not change an existing answer. The frontend remembers your next-query preference.

- Gemini requires `GEMINI_API_KEY`, `GEMINI_MODEL`, and explicit provider quota settings.
- Qwen requires `LOCAL_LLM_ENABLED=true`, a running Ollama service at `LOCAL_LLM_URL`, and the installed model named by `LOCAL_LLM_MODEL` (for example `qwen3:4b`).
- `GET /api/v1/models` lists configured models. `POST /api/v1/runs` accepts `model_provider: "gemini" | "qwen"`; omitted values use the deployment default (Qwen when local writing is enabled). Configuration availability does not guarantee remaining cloud quota or a healthy local service. Failures preserve retrieved evidence and identify the writing error; the server does not silently switch providers.
- Apply database migration `0020` before deploying this change. Older runs with no saved provider use the deployment default when resumed.

Answer depth is controlled by the writing adapters: explanatory questions target connected paragraphs covering definition, mechanism, a supported example, significance and caveats. Qwen uses up to 1,600 generated tokens and 1,100 characters per retrieved passage in a 6,144-token context. The entire visible answer is produced in the cited paragraphs, rather than an unused summary. Targets yield to evidence limitations and explicit brevity requests. This is prompt/context tuning, not weight training. Semantic-verification status is shown once above the answer; detailed heuristic checks remain in Diagnostics.
