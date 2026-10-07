#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .data/wheels .data/docker
.venv/bin/python -m pip download --only-binary=:all: --dest .data/wheels -r backend/requirements.txt
# Docker build workers in some cloud environments have no DNS/network. Install
# the same HTTPS-downloaded, pinned distributions using a read-only build context.
DOCKER_CONFIG="$PWD/.data/docker" docker build \
    --build-context wheels=.data/wheels -f deploy/Dockerfile.offline -t todaygo-api:local .
