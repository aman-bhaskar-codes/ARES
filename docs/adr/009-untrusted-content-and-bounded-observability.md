# ADR 009 — Remote content remains untrusted; detection is observability, not authority

**Status:** accepted

## Context

ARES intentionally retrieves arbitrary public content. A remote page can contain instructions aimed at the language model, encoded text, fake role delimiters, or requests to invoke tools or expose secrets. Regex or classifier detection cannot establish that content is safe.

Telemetry itself can also become a failure mode if exporters block request paths, logs contain secrets, or high-cardinality fields grow without bound.

## Decision

- Every retrieved document is untrusted regardless of detector output.
- The synthesis model receives a privileged `system_instruction` separately from a JSON data envelope containing the user question and evidence.
- Gemini interaction storage is disabled (`store=False`) for synthesis calls.
- No model-side network/filesystem/shell tools are exposed by the synthesis adapter.
- `RemoteContentRiskScanner` records bounded categories/scores for evaluation and diagnostics only; it never grants authority.
- Structured logs contain stable event names and bounded metadata, not query/evidence bodies, credentials, or headers.
- Request IDs are accepted only from a restricted character set/length or replaced with a generated UUID.
- Run-stage telemetry persists bounded timing events. If the OpenTelemetry API is present/configured, equivalent spans are emitted; tracing is optional and does not own correctness.
- Telemetry failures must not fail a research run.

## Consequences

Security does not depend on pattern matching remote prose. Operators still get visibility into instruction-like/obfuscated source content without creating a false “trusted source” state. A production deployment may add an OTLP SDK/exporter later without changing the application telemetry contract.
