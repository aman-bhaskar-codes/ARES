# Milestone 06 — multi-user release-candidate boundary

M6 turns the M1–M5 research system into a deployable multi-user release candidate. It does **not** add a new research-provider feature merely for breadth; it closes identity, tenant isolation, admission control, process lifecycle, operations and release verification.

## Security / identity contract

- OAuth 2.0 / OpenID Connect Authorization Code flow with PKCE S256.
- One-time, expiring state plus nonce; return paths are same-origin relative paths only.
- ID Tokens are verified against provider JWKS and checked for signature, issuer, audience, authorized party, expiry, future `nbf`/`iat`, nonce and subject shape.
- UserInfo is optional; if used, its `sub` must match the already-validated ID Token subject.
- Provider access tokens are never persisted.
- Browser sessions use random opaque tokens stored server-side only as SHA-256 hashes. CSRF uses an independent double-submit token and same-origin mutation checks.
- Workspace roles are `viewer`, `editor`, `owner`; viewers cannot mutate research state.

## Tenant isolation

Research-bearing rows now carry `workspace_id`; top-level created resources also carry `created_by_user_id`. PostgreSQL `FORCE ROW LEVEL SECURITY` protects conversations, runs, documents, audit rows and their derived evidence/job/source/chunk/artifact rows.

The request `TenantSession` sets `app.workspace_id`/`app.user_id` transaction-locally on **every** PostgreSQL transaction. When no request principal exists the settings are explicitly blanked, preventing connection-pool reuse from inheriting a prior tenant.

Production database privilege groups are separated:

- `ares_api`: `NOBYPASSRLS`, public API/browser path.
- `ares_worker`: `BYPASSRLS`, durable cross-workspace queue/evidence worker only.
- migration/admin login: schema changes and role provisioning only; never used by API/worker.

The fleet-wide active-run count is exposed through one narrow `SECURITY DEFINER` aggregate; API code does not receive general cross-tenant read authority. Workspace and per-user admission counts remain ordinary RLS-scoped queries.

## Admission / quotas

A run is admitted only when all configured limits allow it:

- global active runs;
- active runs in the workspace;
- active runs created by the requesting user in that workspace.

PostgreSQL serializes admission with an advisory transaction lock. Rejection is HTTP 429 with `Retry-After`; idempotent replay is checked before capacity rejection.

## Production lifecycle

API:

1. validate security configuration before OIDC construction;
2. serve liveness independently from dependencies;
3. readiness checks database connectivity, production schema revision and optionally an active worker;
4. stop admission through the process supervisor/reverse proxy;
5. close OIDC HTTP client;
6. flush bounded telemetry;
7. dispose DB pools.

Worker:

1. registers fleet presence;
2. claims work only while active;
3. on SIGTERM/SIGINT publishes `draining` and stops new job admission;
4. lets an accepted run finish under durable lease fencing;
5. closes research providers;
6. flushes telemetry;
7. disposes DB pools and removes local health marker.

## Production container boundary

`Dockerfile` builds frontend + backend reproducibly from lockfiles, then runs as non-root UID/GID 10001. Production Compose uses read-only container filesystems, dropped Linux capabilities, `no-new-privileges`, bounded tmpfs and explicit stop-grace periods.

Networks are deliberately split:

- `data` is internal-only and carries PostgreSQL/service traffic;
- `egress` permits API/worker/SearXNG to reach public research providers.

PostgreSQL never joins the egress network.

## Public-edge expectations

ARES terminates TLS behind a reverse proxy/load balancer. Production validates one HTTPS origin for the browser and API. FastAPI additionally applies Trusted Host validation, HSTS, CSP, nosniff, frame denial, referrer/permissions/cross-origin policies and no-store auth responses.

Expensive research admission is database-backed. Volumetric anonymous abuse/rate limiting remains the responsibility of the reverse proxy/CDN/WAF because a per-process in-memory limiter would give false distributed guarantees.

## Verification gates

Local/sandbox gates:

```bash
PYTHONPATH=backend/src pytest backend/tests -q
PYTHONPATH=backend/src python evals/run_suite.py --suite all --decision-provider deterministic --retrieval-mode lexical
PYTHONPATH=backend/src python scripts/verify_migrations.py
PYTHONPATH=backend/src python -m compileall -q backend/src backend/tests scripts
PYTHONPATH=backend/src python scripts/export_openapi.py
python scripts/check_secrets.py
```

PostgreSQL release gates:

```bash
export ARES_TEST_POSTGRES_URL='postgresql+psycopg://...'
make test-postgres
```

Those tests cover provider-quota concurrency, active-run admission, pgvector exact ordering, direct RLS isolation and pooled-connection tenant-context reset.

Frontend/production-image gates remain:

```bash
pnpm install --frozen-lockfile
pnpm --filter @ares/web typecheck
pnpm --filter @ares/web test
pnpm --filter @ares/web build
docker build -t ares:rc .
```

## Explicit non-claims

M6 does not claim production uptime, provider compatibility with an unknown user account, independent penetration testing, independent held-out benchmark superiority, browser-rendered crawling, or OCR execution. Those require deployment-specific evidence rather than source-code assertions.
