# Implementation status — 2026-10-05

## Milestones 01–06

ARES now contains the full source implementation through the multi-user release-candidate boundary. Earlier milestones remain integrated: durable jobs/events, strict-free live research, multi-source web/academic/software/document tooling, page-aware PDF RAG, persistent hybrid retrieval, pgvector, claim-level evidence, exports, evaluation, adversarial security regression, backpressure, observability and the full researcher workspace.

## Milestone 06 implemented in source

- OIDC Authorization Code + PKCE S256 with one-time state/nonce and same-origin return paths;
- JWKS-backed ID-token signature validation plus issuer, audience, authorized-party, time and nonce checks;
- opaque server-side sessions, independent CSRF token, logout/revocation and no provider-token persistence;
- workspace roles (`viewer`, `editor`, `owner`) and application authorization;
- workspace ownership columns plus PostgreSQL `FORCE ROW LEVEL SECURITY` on research-bearing data;
- per-transaction tenant context reset to prevent pooled-connection tenant leakage;
- separate API (`NOBYPASSRLS`) and worker (`BYPASSRLS`) database privilege groups;
- per-user, per-workspace and fleet-wide active-run admission limits with PostgreSQL serialization;
- narrow `SECURITY DEFINER` aggregate for fleet-wide active-run count without granting the API general cross-tenant reads;
- worker fleet presence/draining health and optional readiness requirement for a live worker;
- production Trusted Host, CSP/HSTS and related browser security headers plus bounded request bodies;
- non-root/read-only production containers with split internal-data and public-egress networks;
- production doctor, migration compatibility verifier, backup/restore, rollout/rollback and deterministic release-archive tooling;
- CI release gates for PostgreSQL/RLS/pgvector, migration compatibility, frontend build/test, evaluation, production Compose and image construction;
- authenticated frontend bootstrap, session-expiry recovery, account/workspace switch, logout and role-aware mutation controls.

## Executed validation in this sandbox

At final release freeze the following gates were executed here:

- backend: **83 passed, 6 skipped**; all six skips require `ARES_TEST_POSTGRES_URL`;
- development regression suite: gate passed across 30 routing, 12 claim-support, 10 retrieval-corpus and 16 security-observability fixtures;
- migration compatibility: clean database -> `0006`, and `0005` -> `0006`;
- production configuration doctor: passed with a synthetic secure configuration; optional OTLP/embedding settings reported only as warnings;
- Python compileall: passed;
- OpenAPI export: regenerated from the M6 API;
- deterministic secret-shaped-material scan: passed across source candidates;
- TypeScript production-source typecheck: passed using the exact pinned React/TanStack/Lucide type packages available from the previously installed dependency snapshot.

The synthetic development evaluation fixtures are regression tests, **not an external or held-out benchmark** and not evidence of product superiority.

## Environment-specific release gates still external

This sandbox has no PostgreSQL/pgvector server, Docker daemon, OIDC identity provider or Linux-native reinstall of the frontend dependency tree. Therefore these remain target-machine/CI/live gates rather than claimed local passes:

1. six PostgreSQL-only integration tests: provider-quota concurrency, active-run concurrency, exact pgvector ordering, production readiness/Trusted Host, direct RLS isolation and pooled-connection tenant reset;
2. native-platform Vitest and Vite production build from a fresh `pnpm install --frozen-lockfile`;
3. Docker image build and production Compose runtime validation;
4. live OIDC sign-in against the operator's provider and live SearXNG/Gemini/OpenAlex/Crossref/arXiv/GitHub provider smoke tests under the operator's actual credentials/quotas;
5. independent penetration testing and an independently authored held-out evaluation set.

## Deliberately outside the M6 RC source boundary

- OCR execution (image-only PDF detection exists);
- browser-rendered crawling for JavaScript-only sources;
- approximate pgvector indexes before measured need;
- public deployment itself;
- production uptime/SLO claims;
- external benchmark-superiority claims.

