# Architecture

The API owns authentication, workspace authorization, admission, idempotency and read/export endpoints. The worker leases durable jobs and advances a bounded sequence: planning, discovery, reading, retrieval, synthesis and claim checking. Run status and events are persisted; the UI renders snapshots and reconnectable event streams.

Discovery tracks can run concurrently, but source failures remain separate from empty successful searches. Retrieval chooses passages before the writer sees them. A configured writer is chosen per run; no implicit paid-model fallback is permitted. Citation indexes resolve only to admitted evidence for that run.

PostgreSQL is the production store. pgvector supplies optional exact vector retrieval and PostgreSQL lexical search supplies text candidates. SQLite supports demo/local development with different scaling properties. Blob storage is content addressed and path confined. Large parser/media work is bounded and optional.

## Invariants

- Authorize at each workspace resource boundary, not only after generation.
- Treat sources as data, never instructions granting tool access.
- Preserve idempotency and lease fencing during retry/recovery.
- Recheck sessions and workspace identity during event streams.
- Distinguish absent evidence, discovery outage and synthesis outage.
- Require migrations and secure startup configuration before production readiness.

## Decisions

1. Keep a staged durable pipeline instead of adding agent orchestration without a measured need.
2. Keep model-specific transport separate from shared grounded-output parsing.
3. Preserve public API contracts while isolating router ownership and dependency boundaries.
4. Use offline labeled regression checks for development and separately report externally validated quality.
