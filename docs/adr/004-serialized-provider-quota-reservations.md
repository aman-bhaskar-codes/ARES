# ADR 004 — Serialize provider quota reservations in PostgreSQL

**Status:** accepted for V1 foundation — 2026-10-03

## Context

ARES strict-free mode must not allow concurrent workers to oversubscribe the configured provider allowance. A read-then-insert implementation can race: two transactions can both read the same request/token totals and both decide that capacity remains.

An in-process mutex is insufficient because ARES intentionally supports multiple worker processes and may later run workers on separate hosts.

## Decision

Create one `provider_quota_locks` row per `(provider, model)` and update that row at the start of every quota reservation transaction. PostgreSQL holds the resulting row lock until commit. Usage-window reads and the new reservation insert happen after the lock is acquired and inside the same transaction.

SQLite keeps the same schema for the keyless demo/test path; its write serialization is sufficient for the non-production local mode. PostgreSQL concurrency behavior is covered by an explicit integration test.

## Consequences

- Quota admission is serialized per provider/model, not globally.
- Different models/providers can reserve independently.
- The lock table is tiny and contains no secrets.
- Provider quotas remain conservative local ceilings; ARES still cannot guarantee provider-side billing behavior if a user enables billing outside ARES.
- The reservation table may need compaction/aggregation if usage history grows materially.

## Alternatives rejected

- **Python mutex:** process-local only; unsafe with multiple workers.
- **Serializable isolation for every worker transaction:** broader contention and complexity than needed.
- **Redis distributed lock:** adds infrastructure before there is a measured need.
- **Advisory locks only:** workable on PostgreSQL but less portable and less explicit in schema/migrations.

## Revisit when

ARES adds distributed quota authorities, multiple database regions, provider-reported token reconciliation, or a dedicated billing/usage service.
