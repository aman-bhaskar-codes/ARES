# Milestone 10 Release Report — Faster, stronger live research

**Candidate:** ARES `0.10.0` / schema `0011`  
**Baseline:** supplied `ARES_M09_release_candidate(1).zip`, SHA-256 `8d3f853a67de816a21aaf38b59461b3fbaf15be7fcb442775900d1b46a745536`; M10 is an additive continuation, not a rewrite.  
**Date:** 4 October 2026

## Implemented scope

M10 keeps the M07 execution contracts and the M08/M09 provenance model. It does not add a second research engine, vector database, tenant store, job system or browser authority to the LLM.

### M10-01 — bounded concurrent discovery and cache

- Web, academic and software discovery are coordinated as independent bounded tracks under one `RunContext`, absolute deadline and existing PostgreSQL fleet/provider resource leases.
- Failure of one optional track no longer discards successful independent tracks. Provider rate-limit failures produce a durable `provider.backoff` event, including bounded `Retry-After` metadata when available.
- Search/document caching is workspace-scoped and policy/version/date/provider aware. Cache reuse never masquerades as a fresh provider call, and provider budgets count actual attempts rather than cache hits.
- Concurrent identical permitted requests are coalesced without holding a database transaction across the network request. Worker maintenance removes expired cache rows in bounded batches.
- The targeted recovery wave uses the same budget/cache/resource path rather than bypassing M10 controls.
- Safe HTTP remains the primary web reader. Existing destination validation/IP pinning, redirects, byte limits and request deadlines remain intact.

### M10-02 — retrieval, source independence and coverage

- Existing PostgreSQL GIN lexical retrieval + versioned vector retrieval + RRF remain the retrieval foundation; M10 does not introduce Qdrant/Elasticsearch by default.
- Exact DOI, arXiv and GitHub repository identifiers are preferred over fuzzy metadata matches.
- Source independence now has durable origin grouping. DOI and arXiv version aliases normalize to one origin; public-text near-copy grouping uses a conservative salted MinHash/shingle fingerprint so copies do not inflate independent support while unrelated sources remain distinct.
- Coverage is persisted as facet records with `supported`, `conflicting` or `missing` status, supporting/opposing evidence IDs, independent-origin counts, rationale and checker provenance.
- OpenAlex `best_oa_location.pdf_url` and arXiv PDF links can be treated as *candidates* for academic full text. The existing safe public fetcher retrieves bounded PDFs and the M08 PDF parser extracts page-aware evidence. If full text cannot be fetched/parsed, the metadata/abstract remains explicitly metadata/abstract rather than being relabeled as a read paper.
- Academic PDF enrichment is separately bounded and cached; it never uses the browser fallback.
- No reranker was promoted because this environment cannot produce the required measured relevance-versus-CPU evidence. That is an intentional release decision, not a missing dependency hidden as success.

### M10-03 — bounded semantic checking and validated answer blocks

- Deterministic identity/number/unit/date/polarity checks remain first. Only materially ambiguous claims are eligible for optional semantic assessment.
- The Gemini semantic adapter uses a typed structured-output contract and returns one of `supported`, `partial`, `conflicting` or `insufficient`, with supporting/opposing evidence references and bounded rationale.
- Returned evidence references are server-validated; the model cannot manufacture authoritative evidence IDs.
- Semantic requests use the same usage ledger and a worker-enforced timeout in addition to provider/SDK timeouts. Checker outage/timeouts preserve conservative deterministic assessment and emit degradation events; they never upgrade heuristic evidence to verified support.
- Claim/evidence edges persist `supports`, `contradicts` or `contextualizes` plus rationale/checker method/version. The run-quality API exposes those edges and facet coverage to the existing React workspace.
- `answer.block.validated` is emitted for finalized validated blocks while legacy `answer.block` compatibility remains for rolling clients. Copy/export continue to use the finalized server representation.

### M10-04 — isolated browser fallback

- `BrowserFetcher` is an allowlisted fallback after ordinary Safe HTTP extraction fails; an unsafe URL is never retried through Chromium.
- Chromium runs in a separate sidecar image, not the API/research worker. The sidecar creates a fresh context per render, disables downloads and service workers, blocks WebSockets and non-GET/HEAD traffic, and revalidates target/final/subresource URLs.
- A separate >=32-character bearer token protects worker-to-browser RPC. Production settings reject browser enablement when the token or service origin is invalid.
- The production overlay gives the browser no database/Gemini/OIDC environment, blob/host volumes, Docker socket or public host port; it runs as `pwuser`, drops Linux capabilities, uses a read-only root, bounded tmpfs/RSS/CPU/PIDs, `no-new-privileges` and a pinned Playwright-compatible seccomp profile.
- `scripts/vendor_playwright_seccomp.py` pins the Playwright `v1.63.0` profile and verifies upstream Git blob SHA `fddc05fb520affb145404e6f6f647ca96af8087d`. The profile is intentionally not replaced by `seccomp=unconfined` when unavailable.
- `BROWSER_ENABLED` remains false by default. Application URL checks are defense in depth; production activation still requires an externally enforced egress firewall/network policy that blocks private/internal/link-local/cloud-metadata destinations for all browser-originated traffic.

