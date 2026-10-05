# Milestone 07 Release Report — Verified Foundation and Responsive Execution

**Date:** 4 October 2026  
**Baseline:** supplied `ARES_M06_release_candidate.zip` / schema `0006`  
**Candidate:** ARES `0.7.0` / schema `0007`

## Scope and integration result

M07 extends the existing M06 application rather than creating a parallel scheduler, evidence store, frontend, broker, auth layer, or vector database. Existing M06 saved runs/readers remain compatible.

Implemented and integrated:

- checked-answer finalization: visible/copy/export answer content comes from accepted claim-linked blocks rather than unchecked model summary prose;
- deterministic numeric/date/unit/negation screening, including the required `10 percent` vs `90 percent` regression;
- persisted assessment method/version/state/rationale while retaining explicit legacy labels;
- persisted run deadline, budget version, usage ledger, date window and durable event cursor;
- end-to-end date-window propagation through API admission, frontend client contract, planner, provider requests/filters and final source selection; unknown source dates remain unknown rather than being replaced by fetch time;
- worker-time workspace/document reauthorization despite the intentionally privileged worker DB role;
- bounded provider/source/Gemini timeouts tied to remaining run time, including transport-level timeout propagation;
- PostgreSQL fleet resource leases plus process-local bounds, durable fenced checkpoints and provider-usage reconciliation;
- partial evidence reports on useful timeout/quota/budget exhaustion instead of discarding all progress;
- schema-v2 SSE events, bounded replay, durable `last_seq`, snapshot-required recovery, ~15-second comment heartbeats, adaptive polling and periodic authorization revalidation;
- runtime frontend validation for auth/run/event payloads, bounded/deduplicated event history, future-schema rejection and additive-event compatibility;
- tenant-boundary frontend cache clearing on workspace switch and session clearing on logout;
- generated API contract/type workflow aligned between package scripts and CI;
- exact stored-text content hashes after bounded fetch truncation;
- explicit connectivity doctor for DB/schema, SearXNG, Gemini key/model, OIDC discovery, OpenAlex, Crossref, arXiv, GitHub and Jev policy without exposing credentials;
- telemetry capability reporting distinguishes configured, ready and degraded states;
- reproducible deterministic M07 performance harness and report.

## Dependency/release reproducibility

The stale M06 backend lock blocker is closed. `backend/pyproject.toml` and the editable package entry in `backend/uv.lock` now agree on ARES `0.7.0`, including the required `cryptography` dependency. Optional OTLP export remains failure-isolated rather than a mandatory core install; system status and the connectivity doctor report a configured-but-unavailable exporter as degraded.

The pnpm lock is one valid YAML document and its `apps/web` dependency/devDependency specifiers match `apps/web/package.json`.

## Migration

`0007_execution_contracts` is additive. It adds run deadline/date-window/budget/event-sequence fields, claim assessment metadata, provider usage reconciliation fields, durable run checkpoints and fleet resource leases. New runtime coordination tables receive PostgreSQL RLS immediately. Worker grants are explicit and future tables receive no automatic grants.

Executed locally:

- clean SQLite database -> `0007`: **PASS**
- representative `0006` database -> `0007`: **PASS**

## Executed verification evidence

| Gate | Result |
|---|---|
| Backend collection | **122 tests collected** |
| Backend tests available in this sandbox | **PASS — 116 passed** |
| PostgreSQL-only tests | **6 NOT RUN/SKIPPED — no PostgreSQL service** |
| Numeric mismatch + rejected-summary regressions | **PASS** |
| Deadline/cancellation/quota/checkpoint/resource-lease regressions | **PASS** |
| Workspace-switch/logout session regression | **PASS** |
| API date-window round trip + planner/provider propagation | **PASS** |
| Provider transport-timeout regressions | **PASS** |
| Stored-text hash regression | **PASS** |
| Python compileall | **PASS** |
| Deterministic secret scan | **PASS — 211 source candidates** |
| Deterministic routing/claim/retrieval/security evaluation | **PASS** |
| OpenAPI export + generated frontend schema | **PASS; repeat generation stable** |
| Migration verifier | **PASS** |
| Backend lock consistency | **PASS — `uv lock --project backend --check --offline`** |
| pnpm lock structural/importer consistency | **PASS** |
| Frontend core API/runtime boundary TypeScript check | **PASS** |
| `.env.example` static connectivity/settings check | **PASS** |
| Reproducible 60-run demo performance harness | **PASS** |
| Frozen backend reinstall | **NOT RUN** — package artifacts not cached and registry DNS unavailable |
| Ruff from pinned environment | **NOT RUN** — package not installed and registry access unavailable |
| Full pnpm install/Vitest/Vite build | **NOT RUN** — pnpm/packages unavailable and registry DNS unavailable |
| PostgreSQL/pgvector/FORCE-RLS/role suite | **NOT RUN** — no PostgreSQL/Docker runtime in this sandbox |
| Production image/Compose runtime | **NOT RUN** — no Docker/Podman daemon |
| Live OIDC + provider smoke | **NOT RUN** — operator credentials/services were not supplied and outbound runtime DNS is unavailable |
| Remote GitHub Actions/PR | **NOT RUN** — the connected GitHub app has no repository installation exposed to this session |

An unexecuted environment-dependent gate is deliberately not counted as a PASS. CI is configured to execute the PostgreSQL/RLS, fresh backend/frontend install, Vitest/Vite, production image and Compose gates on a capable runner. `make connectivity-doctor-strict` provides the operator-side all-provider read-only connectivity gate after `.env` is populated.

## Performance baseline

See `MILESTONE_07_PERFORMANCE_BASELINE.md`. On this container, the reproducible 60-run deterministic demo harness measured:

- run admission p95: **6.056 ms**;
- deterministic demo execution p95: **26.579 ms**;
- durable event replay p95: **6.824 ms**.

These are local regression measurements, not production throughput or live-provider latency claims.

## Security and correctness notes

- API/worker privilege separation from M06 is preserved; worker execution reauthorizes current membership/document ownership before work.
- New `run_steps` and `resource_leases` tables are tenant-owned and RLS-protected in PostgreSQL migrations; worker grants are explicit.
- No API key/token is logged or embedded in generated artifacts. Connectivity checks print only state/errors, not secrets.
- Retrieved content remains untrusted data; no model output gains command/network authority.
- Workspace switch clears client query cache before adopting the new principal, preventing previous-tenant cached resources from resurfacing.
- Provider request deadlines now reach the underlying HTTP/Gemini transport where supported, not only the orchestration future.

## Rollback

M07 storage changes are additive around M06 readers. Old saved answers remain readable. Optional M07 execution/stream paths can be application-reverted while retaining `0007`; correctness and authorization fixes should not be rolled back. Pause queue admission if shared quota/resource-lease coordination is unavailable. Do not destructively downgrade production data outside the documented schema compatibility range.

## Promotion status

**M07 engineering implementation is complete in this archive.** The source candidate is ready for the repository/target-environment promotion gates. A public/production release must still run the explicitly listed PostgreSQL/RLS, fresh frontend/backend install, container, live OIDC/provider and remote CI gates in an environment that actually provides those services and credentials.
