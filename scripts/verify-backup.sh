#!/usr/bin/env bash
set -euo pipefail

target="${1:?usage: verify-backup.sh BACKUP_DIRECTORY}"
test -s "${target}/database.dump"
test -s "${target}/storage.tar.gz"
tar -tzf "${target}/storage.tar.gz" >/dev/null

if test -f "${target}/SHA256SUMS"; then
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "${target}" && sha256sum --check SHA256SUMS)
  else
    (cd "${target}" && shasum -a 256 --check SHA256SUMS)
  fi
fi

echo "Backup verified: ${target}"
