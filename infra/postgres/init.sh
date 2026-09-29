#!/bin/bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
  CREATE ROLE dataforge LOGIN PASSWORD '${DATAFORGE_APP_PASSWORD}';
  CREATE ROLE airflow LOGIN PASSWORD '${AIRFLOW_DB_PASSWORD}';
  CREATE ROLE metabase LOGIN PASSWORD '${METABASE_DB_PASSWORD}';
  CREATE ROLE publisher LOGIN PASSWORD '${PUBLISHER_PASSWORD}';
  CREATE ROLE metabase_reader LOGIN PASSWORD '${METABASE_READER_PASSWORD}';

  CREATE DATABASE dataforge_app OWNER dataforge;
  CREATE DATABASE airflow OWNER airflow;
  CREATE DATABASE metabase OWNER metabase;
  CREATE DATABASE dataforge_warehouse OWNER publisher;

  REVOKE ALL ON DATABASE dataforge_warehouse FROM PUBLIC;
  GRANT CONNECT ON DATABASE dataforge_warehouse TO metabase_reader;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname dataforge_warehouse <<-SQL
  REVOKE CREATE ON SCHEMA public FROM PUBLIC;
  ALTER DEFAULT PRIVILEGES FOR ROLE publisher GRANT USAGE ON SCHEMAS TO metabase_reader;
  ALTER DEFAULT PRIVILEGES FOR ROLE publisher GRANT SELECT ON TABLES TO metabase_reader;
SQL
