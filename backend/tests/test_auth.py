import json
from datetime import timedelta
from sqlalchemy import select
from app.models import User, Challenge, RefreshSession, utcnow


def get_code(app, cid):
    return json.loads((app.state.settings.mail_directory / f"{cid}.json").read_text())["code"]


def test_registration_requires_two_factors_and_unique_email(client, app):
    data = {
        "name": "Мария",
        "email": "maria@example.com",
        "password": "PasswordTest42",
        "role": "organizer",
    }
    response = client.post("/api/auth/register", json=data)
    assert response.status_code == 201
    challenge = response.json()
    assert "access_token" not in challenge and "code" not in challenge
    cid = challenge["challenge_id"]
    code = get_code(app, cid)
    assert (
        client.post("/api/auth/verify", json={"challenge_id": cid, "code": "123"}).status_code
        == 400
    )
    wrong = "000000" if code != "000000" else "111111"
    assert (
        client.post("/api/auth/verify", json={"challenge_id": cid, "code": wrong}).status_code
        == 401
    )
    tokens = client.post("/api/auth/verify", json={"challenge_id": cid, "code": code})
    assert tokens.status_code == 200
    assert (
        client.post("/api/auth/verify", json={"challenge_id": cid, "code": code}).status_code == 401
    )
    assert client.post("/api/auth/register", json=data).status_code == 409
    assert (
        client.post(
            "/api/auth/register", json={**data, "email": "admin@example.com", "role": "admin"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/auth/register",
            json={**data, "email": "weak@example.com", "password": "1234567890"},
        ).status_code
        == 400
    )
    with app.state.db.sessions() as db:
        user = db.scalar(select(User).where(User.email == data["email"]))
        assert user.password_hash.startswith("$argon2") and user.password_hash != data["password"]
        row = db.get(Challenge, cid)
        assert row.code_hash != code


def test_refresh_rotation_replay_revocation_and_logout(client, account, app):
    tokens, headers = account()
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    fresh = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert fresh.status_code == 200
    new = fresh.json()
    newheaders = {"Authorization": "Bearer " + new["access_token"]}
    assert new["refresh_token"] != tokens["refresh_token"]
    assert client.get("/api/auth/me", headers=newheaders).status_code == 200
    assert (
        client.post(
            "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )
    assert client.get("/api/auth/me", headers=newheaders).status_code == 401
    login = client.post(
        "/api/auth/login", json={"email": tokens["user"]["email"], "password": "StrongPassword42"}
    )
    cid = login.json()["challenge_id"]
    verified = client.post(
        "/api/auth/verify", json={"challenge_id": cid, "code": get_code(app, cid)}
    ).json()
    h = {"Authorization": "Bearer " + verified["access_token"]}
    assert client.post("/api/auth/logout", headers=h).status_code == 204
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert (
        client.post(
            "/api/auth/refresh", json={"refresh_token": verified["refresh_token"]}
        ).status_code
        == 401
    )
    with app.state.db.sessions() as db:
        rows = db.scalars(select(RefreshSession)).all()
        assert all(
            row.token_hash not in {tokens["refresh_token"], new["refresh_token"]} for row in rows
        )


def test_otp_attempt_limit_expiration_and_invalid_password(client, app, account):
    account()
    assert (
        client.post(
            "/api/auth/login", json={"email": "organizer@example.com", "password": "wrong"}
        ).status_code
        == 401
    )
    login = client.post(
        "/api/auth/login", json={"email": "organizer@example.com", "password": "StrongPassword42"}
    )
    cid = login.json()["challenge_id"]
    code = get_code(app, cid)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert (
            client.post("/api/auth/verify", json={"challenge_id": cid, "code": wrong}).status_code
            == 401
        )
    assert (
        client.post("/api/auth/verify", json={"challenge_id": cid, "code": code}).status_code == 401
    )
    cid = client.post(
        "/api/auth/login", json={"email": "organizer@example.com", "password": "StrongPassword42"}
    ).json()["challenge_id"]
    with app.state.db.sessions() as db:
        db.get(Challenge, cid).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert (
        client.post(
            "/api/auth/verify", json={"challenge_id": cid, "code": get_code(app, cid)}
        ).status_code
        == 401
    )


def test_admin_roles_audit_and_session_revocation(client, account, app):
    admin, ha = account("admin@example.com")
    target, ht = account("target@example.com", "attendee")
    with app.state.db.sessions() as db:
        db.get(User, admin["user"]["id"]).role = "admin"
        db.commit()
    assert client.get("/api/admin/users", headers=ha).status_code == 200
    uid = target["user"]["id"]
    assert (
        client.patch(
            f"/api/admin/users/{uid}/role", json={"role": "moderator"}, headers=ha
        ).status_code
        == 200
    )
    assert client.get("/api/auth/me", headers=ht).status_code == 401
    assert (
        client.patch(
            f"/api/admin/users/{admin['user']['id']}/role", json={"role": "attendee"}, headers=ha
        ).status_code
        == 400
    )
    assert any(
        row["action"] == "user.role.moderator"
        for row in client.get("/api/admin/audit", headers=ha).json()
    )


def test_oauth2_swagger_token_endpoint(client, account, app):
    account()
    cid = client.post(
        "/api/auth/login", json={"email": "organizer@example.com", "password": "StrongPassword42"}
    ).json()["challenge_id"]
    result = client.post("/api/auth/token", data={"username": cid, "password": get_code(app, cid)})
    assert result.status_code == 200 and result.json()["token_type"] == "bearer"


def test_oauth2_invalid_form_is_400(client):
    assert (
        client.post("/api/auth/token", data={"username": "bad", "password": "bad"}).status_code
        == 400
    )
