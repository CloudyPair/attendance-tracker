#!/usr/bin/env bash
set -euo pipefail
umask 077
FLAG_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FLAG_ROOT"
FLAG_BACKUP="backups/$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$FLAG_BACKUP"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$FLAG_BACKUP/database.dump"
tar -czf "$FLAG_BACKUP/media.tar.gz" -C deploy/state media
cp .env "$FLAG_BACKUP/server.env"
printf 'Backup saved: %s\n' "$FLAG_BACKUP"
