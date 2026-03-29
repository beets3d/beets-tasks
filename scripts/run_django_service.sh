#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"
VENV_DIR="${VENV_DIR:-$PWD/.venv}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}"

cd "$(dirname "$0")/.."

if [[ -x "$VENV_DIR/bin/gunicorn" ]]; then
  exec "$VENV_DIR/bin/gunicorn" jira_mcp_server.wsgi:application \
    --bind "${HOST}:${PORT}" \
    --workers "$WEB_CONCURRENCY" \
    --timeout 120
fi

exec "$VENV_DIR/bin/python" manage.py runserver "${HOST}:${PORT}"
