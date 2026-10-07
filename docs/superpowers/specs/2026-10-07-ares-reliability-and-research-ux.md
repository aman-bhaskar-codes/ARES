# ARES reliability and research UX design

## Outcome
Make the existing ARES application reliably answer questions with inspectable citations, restore research history, accept supported documents, and export results. The user wants a simpler Perplexity-style experience and dependable tools/backend. Preserve ARES branding and evidence provenance. This is an existing-system repair, not a claim of proprietary Perplexity feature parity.

## Evidence from the audit
- Frontend typecheck failed because two unreferenced prototype components used unresolved imports and missing types. Removed those unused components; production build and 19 frontend tests pass.
- Recent stored live runs failed with `RetrievalTraceItem` missing `id`. Existing uncommitted engine edits bypass the erroneous call. The ranking trace dataclass and persisted RetrievalTrace model are separate contracts; do not pass one as the other.
- Hosting built frontend files registered the catch-all mount before API routers, causing health and API requests to return 404. Repaired ordering and added an integration regression.
- PDF export returned HTML bytes under a PDF MIME type if Playwright was absent. Replaced the false success with an actionable export error; renderer failures also surface through the existing API error contract.
- JSON exports unnecessarily changed their schema version despite retaining their existing structure. Restored the v1 contract while keeping additive provenance.
- SQLite upgrades failed at 0016 because it unconditionally altered the PostgreSQL-only vector table. Added dialect guards; 0017 now supports JSON arrays on SQLite and retains native arrays on PostgreSQL.
- 0015 linked document embedding profile IDs to the embedding table itself. Added corrective migration 0019 linking to retrieval_profiles, preserving already-applied migration history.
- Migration verification used a stale expected head and a potentially unrelated Alembic executable. It now uses the current Python interpreter and verifies 0019 across six upgrade paths.
- Configured local database is SQLite at revision 0015. Research worker profile is configured, while rich ingestion needs a media/combined worker. Settings claim configured providers, which is not proof of successful provider calls.
- Composer clears entered questions after a failed request and lacks a pending admission lock. Conversation restoration and snapshot adoption need protection from stale asynchronous responses.
- Frontend has visible technical status and duplicated sticky composer styling; optional capability tabs can appear even when unavailable.

## Proposed UX
Keep a quiet left sidebar for new research, history, and documents. Center the home screen on a single question composer, with restrained ARES typography and teal accent. Replace the promotional hero and three large example cards with a short prompt and compact suggestions. Put runtime diagnostics in settings.

The primary thread view shows the question, compact progress, readable answer, and citation cards. Keep Answer and Sources as primary views. Expose charts/comparison only when supported; keep detailed activity and quality diagnostics behind an explicit disclosure. Advanced source selection remains available but does not dominate the default composer. Preserve mobile navigation, theme support, visible focus, reduced motion, and accessible evidence drawers.

## Proposed behavior repairs
1. Track admission separately from active-run execution. Prevent repeated submission across composer and suggestions. Preserve draft after failure and show a correction/retry path; clear only after acceptance.
2. Use a stable run query key and reject snapshots that belong to a previous run or tenant. Add explicit loading/error states for restoring conversation history. Cancel or ignore superseded navigation reads.
3. Prevent uploads from entering queues without the appropriate worker. Surface actual capability readiness; retain PDF/text compatibility uploads. Do not advertise unavailable audio/video/OCR.
4. Unify export/download error handling and expose only formats the backend can actually produce.
5. Replace trace bypasses with an intentional recording boundary: persist ranking information in lease-fenced run events, or build complete database traces with a valid retrieval profile. Cover ordinary and targeted follow-up retrieval.
6. Verify synthesis, web search, academic and software providers independently; degrade with explicit gaps when optional providers fail. Keep current free-provider policy and bounded quotas.
7. Reconcile model/storage types and schema readiness to the migration head, including PostgreSQL permissions/RLS for newly introduced tables. Verify profile identity and vector index isolation.
8. Provide one documented local startup command for API, research worker, ingestion worker, and frontend; fail early on missing prerequisites. Preserve production process separation.

## Verification and acceptance
- Frontend typecheck, unit tests, production build.
- Backend unit/integration/security tests and clean/upgrade migration paths.
- Browser success, failed submission with retained draft, duplicate-click prevention, stop/retry, history navigation/deep links, evidence drawer, document ingestion, and downloaded export.
- Narrow viewport, keyboard navigation, light/dark themes, long answers, and reduced motion.
- Real live research through configured search and synthesis providers; mocked contract tests alone do not prove this.
- PostgreSQL/pgvector/RLS tests against a dedicated disposable test database; never run destructive database tests against the user's working data.

## Constraints and unresolved decisions
Preserve all pre-existing uncommitted work and research data. Do not expose credentials in logs or browser output. Do not upgrade the working database without a backup and a tested compatible path. Do not claim production readiness before live providers and PostgreSQL gates have passed.

Recommended execution: native implementation in this chat, with focused regression tests and browser verification. Review this design before the broader UI/architecture changes; a subsequent implementation plan will define the exact sequence and verification gates.
