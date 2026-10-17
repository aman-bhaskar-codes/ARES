# ARES — Repository Review & Fix Prompt

Repo: `aman-bhaskar-codes/ARES` · branch `v3-development` (only branch) · HEAD `476d69b`
Reviewed: 2026-10-14 · ~41k lines Python/TS · FastAPI + SQLAlchemy/Alembic + Postgres/pgvector + React 19/Vite

## 0. How this was reviewed

**Actually run** (clean clone):
- `ruff check` → passes
- backend `pytest` → **221 passed, 6 skipped** (Postgres/RLS/concurrency tests need a live Postgres; they only run in CI)
- frontend `tsc`, `vitest` (21 tests), `vite build` → pass
- Booted `create_app()` under different env settings and probed it with a test client

**Read:** README, Dockerfile, both compose files, CI, settings, `app.py`, routers, SSRF guard, Ollama adapter, synthesis stage, migrations, evals, env templates, committed zip.

**Not done:** I did not read every line of the 41k. `engine.py`, `persistence/*`, `media_ingestion.py` and `auth.py` were skimmed or not opened. Items below are tagged **[verified]** (reproduced or directly seen) or **[by reading]** (inferred from code, not executed).

**Overall verdict:** The core is better engineered than most student repos. It has an SSRF guard with DNS pinning, row-level security, CSRF, idempotency keys, quotas, a durable event stream and 20+ migrations. The problems are mostly **deployment-config traps, an unfinished refactor, repo hygiene, and docs that describe a different project**. Those matter a lot if this is positioned as a research/IIT-visible portfolio piece.

---

## 1. P0 — Fix before any real deployment

### P0-1. Production can boot with authentication disabled [verified]
- `api/app.py:75` only calls `cfg.validate_security_mode()` when `auth_mode == 'oidc'`. All the production guards live inside that method (`settings.py:285+`: "production requires AUTH_MODE=oidc", Postgres, secure cookies, HTTPS).
- I booted the app with `DEPLOYMENT_ENVIRONMENT=production AUTH_MODE=disabled`. It started with no error, and `/api/v1/system/status` returned **200 unauthenticated**. Every API route runs as `local_principal()`.
- `/docs` and `/openapi.json` are also publicly served (200).
- Only the worker (`worker/main.py:238`) validates unconditionally.
- **Fix:** call `validate_security_mode()` unconditionally at startup (or add a pydantic `model_validator` on `Settings`). Disable `docs_url`/`redoc_url`/`openapi_url` in production. Add a test that production + `AUTH_MODE=disabled` raises.

### P0-2. Production readiness check is pinned to a stale schema revision [by reading]
- Alembic head is **0021**. `REQUIRED_SCHEMA_REVISION` defaults to `"0013"` (`settings.py:179`) and both env templates set `0013`.
- `scripts/production_doctor.py:43` actively **fails** if it is anything other than `0013`.
- In production, `/health/ready` compares `alembic_version` to that value (`routers/system.py:42`) and returns 503 on mismatch.
- The production compose healthcheck hits `/health/ready`. After `alembic upgrade head`, the API would be permanently unhealthy. If you set it to 0021 to fix that, `production_doctor` rejects it.
- **Fix:** derive the required revision from Alembic's script directory head (`ScriptDirectory.from_config(...).get_current_head()`) instead of a hand-maintained constant. Remove the hard-coded check in `production_doctor`. Add a CI test asserting `settings default == alembic head`.

### P0-3. Production compose ships a "development-only" SearXNG secret [verified]
- `infra/production/compose.yaml` mounts `../local/searxng/settings.yml`, which contains `secret_key: "ares-local-development-only-change-before-public-use"` and `limiter: false`.
- **Fix:** separate production settings file. Inject the secret via env or a Docker secret. Enable the limiter, or keep SearXNG strictly on the internal network.

---

## 2. P1 — Major correctness / architecture / process issues

