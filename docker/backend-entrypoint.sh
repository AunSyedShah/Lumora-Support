#!/bin/sh
# Runs before the backend starts: wait for the database, create the tables, load first-run data.
# Every step is switchable with an environment variable (see docker-compose.yml) and is safe to repeat.
# (One Django process does migrate + data: starting Django is the slow part of a container start.)
set -eu

if [ -n "${DATABASE_URL:-}" ] && [ "${WAIT_FOR_DB:-1}" = "1" ]; then
  echo "[backend] waiting for the database ..."
  python - <<'PY'
import os, sys, time
import psycopg

for attempt in range(60):
    try:
        psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=3).close()
        sys.exit(0)
    except psycopg.OperationalError as error:
        last = error
        time.sleep(2)
print(f"[backend] the database did not answer: {last}", file=sys.stderr)
sys.exit(1)
PY
fi

extra=""
if [ "${BOOTSTRAP_DATASET:-0}" = "1" ]; then extra="--dataset"; fi

if [ "${RUN_MIGRATIONS:-1}" = "1" ] && [ "${AUTO_BOOTSTRAP:-1}" = "1" ]; then
  echo "[backend] database tables + first-run data (only what is missing) ..."
  uv run manage.py bootstrap_data --migrate $extra
elif [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "[backend] applying database migrations ..."
  uv run manage.py migrate --noinput
elif [ "${AUTO_BOOTSTRAP:-1}" = "1" ]; then
  echo "[backend] first-run data (only what is missing) ..."
  uv run manage.py bootstrap_data $extra
fi

echo "[backend] ready: API http://localhost:${BACKEND_PORT:-8001}/api/docs"
exec "$@"
