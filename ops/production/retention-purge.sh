#!/usr/bin/env sh
set -eu

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 /absolute/path/.env.production /absolute/path/verified-backup-manifest.json [--confirm]" >&2
  exit 2
fi
ENV_FILE=$1
BACKUP_MANIFEST=$2
MODE=${3:-}
COMPOSE_FILE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/production.compose.yaml

case "$ENV_FILE:$BACKUP_MANIFEST" in
  /*:/*) ;;
  *) echo "Both paths must be absolute" >&2; exit 2 ;;
esac
test -f "$ENV_FILE"
test -f "$BACKUP_MANIFEST"
BACKUP_DIR=$(dirname -- "$BACKUP_MANIFEST")
test -f "$BACKUP_DIR/SHA256SUMS"
grep -q '"maintenance_mode":true' "$BACKUP_MANIFEST"
(cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS)

echo "Expired-record dry run:"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile maintenance run --rm retention-dry-run

if [ "$MODE" != "--confirm" ]; then
  echo "Dry run only. Re-run with --confirm after reviewing counts and backup receipt."
  exit 0
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile maintenance run --rm \
  retention-dry-run python -m app.purge_chat_retention --confirm PURGE_EXPIRED_CHAT_RETENTION
echo "Retention purge completed and recorded in app.audit_logs."
