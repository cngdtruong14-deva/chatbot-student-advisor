#!/bin/sh
set -eu

SOURCE_DB="student_advisor"
RESTORE_DB="student_advisor_restore_v4_20260923"
BACKUP_DIR="/artifacts/backups/postgres-v4-20260923"
DUMP_PATH="$BACKUP_DIR/student_advisor.dump"
RECEIPT_PATH="$BACKUP_DIR/restore_receipt.json"

mkdir -p "$BACKUP_DIR"

if psql --host "$DB_HOST" --username "$DB_USER" --dbname postgres --tuples-only --no-align \
  --command "SELECT 1 FROM pg_database WHERE datname='$RESTORE_DB'" | grep -q '^1$'; then
  echo "ISOLATED_RESTORE_DATABASE_ALREADY_EXISTS" >&2
  exit 1
fi

pg_dump --host "$DB_HOST" --username "$DB_USER" --dbname "$SOURCE_DB" \
  --format custom --no-owner --no-acl --file "$DUMP_PATH"

createdb --host "$DB_HOST" --username "$DB_USER" "$RESTORE_DB"
pg_restore --host "$DB_HOST" --username "$DB_USER" --dbname "$RESTORE_DB" \
  --exit-on-error --no-owner --no-acl "$DUMP_PATH"

USERS="$(psql --host "$DB_HOST" --username "$DB_USER" --dbname "$RESTORE_DB" --tuples-only --no-align --command 'SELECT count(*) FROM app.users')"
VERSIONS="$(psql --host "$DB_HOST" --username "$DB_USER" --dbname "$RESTORE_DB" --tuples-only --no-align --command "SELECT count(*) FROM app.document_versions WHERE scope_key='utt_corpus'")"
CHUNKS="$(psql --host "$DB_HOST" --username "$DB_USER" --dbname "$RESTORE_DB" --tuples-only --no-align --command "SELECT count(*) FROM app.chunks c JOIN app.document_versions v ON v.id=c.version_id WHERE v.scope_key='utt_corpus'")"
ACTIVE="$(psql --host "$DB_HOST" --username "$DB_USER" --dbname "$RESTORE_DB" --tuples-only --no-align --command "SELECT id FROM app.corpus_releases WHERE corpus_scope='utt_corpus' AND status='active'")"
DUMP_SHA256="$(sha256sum "$DUMP_PATH" | awk '{print $1}')"
DUMP_BYTES="$(wc -c < "$DUMP_PATH" | tr -d ' ')"

if [ "$USERS" != "1" ] || [ "$VERSIONS" != "44" ] || [ "$CHUNKS" != "514" ] || [ "$ACTIVE" != "UTT-CORPUS-2026-V2" ]; then
  echo "ISOLATED_RESTORE_COUNTS_MISMATCH users=$USERS versions=$VERSIONS chunks=$CHUNKS active=$ACTIVE" >&2
  exit 1
fi

printf '{"protocol":"postgres_restore_drill_v1","source_database":"%s","restore_database":"%s","dump_sha256":"%s","dump_bytes":%s,"users":%s,"utt_versions":%s,"utt_chunks":%s,"active_release":"%s","status":"PASS"}\n' \
  "$SOURCE_DB" "$RESTORE_DB" "$DUMP_SHA256" "$DUMP_BYTES" "$USERS" "$VERSIONS" "$CHUNKS" "$ACTIVE" > "$RECEIPT_PATH"

cat "$RECEIPT_PATH"
