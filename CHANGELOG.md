# Changelog

## Milestone 11 — Visual research workspace and V2 release proof
- Added stable run/evidence deep links, safe Markdown/GFM rendering, comparison/activity/source workspace views and semantic light/dark/reduced-motion UI behavior without migrating frameworks.
- Added schema `0012` visualization datasets/artifacts and a restricted lineage-bearing visualization contract backed by the existing claim/evidence store.
- Added deterministic worker-side visualization generation, read-only visualization retrieval, storage-aware readiness and durable visualization activity events.
- Added evidence-linked numeric charts, comparison data, honest source-publication timeline and a bounded claim/evidence relationship map with accessible evidence/table fallbacks.
- Added numeric-unit validation and spreadsheet-safe CSV export; no executable chart/HTML/SQL/Python specification is accepted.
- Added M11 backend/SPA/frontend regression coverage and networked TypeScript/Vitest/Vite verification; independent held-out evaluation and target-environment release gates remain explicit.

## Milestone 10 — Faster, stronger live research
- Added bounded concurrent web/academic/software discovery under the existing deadline, quota and fleet-resource contracts.
- Added workspace-scoped versioned search/source caching, request coalescing, bounded expiry maintenance and explicit provider-backoff/degraded-track events.
- Added exact scholarly/software identifier preference, conservative source-origin grouping and persisted facet coverage so copied sources do not inflate independent support.
- Added bounded open-access academic PDF enrichment through Safe HTTP + the existing page-aware M08 PDF parser while preserving honest abstract-only fallback.
- Added optional structured Gemini semantic assessment after deterministic checks, with server-validated evidence references, usage accounting, hard worker timeout and conservative outage behavior.
- Added per-edge supports/contradicts/contextualizes rationale/checker provenance and exposed those relations/facets through the existing run-quality UI.
- Added a separate authenticated Playwright browser fallback sidecar plus fail-closed production overlay/vendor tooling; browser fallback remains disabled until the documented egress-isolation gate is satisfied.
- Added migration `0011`, M10 regression/security/performance tooling, refreshed OpenAPI/frontend contracts and a measured same-fixture concurrent-discovery gate.

## Milestone 9 — Audio and short-video evidence
- Added timestamped local ASR and bounded video frame sampling behind the existing M08 asset/ingestion contracts.
- Added time-range/frame-region evidence, media tracks/frames, storyboard/playback navigation and capability-aware media admission.
- Kept media preprocessing isolated from API request handlers and retained text research when optional media capabilities are unavailable.

## Milestone 8 — Documents, images, tables and local indexing
- Added durable asset/extraction/segment/table/rendition/ingestion contracts with additive migrations `0008` and `0009`.
- Added asynchronous `202` asset admission, durable ingestion status/events/cancel/retry and authenticated byte-range asset serving while preserving V1 document endpoints.
- Added bounded CSV table extraction with raw/normalized cells and typed cell provenance; retained pypdf fast-path compatibility for text PDFs.
- Added isolated optional Docling/RapidOCR media parsing and local FastEmbed indexing profiles, provisioned separately from the core API/research dependency graph.
- Moved corpus embedding creation out of interactive research and added bounded PostgreSQL GIN lexical candidates before RRF fusion.
- Extended the existing workspace with drag/drop ingestion readiness, cancellation/retry, PDF/image region inspection and table-cell evidence.
- Added M08 isolation/idempotency/partial-indexing tests, regenerated OpenAPI contracts and kept text research operational when optional media/semantic processing is unavailable.

## Milestone 7 — Verified foundation and responsive execution
- Closed answer/evidence consistency gaps so rejected claims cannot survive in visible/exported summary content.
- Added deterministic numeric/date/unit checks and persisted assessment method/version/state metadata.
- Added migration `0007` with persisted deadlines/date windows/budget ledger/event cursor, durable checkpoints and fleet resource leases.
- Added worker-time authorization, bounded provider transport deadlines, partial-result recovery and provider usage reconciliation.
- Hardened SSE replay/authorization and frontend runtime validation, bounded history, workspace-switch cache isolation and generated API contracts.
- Propagated explicit date windows through planner/provider/source-selection paths and aligned stored source hashes with persisted bounded text.
- Added service/API connectivity diagnostics, lockfile reproducibility checks and a repeatable M07 performance baseline.