### P1-1. Half-finished router refactor [verified]
- 15 endpoints are still inline in `app.py` (auth login/callback, `/api/v2/assets` POST/DELETE/content, ingestion events, renditions, document text/pdf/delete, exports, artifact download, run events). 33 more live in `routers/`.
- `/api/v1/artifacts/{id}` is defined in both places. FastAPI emits `Duplicate Operation ID download_artifact_...` and `openapi.json` is ambiguous.
- `app.py` has two near-identical copies of the SSE `revalidate()` closure.
- Imports sit above `from __future__ import annotations`, behind a block of blank lines.
- Router functions contain machine-generated no-op lines (`getattr(request.app.state, 'auth_store', None)` with the result discarded) — output of the AST-rewrite scripts. Routers use `from ares.api.dependencies import *` with file-level `# ruff: noqa: F403, F405, E501`. This hides undefined names and defeats lint.
- **Fix:** finish the move, with one owner per route. Use FastAPI `Depends(get_repository)` etc. (they already exist in `dependencies.py` but are unused). Remove star-imports and the noqa. Delete the no-op lines. Add a test failing on duplicate `(method, path)` or operation IDs.

### P1-2. Repo hygiene — stray artifacts committed [verified]
- `backend/scratch_add_requests.py` and `backend/scratch_update_app.py` are the AST-rewrite scripts. The merged PR text claims "Removed leftover debugging and scratch scripts".
- `fix_yaml.py` edits a `dependency-review.yml` that no longer exists, so it would crash if run.
- `pr_body.txt` is a PR description checked in.
- `backend/ARES_M12_release_candidate.zip` (1.6 MB, 667 files) is a stale release archive. It nests an entire `.kilo/worktrees/bustling-spoon/` copy of the repo (including old SECURITY.md/docs). It is a build artifact and a second, drifting copy of the source.
- `evals/reports/live-e2e-2026-10-07/` holds committed screenshots and JSON, despite `.gitignore`/README saying reports are untracked.
- A root `uv.lock` stub (52 bytes) sits next to the real `backend/uv.lock`.
- **Fix:** delete all of the above. Add `*.zip`, `scratch_*`, `.kilo/` to `.gitignore`. Publish release archives as GitHub Releases, not in git.

### P1-3. CI/supply-chain regression [verified]
- `fix_yaml.py` shows SHA-pinned actions were deliberately replaced with floating tags. `ci.yml` now uses `actions/checkout@v4`, `setup-python@v5` and `astral-sh/setup-uv@v3`.
- `dependency-review.yml` was deleted; only Dependabot remains.
- `push:` CI only triggers on `v3-development`. There is no `main`, so merging or renaming the default branch leaves pushes un-CI'd (PRs are still covered).
- `ruff` selects only `E4,E7,E9,F`: no bugbear, security (`S`), bandit-style or import-order rules.
- `mypy --strict` covers only `domain/` and `ports/`; `application/`, `adapters/` and `api/` (the large majority of ~17k backend lines) are untyped in CI.
- Dockerfile pins `pnpm@12.8.1`, while root `package.json` says `pnpm@9.12.3` and CI uses `corepack enable`. [by reading] These can disagree and may fail or silently use different pnpm versions.
- **Fix:** re-pin actions to commit SHAs (Dependabot keeps them fresh). Restore dependency review. Add `S`, `B`, `UP`, `I` ruff rules. Widen mypy incrementally (`application`, then `api`). Single pnpm version source.

### P1-4. README describes a different project [verified]
- Claims **Next.js 14 / App Router / Tailwind / Framer Motion** — the app is **Vite + React 19**, with no Tailwind or Framer dependency.
- Claims **Qdrant** vector DB — there is zero Qdrant code. Retrieval is Postgres/pgvector (exact) plus `tsvector`, or SQLite brute-force.
- Claims **OpenAI / Anthropic** plug-and-play — no such adapters exist. Only Gemini and Ollama.
- Says UI is on **:3000** — Vite serves on **5173**.
- Clone URL is `your-username/ARES`. Banner points to `amanbhaskar/ARES/main/ares_banner.jpg`: wrong user, no `main` branch, file not in repo → broken image.
- Quick start omits SearXNG (needed for live research), Postgres and Alembic. Ollama example says `qwen2.5:3b`, while `.env.example` says `qwen3:4b`.
- "Autonomous multi-agent … spawns concurrent AI workers" overstates a pipeline of `discovery → retrieval → synthesis` stages with a thread pool.
- The ADRs, SECURITY.md, CHANGELOG, CONTRIBUTING and `docs/evaluation/METHODOLOGY.md` were deleted, but `evals/reports/README.md` still points to METHODOLOGY. There is no security-reporting policy.
- **Fix:** rewrite the README to match the real stack and architecture. Include an architecture diagram, a real quick start (compose → migrate → run), and an honest "Limitations" section. Restore SECURITY.md and a short ARCHITECTURE.md/ADR set.

