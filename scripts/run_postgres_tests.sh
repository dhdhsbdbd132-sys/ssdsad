#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .data
pg_test_file="$(mktemp "$PWD/.data/pg-test-XXXXXX.env")"
pg_test_container="todaygo-test-${BASHPID}"
cleanup() {
    docker rm -f "$pg_test_container" >/dev/null 2>&1 || true
    rm -f "$pg_test_file"
}
trap cleanup EXIT
.venv/bin/python - "$pg_test_file" <<'PY'
from pathlib import Path
import secrets,sys
path=Path(sys.argv[1])
path.write_text('POSTGRES_USER=todaygo_test\nPOSTGRES_DB=todaygo_test\nPOSTGRES_PASSWORD='+secrets.token_urlsafe(32)+'\n')
path.chmod(0o600)
PY
docker run -d --name "$pg_test_container" --env-file "$pg_test_file" \
    -p 127.0.0.1::5432 postgres:16-alpine >/dev/null
pg_test_port="$(docker port "$pg_test_container" 5432/tcp | sed -n 's/127.0.0.1://p')"
pg_test_ready=0
for pg_test_attempt in {1..30}; do
    if docker exec "$pg_test_container" pg_isready -U todaygo_test -d todaygo_test >/dev/null 2>&1; then
        pg_test_ready=1
        break
    fi
    sleep 0.2
done
if [ "$pg_test_ready" != 1 ]; then
    echo 'Disposable PostgreSQL did not start' >&2
    exit 1
fi
POSTGRES_TEST_ENV="$pg_test_file" POSTGRES_TEST_PORT="$pg_test_port" .venv/bin/python scripts/test_postgres.py
POSTGRES_TEST_ENV="$pg_test_file" POSTGRES_TEST_PORT="$pg_test_port" .venv/bin/python scripts/check_migrations.py
