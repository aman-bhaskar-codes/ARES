# ADR 002 — Gemini-first, strict-free, verified dependency baseline

**Status:** accepted with lockfile gate — 2026-10-02

## Decisions

- Use the official `google-genai` Python SDK behind `LLMProvider`; current verified public release is **2.26.0**, not the blueprint snapshot's 2.28.0.
- Use Gemini Interactions structured JSON output so model responses are schema-validated before citations are assembled.
- Configure one Gemini model explicitly (`gemini-3.8-flash` candidate). Never select a paid fallback automatically.
- `local_live` requires `STRICT_FREE_MODE=true`, `ALLOW_BILLABLE_PROVIDERS=false`, a server-side API key, and explicit RPM/TPM/RPD ceilings copied from the user's project.
- SearXNG remains the discovery adapter; the application does not depend on a public instance.
- Direct runtime versions are pinned in manifests, but reproducible lockfiles remain a release gate because registry access is unavailable in this sandbox.

## Consequences

Provider changes are localized to adapters. Local counters are conservative controls, not a guarantee about Google billing/account configuration. A live smoke/evaluation is required before claiming provider compatibility or quality.
