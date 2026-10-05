# Milestone 01 — Reproducible local foundation

**Goal:** a fresh checkout can run the keyless recorded demo, and a developer with Docker can validate the production PostgreSQL migration/concurrency path before enabling any external AI provider.

## What this milestone implements

- Demo-first SQLite configuration with no API key required.
- PostgreSQL migration path through Alembic revision `0002`.
- Durable job leases and stale-worker fencing.
- Atomic Gemini quota reservation across worker processes using a provider/model lock row.
- PostgreSQL concurrency test for the quota lock.
- Pinned GitHub Actions for checkout, Python, Node and uv.
- CI PostgreSQL service that applies migrations before backend tests.
- `scripts/doctor.py` for local configuration checks without printing secrets or calling providers.

## 1. Clone and enter the repository

```bash
git clone <YOUR_REPOSITORY_URL> ares-research
cd ares-research
```

Use Python 3.12+ and Node 22.16+ for this branch.

## 2. Configure the keyless demo

```bash
cp .env.example .env
python scripts/doctor.py
```

`.env.example` intentionally points at SQLite:

```env
ARES_MODE=demo
DATABASE_URL=sqlite+pysqlite:///./.data/ares-dev.sqlite3
```

Do not put a Gemini key in the browser or frontend environment.

## 3. Install backend dependencies

With network access:

```bash
uv lock --project backend
uv sync --project backend --extra dev --frozen
```

Commit `backend/uv.lock` once generated. Until the lockfile exists, use this only for initial bootstrap:

```bash
uv sync --project backend --extra dev
```

## 4. Run backend validation

```bash
make doctor
make test
make test-compile
make openapi
git diff --check
```

Expected local result before PostgreSQL is configured:

```text
19 passed, 1 skipped
```

The skipped test is intentionally PostgreSQL-only.

## 5. Run the keyless API and worker

Terminal A:

```bash
uv run --project backend uvicorn ares.api.app:app --app-dir backend/src --reload
```

Terminal B:

```bash
PYTHONPATH=backend/src uv run --project backend python -m ares.worker.main
```

Check readiness:

```bash
curl http://127.0.0.1:8000/health/ready
```

Expected:

```json
{"status":"ready","mode":"demo"}
```

## 6. Validate PostgreSQL manually

Prerequisite: Docker Engine or a compatible Compose implementation.

Start PostgreSQL:

```bash
make infra
```

Use the PostgreSQL URL only for this validation step:

```bash
export DATABASE_URL='postgresql+psycopg://ares:ares@127.0.0.1:5432/ares'
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend alembic -c backend/alembic.ini current
```

Expected migration head:

```text
0002 (head)
```

Run the production concurrency test:

```bash
export ARES_TEST_POSTGRES_URL="$DATABASE_URL"
PYTHONPATH=backend/src uv run --project backend pytest \
  backend/tests/integration/test_postgres_concurrency.py -q
```

Expected:

```text
1 passed
```

This test starts two concurrent quota reservations with `RPM=1`. Exactly one must be admitted and one rejected. If both are admitted, strict-free quota enforcement is not safe to ship.

## 7. Install and verify the web app

This sandbox cannot resolve the npm registry, so these commands must be run on a network-enabled machine:

```bash
corepack enable
corepack prepare pnpm@12.8.1 --activate
pnpm install
pnpm --filter @ares/web typecheck
pnpm --filter @ares/web test
pnpm --filter @ares/web build
```

Commit the generated `pnpm-lock.yaml` only after those commands succeed. Do not hand-write or fabricate the lockfile.

Run the web UI:

```bash
pnpm --filter @ares/web dev
```

Open `http://127.0.0.1:5173`.

## 8. Acceptance checklist

Milestone 01 is complete only when all of these are true:

- [ ] `make doctor` passes.
- [ ] backend tests pass.
- [ ] Alembic reports `0002 (head)` on PostgreSQL.
- [ ] PostgreSQL quota concurrency test passes.
- [ ] API and worker can complete a recorded demo run.
- [ ] frontend typecheck/tests/build pass.
- [ ] `backend/uv.lock` and `pnpm-lock.yaml` are committed.
- [ ] no API keys are present in Git history or the frontend bundle.

## Why the quota-lock table exists

A naive implementation does `SUM(provider_usage)` and then inserts a reservation. With two workers, both transactions can read the same remaining allowance before either inserts, allowing a supposedly strict-free project to exceed its configured limit.

ARES now serializes quota reservations by `(provider, model)` using `provider_quota_locks`. PostgreSQL obtains a row-level write lock for that provider/model until the transaction commits. The usage sums and the new reservation therefore occur inside one serialized critical section.

This is deliberately implemented in the persistence layer rather than with a Python mutex because multiple worker processes must share the same safety boundary.
