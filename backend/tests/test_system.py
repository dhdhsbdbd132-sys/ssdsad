import pytest
from app.core.config import Settings


def test_health_openapi_and_security_headers(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    schema = client.get("/openapi.json").json()
    assert (
        schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]["password"][
            "tokenUrl"
        ]
        == "/api/auth/token"
    )
    assert {"get", "post"} <= set(schema["paths"]["/api/events"])
    assert {"get", "patch", "delete"} <= set(schema["paths"]["/api/events/{event_id}"])
    assert "400" in schema["paths"]["/api/events"]["post"]["responses"]
    assert "422" not in schema["paths"]["/api/events"]["post"]["responses"]
    assert client.get("/docs").status_code == 200


def test_rate_limit(app):
    from app.main import create_app
    from fastapi.testclient import TestClient

    s = app.state.settings.model_copy(update={"rate_limit": 2})
    limited = create_app(s)
    with TestClient(limited) as c:
        for _ in range(2):
            assert c.post("/api/auth/login", json={}).status_code == 400
        assert c.post("/api/auth/login", json={}).status_code == 429


def test_500_sanitized(client, app):
    @app.get("/__test_failure")
    def failure():
        raise RuntimeError("sensitive database details")

    r = client.get("/__test_failure")
    assert r.status_code == 500 and "sensitive" not in r.text
    assert r.json()["request_id"]


def test_body_limit(client):
    r = client.post("/api/auth/login", content="x" * 70000)
    assert r.status_code == 413


def test_production_rejects_insecure_settings():
    with pytest.raises(ValueError):
        Settings(environment="production", secret_key="short")
    with pytest.raises(ValueError):
        Settings(environment="production", secret_key="s" * 64, mail_backend="file")


def test_chunked_body_limit(client):
    response = client.post("/api/auth/login", content=iter([b"x" * 40000, b"y" * 40000]))
    assert response.status_code == 413
