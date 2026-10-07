"""Exercise OIDC end-to-end with a locally signed provider identity and mocked HTTPS."""

import json
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, parse_qs
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from app.services import oauth


def test_oidc_pkce_nonce_mail_factor_and_single_use(client, app, monkeypatch):
    settings = app.state.settings
    settings.oauth_client_id = "test-client"
    settings.oauth_client_secret = "test-secret"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "test-key"
    metadata = {
        "issuer": settings.oauth_issuer,
        "authorization_endpoint": "https://provider.example.com/authorize",
        "token_endpoint": "https://provider.example.com/token",
        "jwks_uri": "https://provider.example.com/jwks",
    }
    context = {}

    def handler(request):
        if str(request.url) == settings.oauth_discovery_url:
            return httpx.Response(200, json=metadata)
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [jwk]})
        if request.url.path == "/token":
            data = parse_qs(request.content.decode())
            verifier = data["code_verifier"][0]
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("=")
            )
            assert challenge == context["code_challenge"]
            now = datetime.now(timezone.utc)
            token = jwt.encode(
                {
                    "iss": settings.oauth_issuer,
                    "aud": "test-client",
                    "sub": "provider-user",
                    "iat": now,
                    "exp": now + timedelta(minutes=5),
                    "nonce": context["nonce"],
                    "email": "oauth@example.com",
                    "email_verified": True,
                    "name": "OAuth User",
                },
                key,
                algorithm="RS256",
                headers={"kid": "test-key"},
            )
            return httpx.Response(200, json={"id_token": token})
        return httpx.Response(404)

    original = httpx.Client
    monkeypatch.setattr(
        oauth.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    start = client.get("/api/auth/oauth/start")
    assert start.status_code == 200
    data = start.json()
    query = parse_qs(urlsplit(data["authorization_url"]).query)
    context.update({key: value[0] for key, value in query.items()})
    assert context["code_challenge_method"] == "S256"
    poll = {"state": data["state"], "poll_key": data["poll_key"]}
    assert client.post("/api/auth/oauth/poll", json=poll).json()["status"] == "pending"
    assert (
        client.post("/api/auth/oauth/poll", json={**poll, "poll_key": "x" * 43}).status_code == 401
    )
    assert (
        client.get(
            "/api/auth/oauth/callback", params={"state": data["state"], "code": "test-code"}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/auth/oauth/callback", params={"state": data["state"], "code": "test-code"}
        ).status_code
        == 400
    )
    completed = client.post("/api/auth/oauth/poll", json=poll).json()
    assert completed["status"] == "complete" and "access_token" not in completed
    assert client.post("/api/auth/oauth/poll", json=poll).status_code == 401
    cid = completed["challenge_id"]
    code = json.loads((settings.mail_directory / f"{cid}.json").read_text())["code"]
    assert (
        client.post("/api/auth/verify", json={"challenge_id": cid, "code": code}).status_code == 200
    )
