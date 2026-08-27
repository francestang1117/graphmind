from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.endpoints import auth


@pytest.fixture(autouse=True)
def isolate_auth_storage(monkeypatch):
    monkeypatch.setattr(auth, "load_user_record", lambda **_: None)
    monkeypatch.setattr(auth, "save_user_record", lambda _: None)
    monkeypatch.setattr(auth, "load_user_by_oauth", lambda *_: None)
    monkeypatch.setattr(auth, "save_oauth_identity", lambda *_: None)

    async def no_redis():
        return None

    monkeypatch.setattr(auth, "_redis_client", no_redis)


def _client() -> TestClient:
    auth._users.clear()
    auth._refresh_tokens.clear()
    auth._oauth_users.clear()
    auth._oauth_values.clear()
    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")
    return TestClient(app)


def test_register_login_refresh_logout_flow():
    client = _client()

    register = client.post(
        "/auth/register",
        json={"email": "Ada@example.com", "password": "strong-pass", "name": "Ada"},
    )
    assert register.status_code == 201
    tokens = register.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert client.cookies.get(auth.settings.REFRESH_COOKIE_NAME)

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "ada@example.com"
    assert me.json()["name"] == "Ada"

    login = client.post(
        "/auth/login",
        data={"username": "ada@example.com", "password": "strong-pass"},
    )
    assert login.status_code == 200
    login_tokens = login.json()
    cookie_header = {
        "Cookie": f"{auth.settings.REFRESH_COOKIE_NAME}={login_tokens['refresh_token']}"
    }

    refresh = client.post("/auth/refresh", headers=cookie_header)
    assert refresh.status_code == 200
    assert refresh.json()["access_token"]

    logout = client.post(
        "/auth/logout",
        headers={
            "Authorization": f"Bearer {login_tokens['access_token']}",
            **cookie_header,
        },
    )
    assert logout.status_code == 200

    assert "Max-Age=0" in logout.headers["set-cookie"]
    refresh_again = client.post("/auth/refresh", headers=cookie_header)
    assert refresh_again.status_code == 401


def test_duplicate_email_is_rejected():
    client = _client()
    body = {"email": "user@example.com", "password": "strong-pass"}

    assert client.post("/auth/register", json=body).status_code == 201
    duplicate = client.post("/auth/register", json=body)

    assert duplicate.status_code == 409


def test_registration_rejects_weak_or_oversized_passwords():
    client = _client()

    too_short = client.post(
        "/auth/register",
        json={"email": "short@example.com", "password": "short"},
    )
    common = client.post(
        "/auth/register",
        json={"email": "common@example.com", "password": "password123"},
    )
    too_large = client.post(
        "/auth/register",
        json={"email": "large@example.com", "password": "界" * 25},
    )

    assert too_short.status_code == 422
    assert too_short.json()["detail"] == "Password must be at least 8 characters"
    assert common.status_code == 422
    assert common.json()["detail"] == "This password is too common"
    assert too_large.status_code == 422
    assert too_large.json()["detail"] == "Password must not exceed 72 UTF-8 bytes"


