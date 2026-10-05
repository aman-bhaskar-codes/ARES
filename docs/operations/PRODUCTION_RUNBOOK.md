# Production runbook

## 1. Preconditions

Use an immutable ARES image reference. Provide a PostgreSQL 18 + pgvector database, durable blob volume/object-store equivalent, HTTPS reverse proxy and an OIDC provider that supports Authorization Code + PKCE and JWKS discovery.

Never use the migration/admin database credential in the API or worker.

## 2. Provision concrete database login roles

Create two secret-managed LOGIN roles outside the repository, then make them members of the checked-in privilege groups:

```sql
CREATE ROLE ares_api_login LOGIN PASSWORD '<secret>';
GRANT ares_api TO ares_api_login;

CREATE ROLE ares_worker_login LOGIN PASSWORD '<secret>';
GRANT ares_worker TO ares_worker_login;
```

Run migrations as a separate privileged migration/admin identity. Then run `infra/postgres/bootstrap_roles.sql` as that same controlled admin identity. Verify:

```sql
SELECT rolname, rolsuper, rolbypassrls
FROM pg_roles
WHERE rolname IN ('ares_api', 'ares_worker', 'ares_api_login', 'ares_worker_login');
```

The API privilege group must have `rolbypassrls=false`. The worker privilege group is the only application group that intentionally bypasses RLS.

## 3. Validate configuration

```bash
cp .env.production.example .env.production
# Fill real secrets using your secret manager; do not commit this file.
PYTHONPATH=backend/src python scripts/production_doctor.py --env-file .env.production
```

The doctor never prints provider/database credentials.

## 4. Compose contract

Set:

```bash
export ARES_IMAGE='registry.example/ares@sha256:<immutable-digest>'
export MIGRATION_DATABASE_URL='postgresql+psycopg://...'
export POSTGRES_ADMIN_USER='...'
export POSTGRES_ADMIN_PASSWORD='...'
export ARES_ENV_FILE="$PWD/.env.production"
```

Validate before changing anything:

```bash
docker compose -f infra/production/compose.yaml config --quiet
```

Then start:

```bash
docker compose -f infra/production/compose.yaml up -d postgres searxng
docker compose -f infra/production/compose.yaml run --rm migrate
docker compose -f infra/production/compose.yaml run --rm provision-db-roles
docker compose -f infra/production/compose.yaml up -d worker api
```

## 5. Health contract

- `/health/live`: process is alive; downstream failure does not automatically fail liveness.
- `/health/ready`: database reachable, expected schema installed, live-mode configuration valid, and—when configured—at least one non-stale active worker exists.
- worker container health: fresh local worker-health marker written by the presence loop.

Do not send user traffic merely because the container is running; use readiness.

## 6. Rollout

1. Back up DB + blobs.
2. Build/test an immutable image from one source revision.
3. Apply **expand-compatible** migrations first.
4. Provision/review role grants.
5. Start one bounded worker/API cohort.
6. Observe request failures, queue age, worker active/draining/stale counts, provider rejections, run completion and citation/evidence invariants.
7. Increase traffic only after a meaningful observation window.

A healthy Deployment/container is not proof research correctness; keep the offline evaluation and live smoke separate from infrastructure health.

## 7. Shutdown / drain

Workers receive SIGTERM, publish `draining`, stop new leases, finish accepted work within the platform grace period, close providers and flush telemetry. If the grace period expires, durable lease fencing permits another worker to reclaim later without accepting stale results.

## 8. Incident distinctions

Operators should be able to distinguish:

- admission 429 vs provider rejection;
- queue wait vs active research latency;
- user cancellation vs worker/provider failure;
- stale worker vs process crash;
- missing telemetry vs no activity;
- tenant authorization 404/403 vs nonexistent data.

Never place prompts, evidence passages, cookies, Authorization headers or provider tokens in telemetry labels/log fields.

## M11 / V2 release checks

Before enabling `VISUALIZATIONS_ENABLED=true` in a production profile:

1. migrate to `0012` and confirm `/api/v1/system` reports visualization `ready=true`;
2. run PostgreSQL target-role tests, including M11 visualization-table RLS and API read-only grants;
3. execute a fresh root `pnpm install --frozen-lockfile`, frontend typecheck, Vitest and production build;
4. run the Chromium/Firefox/WebKit deep-link/accessibility smoke plus manual keyboard/screen-reader review;
5. generate the CycloneDX SBOM and run the dependency-review/security gates;
6. rehearse backup/restore and M06→M11 migration on disposable copies;
7. retain the independently authored held-out evaluation and external tester notes separately from development regression output.

A visualization failure is an optional-capability degradation, not a reason to discard an otherwise completed research answer. Disable the feature flag first during rollback; keep schema `0012` and immutable lineage records.
