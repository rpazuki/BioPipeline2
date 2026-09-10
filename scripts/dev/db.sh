#!/usr/bin/env bash
# Development database helper.
#
#   ./scripts/dev/db.sh up        start PostgreSQL
#   ./scripts/dev/db.sh down      stop it
#   ./scripts/dev/db.sh reset     drop the schema and migrate to head
#   ./scripts/dev/db.sh migrate   migrate to head
#   ./scripts/dev/db.sh psql      open a shell
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE="docker compose -f ${ROOT}/deploy/compose/compose.dev.yaml"
export BP_DATABASE_URL="${BP_DATABASE_URL:-postgresql+psycopg://biopipeline:biopipeline@localhost:55432/biopipeline2}"

# Wait on the *host* port, not the in-container socket. pg_isready inside the
# container succeeds as soon as the unix socket is up, which is before Docker
# has finished publishing the port, so checking there races with the client.
wait_for_postgres() {
  for _ in $(seq 1 60); do
    if "${ROOT}/.venv/bin/python" - <<'PYEOF' >/dev/null 2>&1
import socket, sys
with socket.socket() as s:
    s.settimeout(1)
    sys.exit(s.connect_ex(("127.0.0.1", 55432)))
PYEOF
    then
      return 0
    fi
    sleep 1
  done
  echo "postgres did not become ready on localhost:55432" >&2
  return 1
}

case "${1:-}" in
  up)
    ${COMPOSE} up -d postgres
    wait_for_postgres
    echo "postgres ready on localhost:55432"
    ;;
  down)
    ${COMPOSE} down
    ;;
  reset)
    ${COMPOSE} up -d postgres
    wait_for_postgres
    ${COMPOSE} exec -T postgres psql -U biopipeline -d biopipeline2 \
      -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" >/dev/null
    (cd "${ROOT}/backend" && "${ROOT}/.venv/bin/alembic" upgrade head)
    echo "schema reset and migrated to head"
    ;;
  migrate)
    (cd "${ROOT}/backend" && "${ROOT}/.venv/bin/alembic" upgrade head)
    ;;
  psql)
    ${COMPOSE} exec postgres psql -U biopipeline -d biopipeline2
    ;;
  *)
    sed -n '2,10p' "$0"
    exit 1
    ;;
esac
