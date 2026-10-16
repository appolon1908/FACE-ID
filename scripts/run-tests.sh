#!/usr/bin/env bash
# Runs the pytest suite inside the FACE-ID image against a dedicated faceid_test database.
# The suite refuses to run unless DATABASE_URL points at a *_test database; live data is never touched.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
TEST_DB="${FACEID_TEST_DB:-faceid_test}"
docker exec faceid-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tc "select 1 from pg_database where datname='$TEST_DB'" | grep -q 1 \
  || docker exec faceid-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "create database $TEST_DB"
IMAGE="$(docker inspect face-id-api --format '{{.Config.Image}}')"
docker run --rm --network face-id_default -v "$PWD":/src -w /src \
  -e DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${TEST_DB}" \
  -e PYTHONDONTWRITEBYTECODE=1 "$IMAGE" \
  sh -c "pip install -q -r requirements-dev.txt 2>/dev/null && python -m pytest -p no:cacheprovider -q tests $*"
