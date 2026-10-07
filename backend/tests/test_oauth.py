"""External sign-in is absent; password and code authentication keeps its token endpoint."""


def test_google_sign_in_routes_are_unavailable(client):
    for method, path in (
        ("GET", "/api/auth/oauth/start"),
        ("GET", "/api/auth/oauth/callback?state=old-attempt&code=old-code"),
        ("POST", "/api/auth/oauth/poll"),
    ):
        response = client.request(method, path)
        assert response.status_code == 404
        assert "authorization_url" not in response.text


def test_openapi_keeps_local_token_flow_without_external_sign_in(client):
    schema = client.get("/openapi.json").json()
    assert not any("/auth/oauth/" in path for path in schema["paths"])
    assert not {"OAuthStart", "OAuthPoll"} & schema["components"]["schemas"].keys()
    assert "/api/auth/token" in schema["paths"]
    assert "/api/auth/login" in schema["paths"]
    assert "/api/auth/verify" in schema["paths"]
