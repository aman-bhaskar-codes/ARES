# Blueprint baseline and material gaps

The supplied ARES blueprint is accepted as the architecture baseline. This first implementation slice intentionally implements the blueprint's Section 52 handoff order: local shell, conversation/run API, durable job/event persistence, replayable progress, fixture answer and citation inspection, then live safe search and Gemini adapters.

## Closed in this slice

- Durable run/job/event state with lease fencing and idempotency.
- Keyless recorded demo that does not masquerade as live research.
- Safe public retrieval boundary with SSRF/DNS-rebinding controls.
- Gemini structured synthesis behind a provider port and strict-free quota gate.
- Claim-to-evidence persistence and inspectable citation UI.
- Cancellation that stops admission of new retrieval work.
- API contract export, migration, pinned CI actions and responsive UI source.

## Still open before calling the whole product “V1 complete”

- Real PostgreSQL integration/concurrency/RLS tests; this sandbox has no PostgreSQL runtime.
- Network-resolved `uv.lock` and `pnpm-lock.yaml`; neither is fabricated offline.
- Frontend install/typecheck/test/build and browser E2E execution.
- Live SearXNG + Gemini smoke with the user's actual free-project quotas.
- Research-mode multi-wave coverage checks beyond the current one-wave cited web loop.
- Document RAG plus academic/software source adapters.
- Multi-user identity/authorization path and deletion/privacy workflows.
- OpenTelemetry export and measured evaluation report.

Browser/news/MCP remain deferred exactly as the blueprint recommends; they are not prerequisites for the next V1 gate.
