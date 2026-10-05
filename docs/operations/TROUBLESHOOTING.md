# Troubleshooting

## Visualizations are enabled but unavailable

Check `/api/v1/system` and confirm `visualizations.enabled=true` **and** `visualizations.ready=true`. Readiness requires migration `0012_visual_artifacts`; a flag alone is insufficient. Run the migration verifier and inspect database connectivity before changing frontend code.

## A completed run has no visual artifacts

Not every run produces every visualization. Comparison needs stored facets; numeric charts require at least two directly cited normalized table-cell values in one comparable unit; publication timelines require known publication dates. Inspect `visualization.ready` / `visualization.failed` durable events and keep the normal answer/evidence path usable.

## CSV download fails

The server intentionally rejects unsupported visualization kinds and revalidates authorization by run. Confirm the artifact belongs to the current workspace, `allow_download_csv` is true and the API storage readiness check passes. Do not recreate the export client-side as a workaround.

## Deep research links return 404

The production API must serve the built web directory through the SPA fallback. `/api/*` routes never fall back to `index.html`. Verify `WEB_DIST_DIR`, the built `index.html`, reverse-proxy routing and auth/session behavior.

## Frontend build warns about large chunks

ECharts, React Flow and PDF.js are lazy-loaded, but their feature chunks are still substantial. Treat the warning as a measurable performance follow-up. Do not move those packages back into the initial search bundle merely to silence the report; use bundle analysis and real interaction metrics first.

## Frozen pnpm install fails

Run `python scripts/verify_m11_release.py --skip-archive` first. If it reports a lock importer mismatch, regenerate with the repository-pinned pnpm version and commit `pnpm-lock.yaml`. Do not use `--no-frozen-lockfile` in release CI.

## PostgreSQL/RLS gate is unavailable locally

Do not substitute SQLite as isolation proof. Configure a disposable pgvector database with the intended API/worker roles and run `make test-postgres`. Retain the target-environment result in the release evidence.