### P1-5. Model-provider layer is hard-coded and hacky [by reading]
- `/api/v1/models` and `create_run` hard-code the strings `"gemini"` / `"qwen"` and their availability logic. There is no provider registry.
- `OllamaLLMProvider` subclasses `GeminiLLMProvider` and passes `client=SimpleNamespace()` to dodge the parent's SDK client. This is brittle inheritance for reuse of prompt and parse code.
- Ollama call details: `num_ctx=6144` with evidence truncated to 1100 chars per passage, `minLength=240` forced on claims for "explain/detail" queries, and `response.json()` parsed three times. `httpx.Client()` is created with no limits and never closed. A 4B model under a strict JSON schema with forced `minLength` is a likely source of failed or empty syntheses.
- Gemini defaults differ between examples (`gemini-3.5-flash-lite` in `.env.example`, `gemini-3.8-flash` in the production template).
- **Fix:** a `ModelProvider` protocol and registry (id, capabilities, availability, config). Extract the shared prompt/parse into a base class instead of subclassing Gemini. Make context budget and truncation configurable. Close clients on shutdown. Fall back to a retry with relaxed schema.

---

## 3. P2 — Quality, robustness, evaluation

### P2-1. Evaluation is too thin to support the project's own claims [verified]
- `evals/datasets`: 12 claim cases, 10 retrieval, 30 routing, 16 security. CI only runs the **deterministic** decision provider with **lexical** retrieval, as a regression check.
- The "held-out" dataset folder has only a README and an example manifest.
- `live-e2e-2026-10-07` results are single-query anecdotes. One report is `status: "partial"` because of a Gemini daily quota; the "citation resolution passed" flag is a self-check, not a measured faithfulness score.
- For a project whose stated research focus is evaluation, add: a larger labeled set, citation-faithfulness / claim-support metrics (e.g. NLI or LLM-judge with calibration), retrieval recall@k/nDCG on a public benchmark, and run-to-run variance across seeds and providers.

### P2-2. Memory-heavy request paths [by reading]
- `GET /api/v2/assets/{id}/content` without a Range header reads the **entire blob into memory** (videos can be up to 100 MB). `POST /api/v1/documents/pdf` accumulates the whole upload in a list before parsing.
- Stream with `FileResponse`/`StreamingResponse`, and spool uploads to disk as `create_asset` already does.

### P2-3. Large "god" modules and broad exception handling [verified]
- `engine.py` 1164 lines, `persistence/views.py` 1125, `persistence/base.py` 985, `db.py` 964, `asset_ingestion.py` 809, `media_ingestion.py` 821, `persistence/retrieval.py` 803.
- 41 bare/broad `except Exception` handlers. Some are legitimate boundaries, but each should log with context or narrow its type.
- `adapters/persistence/refactor_views.py` is a file named after a process, not a purpose.

### P2-4. Frontend [verified/by reading]
- Production build ships source maps (`build.sourcemap: true`) and they are served by the SPA static mount, so source is public. Main chunk is 568 kB, and the chart chunk 547 kB.
- Only 5 test files / 21 tests; no component tests for the SSE hook `useRunStream` (the most failure-prone UI piece: reconnect, `Last-Event-ID`, auth expiry).
- Set `sourcemap: 'hidden'` for prod and upload maps to your error tracker. Split the chart/graph chunks. Add tests for stream reconnect and CSRF-expiry handling.

