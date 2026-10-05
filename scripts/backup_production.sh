#!/usr/bin/env sh
set -eu

: "${BACKUP_DATABASE_URL:?set BACKUP_DATABASE_URL to a privileged read-only/backup PostgreSQL URL}"
: "${BLOB_ROOT:?set BLOB_ROOT to the ARES blob directory}"
BACKUP_DIR="${BACKUP_DIR:-./backups/ares-$(date -u +%Y%m%dT%H%M%SZ)}"

command -v pg_dump >/dev/null 2>&1 || { echo "pg_dump is required" >&2; exit 2; }
command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum is required" >&2; exit 2; }
mkdir -p "$BACKUP_DIR"

pg_dump --format=custom --no-owner --no-acl --file "$BACKUP_DIR/postgres.dump" "$BACKUP_DATABASE_URL"
if [ -d "$BLOB_ROOT" ]; then
  tar -C "$BLOB_ROOT" -czf "$BACKUP_DIR/blobs.tar.gz" .
else
  tar -czf "$BACKUP_DIR/blobs.tar.gz" --files-from /dev/null
fi
(
  cd "$BACKUP_DIR"
  sha256sum postgres.dump blobs.tar.gz > SHA256SUMS
)
printf '%s\n' "Backup written to $BACKUP_DIR" "Verify: (cd '$BACKUP_DIR' && sha256sum -c SHA256SUMS)"
