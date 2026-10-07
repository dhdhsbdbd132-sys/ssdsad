import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client"))


@pytest.fixture(scope="session")
def api_server(tmp_path_factory):
    folder = tmp_path_factory.mktemp("api-client")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "DATABASE_URL": f"sqlite:///{folder}/api.db",
        "MAIL_DIRECTORY": str(folder / "mail"),
        "ENVIRONMENT": "test",
        "SECRET_KEY": "test-only-key-" * 5,
        "RATE_LIMIT": "10000",
    }
    subprocess.run(
        [
            str(ROOT / ".venv/bin/alembic"),
            "-c",
            str(ROOT / "backend/alembic.ini"),
            "upgrade",
            "head",
        ],
        env=env,
        check=True,
    )
    process = subprocess.Popen(
        [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if requests.get(url + "/api/health", timeout=0.5).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Test server did not start")
        yield url, folder / "mail"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
