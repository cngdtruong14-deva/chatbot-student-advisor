#!/usr/bin/env sh
set -eu

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 /absolute/path/.env.production /absolute/backup/root BACKUP_ID" >&2
  exit 2
fi
ENV_FILE=$1
BACKUP_ROOT=$2
BACKUP_ID=$3
COMPOSE_FILE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/production.compose.yaml

case "$ENV_FILE:$BACKUP_ROOT" in
  /*:/*) ;;
  *) echo "Environment and backup paths must be absolute" >&2; exit 2 ;;
esac
case "$BACKUP_ID" in
  *[!A-Za-z0-9._-]*|'') echo "Unsafe backup ID" >&2; exit 2 ;;
esac
test -f "$ENV_FILE"
OUT="$BACKUP_ROOT/$BACKUP_ID"
if [ -e "$OUT" ]; then
  echo "Backup target already exists; backups are immutable" >&2
  exit 2
fi
mkdir -m 700 -p "$OUT"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" stop web api
cleanup() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d api web >/dev/null || true
}
trap cleanup EXIT INT TERM

DB_CONTAINER=$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps -q db)
test -n "$DB_CONTAINER"
TMP_DUMP="/tmp/$BACKUP_ID.dump"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db \
  pg_dump -U advisor_admin -d student_advisor -Fc -f "$TMP_DUMP"
docker cp "$DB_CONTAINER:$TMP_DUMP" "$OUT/database.dump"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db rm -f "$TMP_DUMP"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm --no-deps \
  api tar -czf - -C /vectorstore . > "$OUT/vectorstore.tar.gz"

ARTIFACTS_PATH=$(sed -n 's/^ARTIFACTS_PATH=//p' "$ENV_FILE" | tail -n 1)
case "$ARTIFACTS_PATH" in /*) ;; *) echo "ARTIFACTS_PATH must be absolute" >&2; exit 2;; esac
tar -czf "$OUT/artifacts.tar.gz" -C "$ARTIFACTS_PATH" .

(cd "$OUT" && sha256sum database.dump vectorstore.tar.gz artifacts.tar.gz > SHA256SUMS)
cat > "$OUT/backup_manifest.json" <<EOF
{"schema":"student-advisor-backup/1.0","backup_id":"$BACKUP_ID","created_at":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","maintenance_mode":true,"checksums":"SHA256SUMS"}
EOF
chmod 600 "$OUT"/*
trap - EXIT INT TERM
cleanup
echo "Backup complete: $OUT"
echo "Encrypt and copy this directory off-host before treating the backup as durable."
