# ADR 001 — Modular monolith with API/worker split

**Status:** accepted for V1 foundation — 2026-10-02

## Decision

Use one Python application package with separately executed FastAPI and worker processes. PostgreSQL is the live authoritative store for runs, jobs, ordered events, sources, evidence, claims and provider usage. Jobs use leases, heartbeats and lease-token fencing. SQLite is allowed only as a self-bootstrapping keyless demo/test convenience.

## Why

This gives ARES durable restart/replay behavior without Redis, Kafka, Temporal or a microservice network. Domain/application code stays independent from the HTTP and provider SDK boundaries. The worker performs external calls outside row-lock transactions.

## Revisit when

Measured queue contention, multi-host workers, long-lived workflow complexity, or a stronger isolation requirement makes the current lease model insufficient.
