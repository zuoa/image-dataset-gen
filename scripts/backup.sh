#!/usr/bin/env bash
set -euo pipefail

backup_root="${BACKUP_ROOT:-./backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="${backup_root}/${timestamp}"
mkdir -p "${target}"

docker compose exec -T postgres pg_dump \
  --username "${POSTGRES_USER:-dataset_gen}" \
  --dbname "${POSTGRES_DB:-dataset_gen}" \
  --format custom \
  --no-owner \
  --no-acl > "${target}/database.dump"

docker compose exec -T backend tar -C /app/storage -czf - . > "${target}/storage.tar.gz"

if command -v sha256sum >/dev/null 2>&1; then
  (cd "${target}" && sha256sum database.dump storage.tar.gz > SHA256SUMS)
else
  (cd "${target}" && shasum -a 256 database.dump storage.tar.gz > SHA256SUMS)
fi

"$(dirname "$0")/verify-backup.sh" "${target}"
echo "Backup complete: ${target}"
