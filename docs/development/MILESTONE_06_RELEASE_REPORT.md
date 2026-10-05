# Milestone 06 release report — multi-user release candidate

Date: 2026-10-03

## Scope frozen

Milestone 06 closes the multi-user/public-product source boundary without adding speculative research-provider breadth. It adds identity/session security, workspace authorization, PostgreSQL RLS, per-principal admission control, separated runtime DB roles, worker fleet lifecycle, production browser/container hardening, release operations and CI release gates.

## Material implementation completed

### Identity and authorization

- OIDC Authorization Code + PKCE S256;
- one-time server-side state and nonce;
- JWKS ID-token signature validation and claim checks (`iss`, `aud`, `azp`, `exp`, `nbf`, bounded future `iat`, nonce, subject);
- HTTPS-only discovery endpoints under production HTTPS issuer;
- optional UserInfo subject binding;
- opaque hashed server-side sessions and independent CSRF token;
- logout/revocation, workspace switch and viewer/editor/owner enforcement;
- account/workspace/session-expiry flows in React.

### Tenant boundary

- migration `0006_multitenant_security` adds users, workspaces, memberships, sessions, OIDC state, audit events and worker instances;
- workspace/user ownership on top-level research resources;
- PostgreSQL `FORCE ROW LEVEL SECURITY` across research-bearing tables;
- transaction-local tenant context with explicit blank reset for pooled connections;
- API `NOBYPASSRLS` vs worker `BYPASSRLS` privilege groups;
- narrow global-capacity `SECURITY DEFINER` function;
- global/workspace/user active-run admission with advisory-lock serialization.

### Production lifecycle / edge

- aggregate worker registration, heartbeat, draining and local liveness marker;
- production readiness checks DB, required schema and optionally active worker;
- Trusted Host, HSTS/CSP/no-sniff/frame/referrer/permissions/cross-origin headers;
- bounded request bodies;
- non-root/read-only production images, dropped capabilities and `no-new-privileges`;
- internal PostgreSQL data network separated from provider egress network;
- explicit post-migration DB-role provisioning.

### Operations and release engineering

- production configuration doctor;
- empty and M5->M6 migration compatibility verifier;
- database/blob backup and guarded restore scripts;
- rollout/rollback runbook with migration/compatibility caveats;
- deterministic release archive + SHA-256;
- Dependabot, issue/PR templates and CI production-container/release gate.

## Validation observed in this environment

- backend: **83 passed, 6 skipped**;
- six skips are all PostgreSQL-only and require `ARES_TEST_POSTGRES_URL`;
- synthetic development evaluation suite: **gate passed** with no failures across routing, claim-support, retrieval and security-observability fixtures;
- migration verifier: **empty -> `0006`** and **`0005` -> `0006`** passed;
- production doctor: passed against a synthetic secure production configuration; optional OTLP/embedding configuration remained warnings only;
- Python compileall: passed;
- OpenAPI regenerated from current source;
- secret-shaped-material scan: passed;
- TypeScript production-source typecheck: passed against the pinned frontend type dependency snapshot.

## Not claimed as locally executed

The current sandbox does not provide a PostgreSQL/pgvector server, Docker daemon, live OIDC provider or a Linux-native frontend dependency reinstall. Therefore the following remain real CI/target-machine/live gates:

- provider-quota concurrency on PostgreSQL;
- active-run admission concurrency on PostgreSQL;
- exact pgvector ordering;
- production readiness + Trusted Host against PostgreSQL;
- direct RLS cross-tenant isolation;
- pooled-connection tenant reset on PostgreSQL;
- native Vitest/Vite production build after frozen pnpm install;
- Docker image build and production Compose runtime;
- live OIDC sign-in/logout/workspace flows;
- live SearXNG/Gemini/scholarly/software provider smoke tests;
- independent penetration test and independently authored held-out benchmark/evaluation.

## Release interpretation

M6 is **source-complete as a release candidate**, not proof of a deployed production service. A public deployment should be promoted only after the external gates above run in the operator's real environment and rollout/backup evidence is retained.