def test_persisted_user_can_login_after_local_cache_is_cleared(monkeypatch):
    client = _client()
    register = client.post(
        "/auth/register",
        json={"email": "restart@example.com", "password": "restart-passphrase", "name": "Restart"},
    )
    assert register.status_code == 201

    saved = auth._users["restart@example.com"]
    persisted = {
        "id": saved.id,
        "email": saved.email,
        "name": saved.name,
        "hashed_password": saved.hashed_password,
        "created_at": saved.created_at,
    }
    auth._users.clear()
    monkeypatch.setattr(auth, "load_user_record", lambda **_: persisted)

    login = client.post(
        "/auth/login",
        data={"username": "restart@example.com", "password": "restart-passphrase"},
    )
    assert login.status_code == 200

    me = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {register.json()['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "restart@example.com"


def test_auth_required_rejects_anonymous_access(monkeypatch):
    monkeypatch.setattr(auth.settings, "AUTH_REQUIRED", True)
    app = FastAPI()

    @app.get("/private")
    async def private_route(user: auth.UserRecord = Depends(auth.current_user_or_dev)):
        return {"user_id": user.id}

    response = TestClient(app).get("/private")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"
    assert response.headers["www-authenticate"] == "Bearer"


def test_auth_required_accepts_registered_user(monkeypatch):
    monkeypatch.setattr(auth.settings, "AUTH_REQUIRED", True)
    client = _client()

    @client.app.get("/private")
    async def private_route(user: auth.UserRecord = Depends(auth.current_user_or_dev)):
        return {"user_id": user.id}

    register = client.post(
        "/auth/register",
        json={"email": "private@example.com", "password": "private-passphrase"},
    )
    response = client.get(
        "/private",
        headers={"Authorization": f"Bearer {register.json()['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["user_id"]


def test_github_provider_and_start_redirect(monkeypatch):
    client = _client()
    monkeypatch.setattr(auth.settings, "GITHUB_OAUTH_CLIENT_ID", "client-123")
    monkeypatch.setattr(auth.settings, "GITHUB_OAUTH_CLIENT_SECRET", "secret-123")

    providers = client.get("/auth/providers")
    start = client.get(
        "/auth/github/start",
        params={"return_origin": "http://localhost:5173"},
        follow_redirects=False,
    )

    assert providers.json() == {"github": True}
    assert start.status_code == 307
    location = start.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=client-123" in location
    assert "code_challenge_method=S256" in location
    assert any(key.startswith("oauth:github:state:") for key in auth._oauth_values)


def test_github_start_rejects_unconfigured_or_unknown_origin(monkeypatch):
    client = _client()
    monkeypatch.setattr(auth.settings, "GITHUB_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(auth.settings, "GITHUB_OAUTH_CLIENT_SECRET", "")

    missing = client.get(
        "/auth/github/start",
        params={"return_origin": "http://localhost:5173"},
        follow_redirects=False,
    )
    assert missing.status_code == 503

    monkeypatch.setattr(auth.settings, "GITHUB_OAUTH_CLIENT_ID", "client-123")
    monkeypatch.setattr(auth.settings, "GITHUB_OAUTH_CLIENT_SECRET", "secret-123")
    unknown = client.get(
        "/auth/github/start",
        params={"return_origin": "https://untrusted.example"},
        follow_redirects=False,
    )
    assert unknown.status_code == 400


def test_github_callback_uses_one_time_handoff(monkeypatch):
    client = _client()
    auth._oauth_values["oauth:github:state:valid-state"] = (
        '{"origin":"http://localhost:5173","verifier":"pkce-verifier"}',
        auth.datetime.now(auth.timezone.utc) + auth.timedelta(minutes=10),
    )

    async def github_identity(code, verifier):
        assert code == "github-code"
        assert verifier == "pkce-verifier"
        return {
            "provider_user_id": "991122",
            "email": "octo@example.com",
            "name": "Octo Cat",
        }

    monkeypatch.setattr(auth, "_fetch_github_identity", github_identity)
    callback = client.get(
        "/auth/github/callback",
        params={"state": "valid-state", "code": "github-code"},
    )

    assert callback.status_code == 200
    assert "graphmind:oauth" in callback.text
    assert client.cookies.get(auth.settings.REFRESH_COOKIE_NAME)
    handoff_key = next(key for key in auth._oauth_values if key.startswith("oauth:handoff:"))
    handoff = handoff_key.removeprefix("oauth:handoff:")

    exchange = client.post("/auth/oauth/exchange", json={"code": handoff})
    repeated = client.post("/auth/oauth/exchange", json={"code": handoff})

    assert exchange.status_code == 200
    assert exchange.json()["access_token"]
    assert repeated.status_code == 401
    assert auth._users["octo@example.com"].name == "Octo Cat"


def test_github_identity_reuses_the_same_local_user():
    first = auth._oauth_user("github", "991122", "octo@example.com", "Octo Cat")
    second = auth._oauth_user("github", "991122", "changed@example.com", "Renamed Cat")

    assert second.id == first.id
    assert second.email == first.email
