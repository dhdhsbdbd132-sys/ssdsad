"""Use only the dedicated disposable PostgreSQL test container created for validation."""

import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
config_path = Path(os.environ.get("POSTGRES_TEST_ENV", root / ".data/postgres-test.env"))
if not config_path.exists():
    raise SystemExit("Run bash scripts/run_postgres_tests.sh")
config = dict(line.split("=", 1) for line in config_path.read_text().splitlines())
url = f"postgresql+psycopg://{config['POSTGRES_USER']}:{config['POSTGRES_PASSWORD']}@127.0.0.1:{os.environ.get('POSTGRES_TEST_PORT', '55432')}/{config['POSTGRES_DB']}"
env = {**os.environ, "TEST_DATABASE_URL": url}
result = subprocess.run([str(root / ".venv/bin/pytest"), "backend/tests", "-q"], cwd=root, env=env)
raise SystemExit(result.returncode)
