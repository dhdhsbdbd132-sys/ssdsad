"""Round-trip migrations only on a new local DB or the disposable PG test DB."""

import os
import subprocess
import tempfile
from pathlib import Path
from sqlalchemy import create_engine, inspect

root = Path(__file__).resolve().parents[1]
urls = []
folder = tempfile.TemporaryDirectory(prefix="todaygo-migrations-")
urls.append(("SQLite", f"sqlite:///{folder.name}/migration.db"))
p = Path(os.environ.get("POSTGRES_TEST_ENV", root / ".data/postgres-test.env"))
if p.exists():
    c = dict(line.split("=", 1) for line in p.read_text().splitlines())
    urls.append(
        (
            "PostgreSQL",
            f"postgresql+psycopg://{c['POSTGRES_USER']}:{c['POSTGRES_PASSWORD']}@127.0.0.1:{os.environ.get('POSTGRES_TEST_PORT', '55432')}/{c['POSTGRES_DB']}",
        )
    )
for name, url in urls:
    env = {**os.environ, "DATABASE_URL": url, "ENVIRONMENT": "test"}
    # The PG test DB may contain metadata-only tables left by tests; recreate
    # its public schema using the ORM, not any real application database.
    from sys import path

    path.insert(0, str(root / "backend"))
    from app.core.db import Base
    from app import models  # noqa: F401 -- register ORM tables

    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        from sqlalchemy import MetaData

        m = MetaData()
        m.reflect(
            connection,
            only=["alembic_version"]
            if "alembic_version" in inspect(connection).get_table_names()
            else [],
        )
        if "alembic_version" in m.tables:
            m.tables["alembic_version"].drop(connection)

    def run(*args):
        subprocess.run(
            [str(root / ".venv/bin/alembic"), "-c", str(root / "backend/alembic.ini"), *args],
            cwd=root,
            env=env,
            check=True,
        )

    run("upgrade", "head")
    assert {
        "users",
        "events",
        "participations",
        "refresh_sessions",
        "challenges",
        "oauth_attempts",
        "audit_logs",
    } <= set(inspect(engine).get_table_names())
    run("check")
    run("downgrade", "base")
    assert "users" not in inspect(engine).get_table_names()
    run("upgrade", "head")
    engine.dispose()
    print(name, "migration upgrade/check/downgrade/upgrade: passed")
folder.cleanup()