## Milestone 07 — verified foundation and responsive execution

M07 source implementation is complete in ARES `0.7.0` / schema `0007`. The stale backend lock blocker is closed, local backend/migration/evaluation/security/contract gates pass, and a strict connectivity doctor is included for target environments. The locally executable suite collects 122 backend tests: 116 pass here and six PostgreSQL-only cases are explicitly skipped because this sandbox has no PostgreSQL service.

Environment-dependent promotion gates remain intentionally external rather than falsely marked successful: fresh pnpm/Vitest/Vite build, PostgreSQL/pgvector/FORCE-RLS with the intended runtime roles, production containers, live OIDC/provider checks, and remote GitHub Actions. See `MILESTONE_07_RELEASE_REPORT.md` and `MILESTONE_07_HANDOFF.txt`.

## Milestone 08 — documents, images, tables and local indexing

M08 source implementation is complete in ARES `0.8.0` / schema `0009`, extending M07 in place. New V2 assets are admitted as durable asynchronous jobs while the V1 document endpoints remain compatible. Immutable extraction versions and evidence segments add text/page-region/table-cell provenance; CSV/table lineage is persistent; optional Docling/RapidOCR and FastEmbed live in the resource-limited media profile; corpus embeddings are generated during ingestion rather than research queries; PostgreSQL lexical retrieval is bounded and GIN-backed.

The locally executable backend suite now collects 128 tests: **122 pass and six PostgreSQL-only cases are skipped** because this sandbox has no PostgreSQL service. M08 focused integration has six passing cases, migration compatibility passes for empty/0007/0006 -> 0009, the secret scan passes, and OpenAPI/frontend generated contracts were refreshed.

Promotion remains evidence-gated: run fresh `pnpm install --frozen-lockfile` + typecheck/Vitest/Vite, PostgreSQL/pgvector/FORCE-RLS under API/worker roles, production core/media image builds, provisioned Docling/RapidOCR/FastEmbed model profiles, and the plan's licensed OCR/table fixture evaluation before calling M08 production-complete. See `MILESTONE_08_RELEASE_REPORT.md` and `MILESTONE_08_HANDOFF.txt`.

## Milestone 09 — audio and short-video evidence

M09 source implementation is complete in ARES `0.9.0` / schema `0010`, extending M08 in place. Configured WAV/MP3/M4A/Ogg/WebM audio and MP4/WebM video reuse the durable M08 asset/ingestion/evidence contracts. Local ASR is isolated behind a typed `faster-whisper` subprocess; videos reuse that transcript path and add bounded presentation-timestamp frame sampling, optional frame OCR and explicit sampled-coverage warnings. Transcript/frame evidence is published into the existing document-chunk retrieval path with `time_range`/`frame_region` locators, so normal research citations can navigate back to the original authorized media.

The media worker now advertises actual capabilities rather than only configuration flags. Admission rejects audio/video that no worker can process, while video can intentionally degrade to visual-only evidence when FFmpeg is ready but ASR is not. Media tracks, frame metadata/renditions, waveform summaries and asset-level cloud-media consent are persisted under migration `0010`; deletion removes derived frame blobs as well as the original asset. The existing React workspace/evidence drawer gains capability-aware uploads, optional explicit microphone capture, media playback/seek and storyboard inspection without a framework migration.

Fresh locally executable validation: **142 backend tests pass and six PostgreSQL-only cases skip**, the focused M09 suite contributes 22 passing tests, migration compatibility passes for empty/0009/0007/0006 -> `0010`, compileall and secret scan pass, `uv lock --check` passes, and OpenAPI/generated frontend contracts are refreshed. Real FFmpeg/ffprobe fixture processing is exercised in the integration suite.