## Milestone 6 — Multi-user release-candidate boundary
- Added OIDC Authorization Code + PKCE S256, one-time state/nonce, JWKS ID-token validation, opaque server-side sessions, CSRF and logout/revocation.
- Added workspace roles/ownership and PostgreSQL FORCE RLS across research-bearing resources, plus pooled-connection tenant-context reset.
- Added per-user/per-workspace/global admission controls and a narrow SECURITY DEFINER global-capacity aggregate.
- Added worker fleet presence/draining health and production readiness checks for schema/worker availability.
- Added production security headers, Trusted Host validation, request-size limits and same-origin production validation.
- Added distinct API/worker DB privilege groups, hardened split-network production Compose, non-root/read-only containers and graceful stop budgets.
- Added migration compatibility, production-doctor, backup/restore, rollout/rollback and deterministic release-archive tooling.
- Added dependency-update/issue/PR repository hygiene and CI production-container/release gates.

## Milestone 5 — Evaluation, security and reliability hardening
- Added versioned routing, claim-support, retrieval and indirect-injection regression suites with explicit development/held-out boundaries.
- Added uncertainty context (Wilson intervals) and retrieval dispersion without turning development fixtures into benchmark claims.
- Hardened Gemini synthesis with privileged system instructions, untrusted JSON data envelopes, stateless interactions and no model-side tools.
- Added remote-content risk telemetry, stronger SSRF regression coverage and canonical/content/URL mirror deduplication.
- Added PostgreSQL-serialized active-run admission, HTTP 429 backpressure, retry exhaustion and resilient lease heartbeats with stale fencing.
- Added request correlation IDs, bounded JSON logs, stage timings, optional OpenTelemetry spans and per-run diagnostics.
- Added operator load-smoke tooling, secret-shaped-material scanning and stronger CI evaluation/release gates.

## Milestone 4 — Full-stack research workspace and page-aware persistent RAG
- Added bounded PDF ingestion with page maps, OCR-needed detection and content-addressed raw-file storage.
- Separated reusable document IDs from run-scoped source IDs, fixing cross-run provenance collisions.
- Added persisted document chunks and model/dimension-versioned embeddings.
- Added exact PostgreSQL pgvector cosine retrieval and deterministic SQLite vector fallback with reciprocal-rank fusion.
- Added Crossref and arXiv scholarly adapters and normalized DOI/arXiv/GitHub/document source identifiers.
- Added page-aware evidence metadata and deterministic Markdown/JSON evidence exports.
- Added graceful worker shutdown/resource cleanup and richer secret-free system capability reporting.
- Completed React source controls, document management, tool status, support/conflict states, export actions and page-aware citation inspection.
- Added migration `0005`, pgvector-enabled PostgreSQL CI, and PostgreSQL exact-vector release gate.

## Milestone 3 — Research intelligence and multi-source RAG
- Added bounded Jev routing, coverage evaluation, and claim-support verification with deterministic fail-closed fallback.
- Added a second targeted research wave when coverage is materially incomplete.
- Added OpenAlex academic metadata/abstract retrieval with explicit provenance.
- Added read-only GitHub software research over repository/release/license/README metadata.
- Added text/Markdown document ingestion and document-scoped RAG.
- Added optional Gemini Embedding 2 semantic retrieval and reciprocal-rank fusion.
- Added claim support states and frozen routing evaluation fixtures.
- Added migration 0004 for user documents and Milestone 3 ADR/development docs.

## 0.2.0-dev — 2026-10-03

Milestone 02 live research slice: bounded planning and SearXNG discovery, safe multi-source retrieval, ranked/diversified evidence RAG, immutable document versions and exact evidence offsets, structured Gemini evidence synthesis, provider-specific failure states, centralized runtime composition, local SearXNG profile, richer streamed progress and live smoke tooling.

## 0.1.1-dev — 2026-10-03

Milestone 01 hardening: demo-first SQLite configuration, PostgreSQL migration `0002`, serialized provider/model quota reservations, concurrent quota tests, PostgreSQL-backed CI gate, local doctor command, and reproducible setup guide.

## 0.1.0-dev — 2026-10-02

Initial tested vertical slice: durable runs/jobs/events, keyless recorded demo, strict-free live adapters, safe public retrieval, claim-level citations, responsive research UI, migrations, tests and CI scaffold. Deployment intentionally omitted.
