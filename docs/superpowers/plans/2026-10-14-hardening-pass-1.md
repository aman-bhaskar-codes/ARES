# ARES Hardening Pass 1 Implementation Plan

**Goal:** Execute the eleven tasks in the user's attached repository review, preserving public API contracts and existing uncommitted work.
**Architecture:** Keep the durable research pipeline. Harden startup/configuration first, then isolate routing and providers, and add measurable regression coverage.
**Tech stack:** FastAPI, SQLAlchemy/Alembic, React/Vite, SearXNG, Gemini/Ollama.
**Spec:** User attachment `Pasted text.txt`, ARES Repository Review & Fix Prompt, 2026-10-14.

## Global constraints
- Branch `fix/hardening-pass-1`; one reviewable commit per numbered task.
- After each task: ruff, complete backend pytest, frontend typecheck and vitest. Do not advance with a failing gate.
- Preserve existing README edits and untracked banner. No remote publishing requested.
- Preserve API paths and schemas, except removal of duplicate operations.

## Review focus
Production disabled auth; stale readiness revisions; failed optional providers; interrupted streams; Unicode download filenames.

## Ordered execution
- [ ] 1. Startup validation and production documentation exposure; regression tests in integration API security tests.
- [ ] 2. Alembic-derived schema head with optional override; readiness mismatch tests.
- [ ] 3. Production-only SearXNG configuration and compose secret scan.
- [ ] 4. Thin factory, explicit dependency injection, shared stream authorization, unique route tests, regenerated schema.
- [ ] 5. Remove tracked artifacts and rename persistence module; keep summary only.
- [ ] 6. Pinned actions, dependency review, incremental lint/type gates and single pnpm source.
- [ ] 7. Accurate README, architecture, methodology and security policy.
- [ ] 8. Shared synthesis codec, model registry, bounded configurable Ollama client and retry tests.
- [ ] 9. Streaming downloads, spooled uploads, safe Unicode headers, identifier matching, version and boundary logging.
- [ ] 10. Hidden source maps, lazy heavy views, reconnect/auth/CSRF tests.
- [ ] 11. Expanded labeled eval corpus and held-out manifest, support/retrieval metrics, repeated-run variance and CI gates.

For each behavior: reproduce with a failing test, implement, run the four required gates, then commit only that task's files. Record commits and results in the final hardening report.