Promotion remains evidence-gated. This sandbox cannot perform a frozen pnpm install/typecheck/Vitest/Vite build, PostgreSQL/FORCE-RLS target-role tests, production image/Compose runtime, or real faster-whisper model evaluation because those external dependencies/services are unavailable here. The V2 requirement for a licensed set of at least 20 audio clips and 10 videos with WER/RTF/RSS/timestamp/coverage reporting therefore remains open. See `MILESTONE_09_RELEASE_REPORT.md` and `MILESTONE_09_HANDOFF.txt`.

## Milestone 10 — faster, stronger live research

M10 source implementation is complete in ARES `0.10.0` / schema `0011`, extending M09 in place. Web/academic/software discovery now executes as bounded independent tracks under the M07 run deadline/resource ledger; workspace-scoped research caching coalesces duplicate permitted work; provider backoff and optional-track failures produce durable partial-result signals. Source identity now persists conservative origin groups, exact DOI/arXiv/GitHub matches are prioritized, question coverage is represented as explicit facets, and per-claim evidence edges preserve supports/contradicts/contextualizes semantics with rationale and checker provenance.

Open-access academic PDF candidates from OpenAlex/arXiv can be fetched only through the existing SSRF-resistant safe HTTP path and parsed by the M08 bounded PDF parser. Optional Gemini semantic assessment is schema-constrained, budgeted and worker-time-bounded after deterministic checks. A separate authenticated Playwright renderer exists only as a policy-gated fallback; it remains disabled by default and production activation requires the documented external egress firewall plus pinned non-root sandbox/seccomp boundary.

Fresh locally executable validation collects **185 backend tests: 179 pass and six PostgreSQL-only cases skip**. The deterministic regression, compileall, migration compatibility (empty/0010/0009/0007/0006 -> `0011`), secret scan and OpenAPI/frontend contract regeneration pass. A same-fixture synthetic Quick-run A/B measures sequential p95 246.292 ms versus bounded-concurrent p95 139.195 ms, a 43.48% reduction; this is explicitly not a live-provider or historical M07 binary benchmark. Lexical development retrieval regression passes, while local FastEmbed dense/RRF and PostgreSQL indexed retrieval are NOT RUN here; therefore no reranker is promoted without measured evidence.

Promotion remains evidence-gated: PostgreSQL/FORCE-RLS/indexed/mixed-load tests, fresh pnpm typecheck/Vitest/Vite, browser Docker/seccomp/egress SSRF runtime validation, live provider/Gemini smoke tests and independent held-out retrieval/support evaluation must run on a suitably provisioned target. See `MILESTONE_10_RELEASE_REPORT.md` and `MILESTONE_10_HANDOFF.txt`.


## Milestone 11 — visual research workspace and V2 release proof

M11 source development is complete as the ARES `0.11.0` / schema `0012` release candidate, extending M10 in place. Stable run/evidence deep links, safe rich answer rendering, evidence filters, semantic themes, deterministic lineage-bearing visualization datasets/specs, read-only retrieval + authorized CSV export, worker publication, comparison/numeric/timeline/relationship views, accessibility fallbacks, SBOM/reproducible-release tooling and pinned CI gates are integrated.

Fresh locally executable backend validation is **193 passed / 7 PostgreSQL-only skips**; focused M11 integration is **14 passed**; migration compatibility, compileall, secret scan, deterministic regression and the M11 release verifier pass. In the networked frontend validation sandbox, the exact M11 manifests/lock graph pass pnpm 12.8.1 frozen install, TypeScript, **18 Vitest tests across 5 files**, and the Vite production build. The production npm audit reported no known vulnerabilities at the configured high-severity gate at validation time.

M11 source completion is **not public-production promotion**. PostgreSQL/FORCE-RLS target-role execution, three-browser E2E/manual accessibility, recovery/backup and M06→M11 rehearsal, live OIDC/provider/media/browser checks, the independently authored >=100-question held-out evaluation, human review and 3–5 external testers remain environment/human gates. See `MILESTONE_11_RELEASE_REPORT.md` and `MILESTONE_11_HANDOFF.txt`.
