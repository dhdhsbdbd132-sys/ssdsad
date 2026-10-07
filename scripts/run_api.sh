#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/alembic -c backend/alembic.ini upgrade head
exec .venv/bin/uvicorn app.main:app --app-dir backend --host "${API_HOST:-127.0.0.1}" --port "${API_PORT:-8000}" --no-access-log
