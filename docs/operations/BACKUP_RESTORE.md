# Backup and restore

ARES durable state consists of PostgreSQL plus blob storage. A database-only backup is incomplete because PDF/raw-document bytes and generated artifacts live in the blob store.

## Backup

Use a dedicated PostgreSQL backup/read role where possible:

```bash
export BACKUP_DATABASE_URL='postgresql://...'
export BLOB_ROOT='/srv/ares/blobs'
export BACKUP_DIR='/secure/backups/ares-YYYYMMDDTHHMMSSZ'
./scripts/backup_production.sh
```

The script creates:

- `postgres.dump` — custom-format pg_dump without owner/ACL recreation;
- `blobs.tar.gz` — content-addressed blob tree;
- `SHA256SUMS` — integrity manifest.

Store backups encrypted with access controls outside the application host. Test restore, not only backup creation.

## Restore drill

Restore only to an explicitly selected destination. The helper refuses to run without `CONFIRM_RESTORE=YES`:

```bash
export RESTORE_DATABASE_URL='postgresql://...'
export BLOB_ROOT='/srv/ares/blobs'
export BACKUP_DIR='/secure/backups/<backup>'
export CONFIRM_RESTORE=YES
./scripts/restore_production.sh
```

After restore:

1. run Alembic `upgrade head`;
2. run database role provisioning;
3. run production doctor;
4. verify pgvector extension and RLS tests against the restored DB;
5. verify a known document hash and page-level citation;
6. verify one workspace cannot resolve another workspace's resource IDs;
7. admit traffic only after readiness and worker presence are healthy.

A restore into a new environment should use new OIDC/provider/application secrets. Backups do not contain plaintext provider access tokens, because those are never persisted.
