# Milestone 05 release report

## Implemented

- versioned evaluation metrics/harness for routing, claim support, retrieval and indirect-injection observability, including Wilson uncertainty intervals and retrieval dispersion;
- explicit development-vs-held-out evaluation boundary;
- unsupported-claim retention and conflict-recall gates;
- configurable lexical/semantic/hybrid retrieval ablations;
- deterministic-vs-Jev decision-provider comparison path with no automatic metered fallback;
- Gemini synthesis instruction/data separation, `store=False`, structured output and no model tools;
- remote-content risk telemetry that never upgrades source trust;
- stronger SSRF validation and adversarial tests;
- request correlation IDs and bounded JSON operational logs;
- run-stage timing events plus optional OpenTelemetry API span bridge;
- canonical/content/normalized-URL alias deduplication before retrieval, including recovery wave handling;
- DB-serialized active-run admission/backpressure and retryable HTTP 429 contract;
- bounded worker retry exhaustion plus transient heartbeat retry and stale-lease fencing;
- document blob cleanup after failed persistence;
- per-run quality/diagnostic API and production React diagnostics panel, including citation coverage, support rate, queue wait and end-to-end timing;
- operator load-smoke harness;
- CI evaluation, lock, lint, secret-shaped-material, PostgreSQL/pgvector and frontend gates.

## Executed in this sandbox

- backend: 72 collected, 69 passed, 3 skipped because `ARES_TEST_POSTGRES_URL` is unavailable;
- offline development-regression gate: passed;
- Python compileall: passed;
- OpenAPI regeneration: passed;
- `git diff --check`: passed;
- deterministic secret-shaped-material script: passed across tracked plus untracked/non-ignored candidate source paths;
- frontend production-source TypeScript check: passed using the exact pinned React/TanStack/Lucide type packages recovered from the user-completed M1 dependency snapshot and the globally installed TypeScript compiler; test files remain part of the native pnpm/Vitest machine gate.

## Not claimed here

- the three PostgreSQL-only tests are not claimed as passes in this sandbox;
- Vite/Vitest native execution is not claimed here because the available dependency snapshot contains incompatible native packages and registry access is blocked;
- no live Gemini/Jev/provider evaluation is claimed;
- development-fixture metrics are not an external benchmark;
- no performance/capacity benchmark is claimed;
- no public deployment or multi-user authorization is claimed.