## Migration and contracts

Migration `0011_research_assessments` adds the M10 bounded research cache, source-origin identity, facet coverage and per-edge relation/rationale/checker provenance. Upgrade verification passes for empty / `0010` / `0009` / `0007` / `0006` -> `0011`. No destructive cleanup of older M07-M09 rows is required.

OpenAPI was regenerated from the `0.10.0` API and frontend generated schemas were refreshed. The handwritten frontend refinement now treats M10 quality defaults (`facets`, relations, counts and timings) as present values matching the server response rather than nullable/undefined network assumptions.

## Fresh validation executed in this sandbox

- backend collection: **185 tests**; **179 pass / 6 PostgreSQL-only skip**;
- full deterministic regression: PASS across 30 routing, 12 claim-support, 10 retrieval and 16 security fixtures;
- compileall: PASS across backend source/tests, scripts and browser sidecar;
- migration compatibility: **empty/0010/0009/0007/0006 -> 0011 PASS**;
- deterministic secret-shaped-material scan: PASS across 271 source candidates before release freeze;
- OpenAPI export/frontend generated-contract refresh: PASS;
- M10 integration coverage includes concurrent discovery, cache reuse/isolation/normalization, date-window cache identity, provider 429 partial continuation, academic full-text enrichment/cache, facet/edge persistence, semantic-checker outage and hard timeout;
- browser policy tests cover loopback/RFC1918/link-local/cloud-metadata/IPv6 ULA/link-local rejection plus production-overlay absence of DB/blob/host mounts and public ports;
- same-fixture Quick-run benchmark (20 runs/arm, synthetic 50 ms provider delay, SQLite): sequential p95 **246.292 ms**, M10 concurrent p95 **139.195 ms**, measured reduction **43.48%**, target 20%: PASS. This is a controlled development A/B of sequential versus bounded-concurrent discovery on current contracts, **not live-provider p95 and not a historical M07 binary benchmark**;
- retrieval development regression: lexical recall@5 1.0, MRR 1.0, nDCG@5 1.0 on the 10-case development fixture. This is **not an independent external benchmark**.

## Explicitly NOT RUN / external promotion gates

These are not silently counted as passes:

1. PostgreSQL/pgvector/FORCE-RLS target-role suite, indexed PostgreSQL retrieval benchmark and mixed-workload queue/starvation test — `ARES_TEST_POSTGRES_URL` is not configured here.
2. Local FastEmbed dense/RRF ablation — optional runtime/model is not provisioned. Because the quality/latency evidence is absent, the optional reranker remains disabled rather than being added speculatively.
3. Frozen pnpm install, TypeScript project typecheck, Vitest and Vite build — Corepack attempted to obtain the pinned pnpm package but this sandbox cannot resolve `registry.npmjs.org`. Generated API contracts were refreshed; native frontend verification remains a target-machine/CI gate.
4. Browser production image/Compose launch, vendored seccomp materialization and host/container egress-firewall SSRF E2E — container network/Docker/firewall facilities are unavailable here. Source configuration remains fail-closed and browser fallback stays disabled by default.
5. Live SearXNG/OpenAlex/Crossref/arXiv/GitHub/Gemini semantic/provider 429 smoke tests under the operator's real credentials and quotas.
6. Independent held-out retrieval/support evaluation. Development fixtures are regression evidence only.

## Security, privacy and licensing notes

- Research-cache rows are workspace-owned; private documents/media do not enter a shared cross-tenant semantic cache.
- Browser renderer receives no user/provider credentials and cannot perform account login, CAPTCHA bypass, purchases or arbitrary form side effects.
- Same-model Gemini semantic assessment is an assessment aid, not independent truth verification; deterministic contradictions and visible dissent are retained.
- OpenAlex `best_oa_location` is used only to locate a free-to-read copy. Retrieved PDFs retain their original copyright/license; ARES does not interpret discoverability as redistribution permission.
- Browser egress policy is a hard activation gate because DNS/application validation alone cannot close every rebinding/TOCTOU path.

## Rollback

Disable `SEMANTIC_CHECKER_ENABLED` to retain deterministic checking. Disable `BROWSER_ENABLED` to retain Safe HTTP. Disable research caching to return to provider-backed discovery without changing evidence semantics. The existing lexical/RRF retrieval path remains available if optional local embeddings are unavailable. Keep schema `0011`; do not destructively downgrade source-origin, facet or edge-provenance records merely to disable optional M10 capabilities.

## M11 entry condition

M11 can build the visual research workspace on the existing M10 claim/edge/facet/lineage APIs. Before production promotion, execute the external gates above on a networked target/CI environment and retain the results. Do not start M11 by creating a second visualization evidence store or by weakening provenance to simplify charts.
