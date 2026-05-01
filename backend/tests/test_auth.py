from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import auth


def _client() -> TestClient:
    auth._users.clear()
    auth._refresh_tokens.clear()
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

    refresh = client.post("/auth/refresh", json={"refresh_token": login_tokens["refresh_token"]})
    assert refresh.status_code == 200
    assert refresh.json()["access_token"]

    logout = client.post(
        "/auth/logout",
        json={"refresh_token": login_tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {login_tokens['access_token']}"},
    )
    assert logout.status_code == 200

    refresh_again = client.post("/auth/refresh", json={"refresh_token": login_tokens["refresh_token"]})
    assert refresh_again.status_code == 401


def test_duplicate_email_is_rejected():
    client = _client()
    body = {"email": "user@example.com", "password": "strong-pass"}

    assert client.post("/auth/register", json=body).status_code == 201
    duplicate = client.post("/auth/register", json=body)

    assert duplicate.status_code == 409