### P2-5. Smaller items
- `_GITHUB_RE` in `synthesis.py` (`(?:github\.com/)?([A-Z0-9_.-]+/[A-Z0-9_.-]+)`) matches prose like `and/or`, `TCP/IP`, `client/server` as GitHub repo identifiers. This distorts exact-identifier ranking. Require the `github.com/` prefix or a strict `owner/repo` token boundary.
- FastAPI app version string is `'0.11.0'` while packages say `0.12.0`.
- `Content-Disposition` headers are built by string formatting with only `"` stripped (`app.py`, assets and artifacts). **Unverified:** non-Latin-1 filenames (e.g. Devanagari) may raise on header encoding at download time. Use RFC 5987 `filename*=UTF-8''…` and test it.
- `.env.example` has `REQUIRED_SCHEMA_REVISION=0013` (see P0-2) and a long, undifferentiated list of ~100 variables. Group by profile (demo / local_live / production).

---

## 4. Suggested order of work

1. P0-1, P0-2, P0-3 (an afternoon; add tests with each).
2. P1-2 hygiene and P1-1 router refactor (mechanical; unlock lint and typing).
3. P1-3 CI hardening, then P1-4 README/docs rewrite.
4. P1-5 provider registry, P2-2 streaming.
5. P2-1 evaluation work (largest payoff for your research positioning).

---

# 5. Paste-ready fix prompt (for Claude Code / any coding agent)

```
ROLE
You are a senior Python/TypeScript engineer hardening the ARES repo
(FastAPI + SQLAlchemy/Alembic + Postgres/pgvector backend in backend/, React 19 + Vite
frontend in apps/web/). Work on a new branch `fix/hardening-pass-1`. Make small,
reviewable commits, one per numbered task. After EVERY task run:
  uv run --project backend ruff check backend/src backend/tests evals scripts
  uv run --project backend pytest backend/tests -q
  pnpm --filter @ares/web typecheck && pnpm --filter @ares/web test
Do not proceed to the next task while any of these fail. Add or update tests for every
behavior change. Do not change public API paths or response schemas unless stated.

CONTEXT
Baseline: ruff clean, 221 backend tests pass (6 skipped need Postgres), frontend green.
Alembic head is 0021. The findings below were verified by a prior review.

TASKS (in order)

1. [P0] Unconditional security validation
   - backend/src/ares/api/app.py calls cfg.validate_security_mode() only when
     auth_mode == 'oidc'. Make validation run for every startup (keep OIDC-specific checks
     conditional inside the method).
   - In production (deployment_environment == 'production') set docs_url, redoc_url and
     openapi_url to None.
   - Tests: production + AUTH_MODE=disabled raises at create_app(); production /docs and
     /openapi.json return 404; local/demo behavior unchanged.

2. [P0] Derive required schema revision from Alembic head
   - Remove the hard-coded "0013" in settings.py (required_schema_revision),
     .env.example, .env.production.example and scripts/production_doctor.py.
   - Compute head via alembic ScriptDirectory (backend/alembic.ini) and have
     /health/ready (routers/system.py) and the doctors compare against it.
     Keep an optional env override.
   - Test: readiness is OK when DB revision == head and 503 otherwise; a test asserting no
     hard-coded revision remains.

3. [P0] Separate production SearXNG config
   - Create infra/production/searxng/settings.yml with limiter enabled and
     secret_key read from env/secret (no committed secret). Point
     infra/production/compose.yaml at it. Keep the local file clearly dev-only.
   - Extend scripts/check_secrets.py to fail on the string "development-only" in any file
     referenced by production compose.

4. [P1] Finish the router refactor
   - Move every remaining @app.<method> endpoint from api/app.py into the matching module in
     api/routers/ (auth, assets, ingestions, documents, runs, artifacts). One owner per
     (method, path); delete the inline copies. Deduplicate the SSE revalidate() closure into
     a shared helper.
   - Replace `from ares.api.dependencies import *` and `request.app.state.*` boilerplate
     with explicit FastAPI Depends(...) using the existing get_* helpers. Remove the
     discarded `getattr(request.app.state, ...)` no-op lines and every file-level
     `# ruff: noqa`. Fix whatever lint then surfaces.
   - Move imports below `from __future__ import annotations`; app.py should be a thin
     factory (< 150 lines).
   - Add a test that fails on duplicate (method, path) or duplicate operation_id.
   - Regenerate backend/openapi.json and apps/web/src/lib/api/generated.ts; they must have
     no diff other than the removal of duplicate operations.

