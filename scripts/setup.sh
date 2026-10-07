#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r backend/requirements.txt
python3 -m venv .client-venv
.client-venv/bin/python -m pip install --disable-pip-version-check -r client/requirements.lock.txt
.venv/bin/alembic -c backend/alembic.ini upgrade head
setup_environment="$(PYTHONPATH=backend .venv/bin/python -c 'from app.core.config import Settings; print(Settings().environment)')"
if [ "$setup_environment" != "production" ]; then
    PYTHONPATH=backend .venv/bin/python -m app.cli seed
fi
