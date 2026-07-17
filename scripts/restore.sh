#!/usr/bin/env bash
set -euo pipefail

target="${1:?usage: RESTORE_CONFIRM=dataset-gen scripts/restore.sh BACKUP_DIRECTORY}"
if test "${RESTORE_CONFIRM:-}" != "dataset-gen"; then
  echo "Refusing destructive restore. Set RESTORE_CONFIRM=dataset-gen." >&2
  exit 2
fi

"$(dirname "$0")/verify-backup.sh" "${target}"
docker compose stop frontend backend outbox-dispatcher generation-worker media-worker maintenance

docker compose exec -T postgres dropdb \
  --username "${POSTGRES_USER:-dataset_gen}" \
  --if-exists "${POSTGRES_DB:-dataset_gen}"
docker compose exec -T postgres createdb \
  --username "${POSTGRES_USER:-dataset_gen}" \
  "${POSTGRES_DB:-dataset_gen}"
docker compose exec -T postgres pg_restore \
  --username "${POSTGRES_USER:-dataset_gen}" \
  --dbname "${POSTGRES_DB:-dataset_gen}" \
  --no-owner \
  --no-acl < "${target}/database.dump"

docker compose run --rm -T backend sh -c 'find /app/storage -mindepth 1 -delete; tar -C /app/storage -xzf -' \
  < "${target}/storage.tar.gz"
docker compose run --rm migrate
docker compose up -d
echo "Restore complete: ${target}"