5. [P1] Repo hygiene
   - git rm: backend/scratch_add_requests.py, backend/scratch_update_app.py, fix_yaml.py,
     pr_body.txt, backend/ARES_M12_release_candidate.zip(+.sha256), root uv.lock stub,
     evals/reports/live-e2e-2026-10-07/ (keep a one-paragraph summary in evals/reports/README.md).
   - .gitignore: add *.zip, scratch_*, .kilo/, evals/reports/**.
   - Rename adapters/persistence/refactor_views.py to a purpose-based name and fix imports.

6. [P1] CI hardening
   - Pin every action in .github/workflows/*.yml to a full commit SHA with a
     `# vX.Y.Z` comment. Upgrade astral-sh/setup-uv to the current major.
   - Restore .github/workflows/dependency-review.yml (pinned).
   - CI push trigger: [main, v3-development]; add `workflow_dispatch`.
   - ruff select: add B, S, UP, I (fix or targeted-ignore with justification). mypy: extend
     to ares.application first, then ares.api; track remaining modules in
     pyproject [[tool.mypy.overrides]] with ignore_errors = true, to be shrunk over time.
   - Make ONE pnpm version source of truth (package.json "packageManager") and have the
     Dockerfile use it.

7. [P1] Rewrite README + restore docs
   - README must match reality: Vite + React 19 (port 5173), FastAPI, Postgres/pgvector
     (+ SQLite demo mode), SearXNG for live search, Gemini and Ollama providers only.
     Remove Next.js/Tailwind/Framer/Qdrant/OpenAI/Anthropic claims. Fix clone URL to
     aman-bhaskar-codes/ARES, remove or add the banner, fix Ollama model name to match
     .env.example.
   - Quick start: docker compose -f infra/local/compose.yaml up -d; alembic upgrade head;
     run API, worker, web. Add an architecture diagram (Mermaid) and a Limitations section.
   - Add SECURITY.md (reporting policy), docs/ARCHITECTURE.md and
     docs/evaluation/METHODOLOGY.md (referenced by evals/reports/README.md).

8. [P1] Provider registry
   - Introduce a ModelProvider protocol + registry (id, label, location, is_available(cfg),
     factory). Drive /api/v1/models and create_run's provider validation from it; no
     hard-coded "gemini"/"qwen" strings in routers.
   - Stop subclassing GeminiLLMProvider with SimpleNamespace: extract shared
     prompt-build/parse into a base class. In the Ollama adapter parse response.json() once,
     make num_ctx and passage truncation configurable settings, close the httpx client on
     shutdown, and retry once with a relaxed schema when parsing fails.
   - Align default Gemini model across .env.example / .env.production.example / settings.

9. [P2] Streaming and robustness
   - GET /api/v2/assets/{id}/content (no Range) and artifact/rendition downloads: stream
     from the blob store instead of reading whole files. POST /api/v1/documents/pdf: spool
     to a temp file like create_asset does.
   - Build Content-Disposition with RFC 5987 (filename* UTF-8) via a single helper; add a
     test with a Devanagari filename.
   - Fix _GITHUB_RE in application/research_stages/synthesis.py to avoid matching "and/or",
     "TCP/IP" etc.; add tests. Align FastAPI app version with package version (single
     source).
   - Audit `except Exception` handlers: narrow or add contextual logging; list any you
     intentionally keep.

10. [P2] Frontend
   - vite build.sourcemap = 'hidden' for production. Lazy-load EvidenceChart/EvidenceGraph
     to bring the entry chunk under 500 kB.
   - Add vitest tests for useRunStream: reconnect with Last-Event-ID, 401/expired-session
     handling, and CSRF header propagation.

11. [P2] Evaluation
   - Expand evals/datasets (target: >= 100 claim-support cases, >= 50 retrieval queries with
     graded relevance, a populated held-out split with a manifest). Add claim-support /
     citation-faithfulness scoring and retrieval recall@k / nDCG to evals/run_suite.py and
     report mean +/- std over repeated runs. Wire the offline regression into CI with a
     threshold gate.

DEFINITION OF DONE
- All commands in the preamble pass; Postgres-gated tests pass in CI.
- No `# ruff: noqa` blanket suppressions remain in api/.
- `git ls-files` contains no zip/scratch/pr_body artifacts.
- A final summary lists each task, commit SHA, tests added, and anything deferred and why.
```
