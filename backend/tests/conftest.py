import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import os
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.core.db import Base
from app.main import create_app


@pytest.fixture
def app(tmp_path):
    s = Settings(
        environment="test",
        database_url=os.environ.get("TEST_DATABASE_URL", f"sqlite:///{tmp_path}/test.db"),
        secret_key="test-key-" * 8,
        mail_directory=tmp_path / "mail",
        rate_limit=10000,
    )
    app = create_app(s)
    if os.environ.get("TEST_DATABASE_URL"):
        Base.metadata.drop_all(app.state.db.engine)
    Base.metadata.create_all(app.state.db.engine)
    yield app
    app.state.db.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def account(client, app):
    def create(email="organizer@example.com", role="organizer"):
        r = client.post(
            "/api/auth/register",
            json={
                "name": "Тестовый пользователь",
                "email": email,
                "password": "StrongPassword42",
                "role": role,
            },
        )
        assert r.status_code == 201, r.text
        cid = r.json()["challenge_id"]
        code = json.loads((app.state.settings.mail_directory / f"{cid}.json").read_text())["code"]
        tokens = client.post("/api/auth/verify", json={"challenge_id": cid, "code": code})
        assert tokens.status_code == 200, tokens.text
        data = tokens.json()
        return data, {"Authorization": "Bearer " + data["access_token"]}

    return create


@pytest.fixture
def payload():
    from datetime import datetime, timezone, timedelta

    return {
        "title": "Московский пикник",
        "description": "Встречаемся у пруда и знакомимся с соседями.",
        "category": "community",
        "starts_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        "address": "Патриаршие пруды, Москва",
        "latitude": 55.7638,
        "longitude": 37.5927,
        "capacity": 2,
    }
