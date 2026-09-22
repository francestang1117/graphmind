"""Metrics smoke tests for the Prometheus endpoint."""

from fastapi.testclient import TestClient

from app.main import app


def test_metrics_endpoint_records_route_labels():
    client = TestClient(app)

    health = client.get("/health", headers={"X-GraphMind-Frontend-Commit": "test-ui-sha"})
    response = client.get("/metrics")

    assert health.headers["x-graphmind-frontend-commit"] == "test-ui-sha"
    assert health.headers["x-graphmind-parser-version"] == "document-parser-pdf-readable-v2"
    assert health.headers["x-graphmind-analysis-pipeline"] == "medical-insights-readable-v2"
    assert health.headers["x-graphmind-insight-contract"] == "medical-insights-readable-v2"
    assert health.headers["x-graphmind-analysis-model"] == "extractive-v2"
    assert response.status_code == 200
    assert "graphmind_http_requests_total" in response.text
    assert 'path="/health"' in response.text
