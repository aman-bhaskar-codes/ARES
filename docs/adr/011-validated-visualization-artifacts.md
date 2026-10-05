# ADR 011 — validated visualization artifacts share the evidence store

**Status:** accepted for M11  
**Date:** 5 October 2026

## Decision

ARES stores visualizations as deterministic, workspace-owned projections over the existing run/evidence model. A visualization consists of a bounded dataset, an approved `VisualizationSpec`, immutable lineage references, export metadata, and a schema version. It does **not** introduce a graph database, executable chart language, arbitrary formulas, SQL/Python execution, or a model-controlled rendering runtime.

The worker derives optional visual artifacts only after a run has reached a useful terminal state. API reads are read-only. Every persisted lineage reference must resolve to evidence from the same run with the same source, segment and locator. Numeric charts accept only normalized finite table-cell values that were promoted into run evidence, and comparable values must share one unit. Evidence maps are bounded to the configured neighborhood and preserve edge semantics such as `supports`, `contradicts`, and `contextualizes`.

CSV exports are generated server-side from the approved persisted dataset. They retain evidence/source identifiers and escape spreadsheet formula prefixes.

## Why

The user-facing value of M11 is inspectability, not decorative charts. Reusing the existing evidence store prevents drift between prose, citations, exports and visuals. Keeping generation deterministic also means a visualization can be reproduced, reviewed, hidden or regenerated without granting a model execution authority.

## Consequences

- PostgreSQL remains the authoritative store; migration `0012_visual_artifacts` is additive.
- API roles receive read-only access to visualization tables; worker roles publish them.
- Missing/invalid lineage causes rejection rather than best-effort display.
- Visual modules can be disabled independently with `VISUALIZATIONS_ENABLED=false` without affecting normal answer/evidence flows.
- Graph/chart libraries are trusted renderers of ARES-approved data, not interpreters of model-produced executable options.
- A correlation plot never upgrades an evidence relation into a causal claim.

## Alternatives rejected

A separate graph/vector database would duplicate authorization and provenance. Storing ECharts/React Flow executable configuration from a model would create an unnecessary code/data boundary. Client-only exports would create a second representation that could diverge from persisted lineage. All three were rejected for M11.
