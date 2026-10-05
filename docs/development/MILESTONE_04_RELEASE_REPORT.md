# Milestone 04 release report

**Date:** 2026-10-03  
**Scope:** full-stack researcher workflow, PDF/page provenance, persistent hybrid RAG, scholarly adapters, exports and production lifecycle hardening.

## Completed behavior

- PDF/Markdown/text document intake with content-addressed blob storage.
- PDF parsing in a bounded subprocess with page map, page count, warnings, parser version and OCR-needed state.
- Reusable document identity separated from per-run evidence source identity.
- Persisted chunks and model/dimension-versioned embeddings.
- Exact PostgreSQL pgvector cosine retrieval; deterministic SQLite vector fallback for demo/tests.
- Reciprocal-rank fusion across lexical and semantic retrieval with bounded selection.
- OpenAlex + Crossref + arXiv academic metadata/abstract research and GitHub software research.
- Canonical source identifiers for DOI/arXiv/GitHub/local documents.
- Page-aware evidence and claim support/conflict states.
- Deterministic Markdown and JSON evidence exports.
- Secret-free tool/status endpoint.
- Graceful worker stop-admission/drain/cleanup path.
- React source policy controls, document workspace, system workspace, export UI and richer evidence drawer.
- pgvector-enabled PostgreSQL 18 local/CI baseline.

## Executed checks

| Check | Result |
|---|---|
| Backend test collection | 39 tests |
| Backend execution | 37 passed; 2 PostgreSQL-only tests skipped because no test server is configured here |
| M4 focused tests | Passed |
| Clean SQLite migration | `0005 (head)` |
| OpenAPI regeneration | Passed |
| Python compileall | Passed |
| Backend lock validation | `uv lock --project backend --check --offline` passed; 76 packages resolved from lock |
| Frontend TypeScript typecheck | Passed using portable JS/type dependencies from the user's completed M1 install |
| Secret-shaped source scan | No matching API-key/token patterns found |

## Environment gates intentionally not claimed

- PostgreSQL/pgvector integration tests require `ARES_TEST_POSTGRES_URL`; CI and the manual guide execute them.
- Vitest/Vite cannot execute in this Linux sandbox using the user's macOS-installed Rolldown native package, and npm DNS is unavailable for reinstall. Run `pnpm install --frozen-lockfile`, `pnpm ... test`, and `pnpm ... build` on the target machine/CI.
- Live external-provider quality/availability depends on the user's configured SearXNG and provider quotas. No live benchmark claim is made.

## Security/reliability notes

- No arbitrary repository code execution.
- No browser automation or arbitrary plugin URLs.
- Public web retrieval remains behind SafeFetcher/egress policy.
- PDF bytes are size-bounded and parsing is process-isolated/bounded.
- Scanned PDFs are not silently treated as parsed text.
- Gemini synthesis receives selected evidence; citation IDs are server-resolved.
- Jev remains a bounded typed-decision adapter and is not silently enabled in strict-free mode because it is metered.
- No automatic paid provider fallback.
