# ADR 010 — OIDC sessions, PostgreSQL RLS and separated database roles

## Decision

ARES uses OIDC Authorization Code + PKCE for browser identity, server-side opaque sessions for application continuity, explicit workspace membership for authorization, and PostgreSQL FORCE RLS as a second tenant-isolation boundary for research-bearing rows.

The public API uses a `NOBYPASSRLS` privilege group. The durable worker uses a distinct `BYPASSRLS` group because it must lease and persist jobs across workspaces. The migration/admin credential is never used by either runtime service.

## Why

Application filters alone are vulnerable to missed predicates. Giving the worker's cross-tenant authority to the API would defeat RLS. Persisting provider access tokens would expand the credential blast radius. This design keeps browser identity, API authorization and worker queue authority separate.

## Consequences

- every API transaction binds tenant identity transaction-locally and blanks it when no principal exists;
- run admission uses a narrow SECURITY DEFINER global-count function instead of general cross-tenant API reads;
- operations must provision and verify separate database login roles;
- PostgreSQL integration tests are release gates, because SQLite cannot prove RLS behavior;
- production browser and API origin are intentionally the same origin for cookies/CSRF and simpler CSP.
