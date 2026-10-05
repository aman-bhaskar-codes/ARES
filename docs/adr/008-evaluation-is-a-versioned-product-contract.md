# ADR 008 — Evaluation is a versioned product contract

**Status:** accepted

## Context

ARES makes evidence-quality claims that ordinary unit tests cannot validate by themselves. Routing, retrieval, citation resolution, claim support, conflict handling, and adversarial-source behavior can regress while APIs continue to return HTTP 200.

At the same time, a tiny implementation-authored dataset can be overfit easily and must not be presented as an external benchmark.

## Decision

ARES keeps a versioned evaluation layer with separate metrics and explicit dataset provenance.

- Development regression fixtures are committed and run in CI.
- Held-out datasets are not authored by the implementation loop and have a documented independent-population protocol.
- Routing, claim support, retrieval, and security-observability metrics remain separate.
- CI thresholds are regression tripwires, not product-superiority scores.
- Per-run diagnostics are exposed as descriptive facts, never as a single opaque “quality score.”
- Jev and live semantic retrieval are opt-in ablations because they can consume metered/provider quota; deterministic lexical regression remains the offline CI baseline.

## Consequences

A pull request can fail because research behavior degraded even when API/unit tests pass. Evaluation reports remain machine-readable and reviewable. ARES cannot honestly claim an external benchmark result until an independently created/frozen dataset is run under a documented protocol.
