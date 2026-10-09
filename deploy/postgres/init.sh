#!/bin/sh
# First start of the database volume: an owner login (runs migrations) and the application login (no DDL,
# cannot rewrite the audit log or case history).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE mrm_owner LOGIN PASSWORD '${MRM_OWNER_PASSWORD}';
CREATE ROLE mrm_app LOGIN PASSWORD '${MRM_APP_PASSWORD}';
ALTER DATABASE "$POSTGRES_DB" OWNER TO mrm_owner;
GRANT ALL ON SCHEMA public TO mrm_owner;
ALTER SCHEMA public OWNER TO mrm_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO mrm_app;
SQL
