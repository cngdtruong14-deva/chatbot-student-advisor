#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=migrator_password="$MIGRATOR_DB_PASSWORD" --set=app_password="$APP_DB_PASSWORD" <<'SQL'
CREATE ROLE advisor_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'migrator_password';
CREATE ROLE advisor_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
REVOKE ALL ON DATABASE student_advisor FROM PUBLIC;
GRANT CONNECT ON DATABASE student_advisor TO advisor_migrator, advisor_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA app AUTHORIZATION advisor_migrator;
GRANT USAGE ON SCHEMA app TO advisor_app;
ALTER DEFAULT PRIVILEGES FOR ROLE advisor_migrator IN SCHEMA app
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO advisor_app;
ALTER DEFAULT PRIVILEGES FOR ROLE advisor_migrator IN SCHEMA app
  GRANT USAGE, SELECT ON SEQUENCES TO advisor_app;
ALTER ROLE advisor_migrator IN DATABASE student_advisor SET search_path = app, pg_catalog;
ALTER ROLE advisor_app IN DATABASE student_advisor SET search_path = app, pg_catalog;
SQL
