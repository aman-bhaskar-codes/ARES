# Rollout and rollback contract

ARES treats code rollout, data migration and external provider effects as separate state machines.

## Expand first

Migrations must remain readable by the currently deployed version during a rolling update wherever possible. M6 migration `0006` adds identity/workspace/session/audit/worker-presence tables and tenant columns before relying on them.

## Rollback limits

Rolling back an image does not undo:

- rows written under a newer schema;
- OIDC sessions or audit events;
- external provider calls/quota consumption;
- uploaded blobs;
- migration/role changes.

Before rollback, confirm the older code can read every representation written by the new cohort. If not, prefer forward repair or traffic quarantine.

## Required release evidence

Keep the source revision, image digest, schema revision, configuration generation, migration logs, CI results, evaluation report, deployment cohort/time window and the operator decision to expand/abort/repair. A screenshot of a green dashboard is not enough evidence by itself.

## M11 visualization rollout

Roll out `0012` before application code that requires it. Keep `VISUALIZATIONS_ENABLED=false` until the migration, worker and API readiness checks pass, then enable for a small operator/test workspace before broader use. Compare API error rate, visualization-ready/failed events, frontend chunk-load failures, CSV export failures and browser responsiveness against the pre-enable baseline.

Rollback is code/feature-level: set `VISUALIZATIONS_ENABLED=false` and preserve schema/data. Do not downgrade or delete `0012` tables during an incident. Existing answer, evidence, table, PDF and media flows remain the compatibility path. A later cleanup migration may remove visual data only after backup, retention policy and old-reader compatibility are explicitly proven.
