#!/bin/sh
# Esegue i test su un Postgres usa e getta (container). Default: solo i test marcati postgres.
#   deploy/test-postgres.sh              -> pytest -m postgres
#   deploy/test-postgres.sh -q           -> tutta la suite su Postgres
set -e
cd "$(dirname "$0")/.."
NOME="adabox_hub_test_pg_$$"
docker run -d --rm --name "$NOME" -e POSTGRES_PASSWORD=test -p 127.0.0.1::5432 postgres:16-alpine >/dev/null
trap 'docker stop "$NOME" >/dev/null' EXIT INT TERM
PORTA=$(docker port "$NOME" 5432/tcp | head -1 | sed 's/.*://')
until docker exec "$NOME" pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
sleep 1
if [ "$#" -eq 0 ]; then set -- -m postgres; fi
DATABASE_URL="postgres://postgres:test@127.0.0.1:$PORTA/postgres" .venv/bin/pytest "$@"
