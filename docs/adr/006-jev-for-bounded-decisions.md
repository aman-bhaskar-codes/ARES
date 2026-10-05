# ADR 006 — Jev for bounded routing and evaluation

## Status
Accepted for Milestone 3 as an optional, explicitly configured adapter.

## Decision
Use TypeSafe Jev only for narrow typed decisions: task/source routing, evidence-coverage checks, and claim/evidence support classification. Gemini remains the synthesis model. Deterministic application policy retains control of source permissions, URLs, budgets, quotas, retries, and terminal outcomes.

Jev is never an automatic paid fallback. `JEV_ENABLED=true` requires an explicit `JEV_API_KEY`. If Jev is unavailable during a run, ARES fails closed to deterministic routing/evaluation and records the provider decision path.

## Why
The current Jev API is shaped around Noul, Choice, and Score primitives and returns typed probabilities/confidence, which is a better fit for machine routing/checking than free-form generation. It is metered, so strict-free operation cannot depend on it implicitly.

## Revisit
Revisit after held-out routing/support evaluations demonstrate whether Jev materially improves ARES over deterministic policy and/or a Gemini structured-decision baseline.
