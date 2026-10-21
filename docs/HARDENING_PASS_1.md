# ARES hardening pass 1 — delivery record

Branch: `fix/hardening-pass-1`. Starting checkout: `049e640` (newer than the attached review's `476d69b`). All eleven numbered tasks have implementation commits. This is an engineering hardening pass, not production deployment or a scientific-quality certification.

| Task | Commit | Change and verification |
|---|---|---|
| 1 | `3e8ca0c` | Unconditional startup security validation; production docs disabled. New startup/production-doc tests; baseline media fixtures isolated from environment settings. 231 backend / 21 frontend tests passed. |
| 2 | `9d40cdd` | Alembic-derived readiness head and explicit override. Default/head and matching/stale readiness tests. 233 / 21 passed. |
| 3 | `03cd946` | Separate production SearXNG settings, required secret and limiter storage; production bind-mount secret guard tests. 235 / 21 passed. |
| 4 | `1f9abe6` | One owner per route, injected dependencies, shared stream revalidation; 45-line API factory. Route/operation ownership test; exported paths and schemas unchanged. 236 / 21 passed. |
| 5 | `aeac07b` | Removed the requested archives, scratch scripts, root lock stub and raw E2E artifacts. Renamed the persistence helper; kept operational summary. 236 / 21 passed. |
| 6 | `60e4c7e` | Official action release SHAs, dependency review, broader lint and incremental typing, package.json pnpm source. Bounded XML attack tests and documented rule exceptions/type debt. 238 / 21 passed. |
| 7 | `eae9f2d` | Accurate stack/startup README, security policy, architecture and evaluation methodology. 238 / 21 passed. |
| 8 | `d9dd2ee` | Provider protocol/registry, shared grounded parser, bounded/configurable Ollama context, single JSON decode and relaxed retry. Retry/invalid-index tests; no invented citations. 240 / 21 passed. |
| 9 | `e038bc1` | Streaming full/ranged downloads, file-based bounded PDF parsing and spooled upload, RFC 5987 Unicode names, explicit GitHub identifier matching, package API version and contextual exception logs. Unicode, range, parser/file-upload tests. 245 / 21 passed. |
| 10 | `fbb26a2` | Explicit stream replay cursor/auth expiry, CSRF tests, hidden maps and denied map serving, vendor chunks. Entry bundle 158.12 kB. 246 / 25 passed. |
| 11 | `53b4dd3` | 112 support cases, 50 graded retrieval queries, 100 externally annotated SciFact holdout records, annotation-edge scores, run mean/std and regression CI gates. Dataset/metric/repeat tests. 250 / 25 passed. |

The four required checks (ruff, complete backend pytest, frontend typecheck, frontend vitest) passed after every numbered task. Latest complete backend run with PostgreSQL enabled: **260 passed, 1 skipped** (backup CLI version mismatch). The skipped backup/restore test then **passed separately with PostgreSQL 18 tools**. Latest frontend run: **25 passed**. Expanded strict mypy gate: **88 source files, no issues**, with explicit legacy module overrides. Production build passed. Secret scan passed. One third-party Starlette test-client deprecation warning remains.

## Explicit limits and deferred verification

- **Scientific support quality fails the external holdout thresholds:** exact label accuracy 26%, annotation-based citation precision 67.3%, citation recall 28.2%. See [HARDENING_RESULTS.md](evaluation/HARDENING_RESULTS.md). These are heuristic checker metrics, not generated-answer faithfulness. A calibrated semantic/NLI evaluation remains necessary; the holdout was not tuned away.
- **PostgreSQL verified locally:** migrations from empty and historical revisions to 0021, pgvector, RLS and concurrent quota/run admission passed against an isolated PostgreSQL 18 database. **Remote CI remains unverified:** the branch has not been pushed or run remotely.
- **Fresh live search/model E2E passed:** the same RAG question completed with Gemini (308 words, 5 claims) and Qwen (131 words, 2 claims); every citation resolved. Both answers were inspected in the browser. These transport/rendering checks do not establish semantic correctness. Qwen remains slower and less detailed on this local model. Evidence is in `/tmp/ares-hardening-live/live-result.json` and browser screenshots in that directory.
- **Typing is incremental.** Legacy module overrides are listed in [HARDENING_TYPE_DEBT.md](HARDENING_TYPE_DEBT.md); adapters are outside the widened gate.
- Hidden source maps are blocked by the API static mount. No error-tracker upload is configured because the repo has no tracker account/configuration.
- The asynchronously loaded chart chunk remains about 547 kB; the entry chunk meets the requested under-500-kB target.
- The SciFact sample is academic-only and bounded-candidate retrieval; it does not qualify the separate M11 multimodal release gate or establish full-corpus BEIR performance.
- A broader decomposition of every large application/persistence module was not part of the numbered tasks. Retained broad boundaries are listed in [EXCEPTION_BOUNDARIES.md](EXCEPTION_BOUNDARIES.md).

The pre-existing README work was saved to `/tmp/ARES-README-before-hardening.md` before the requested rewrite. The user's untracked `ares_banner.jpg` was left untouched. Changes are local commits only; no deployment, merge, push or PR was performed.

## Final verification corrections

Real Compose parsing caught and corrected malformed nested search dependencies. Added a Docker CLI configuration regression test. Container health probes now supply the public Host header while connecting only to loopback. The worker uses cached reranker models, avoiding an unexpected startup download; uncached rerankers retain retrieval order. PostgreSQL admission tests account for existing fixture runs and clean up their conversation. Backup/restore tests create a separate temporary database so destructive rehearsal cannot affect other fixtures.

The existing local chat SQLite database was backed up to `/tmp/ares-hardening-live/user-before-0021.sqlite3`, migrated additively to 0021, and the normal API/worker restarted. Readiness returned `ready` in `local_live` mode.
