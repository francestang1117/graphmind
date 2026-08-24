"""Checks that private API groups keep their auth dependency."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import router as api_router
from app.api.endpoints import auth


@pytest.fixture()
def private_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(auth.settings, "AUTH_REQUIRED", True)
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/v1/documents/", None),
        ("get", "/api/v1/jobs/", None),
        ("get", "/api/v1/graph/", None),
        ("post", "/api/v1/search/", {"query": "python"}),
        ("post", "/api/v1/chat/", {"message": "What is Python?"}),
        ("post", "/api/v1/scraper/", {"url": "https://example.com"}),
    ],
)
def test_private_api_groups_reject_anonymous_requests(private_client, method, path, body):
    response = private_client.request(method, path, json=body)

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"
