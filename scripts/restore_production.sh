#!/usr/bin/env sh
set -eu

: "${RESTORE_DATABASE_URL:?set RESTORE_DATABASE_URL to the destination PostgreSQL URL}"
: "${BLOB_ROOT:?set BLOB_ROOT to the destination ARES blob directory}"
: "${BACKUP_DIR:?set BACKUP_DIR to a backup directory created by backup_production.sh}"
: "${CONFIRM_RESTORE:?set CONFIRM_RESTORE=YES after verifying the destination is safe to replace}"
[ "$CONFIRM_RESTORE" = "YES" ] || { echo "CONFIRM_RESTORE must equal YES" >&2; exit 2; }

command -v pg_restore >/dev/null 2>&1 || { echo "pg_restore is required" >&2; exit 2; }
command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum is required" >&2; exit 2; }
(
  cd "$BACKUP_DIR"
  sha256sum -c SHA256SUMS
)

pg_restore --clean --if-exists --no-owner --no-acl --dbname "$RESTORE_DATABASE_URL" "$BACKUP_DIR/postgres.dump"
mkdir -p "$BLOB_ROOT"
tar -C "$BLOB_ROOT" -xzf "$BACKUP_DIR/blobs.tar.gz"
printf '%s\n' "Restore completed. Run migrations, production doctor, readiness, and a tenant-isolation smoke before admitting traffic."
