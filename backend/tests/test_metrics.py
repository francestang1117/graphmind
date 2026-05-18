"""Metrics smoke tests for the Prometheus endpoint."""

from fastapi.testclient import TestClient

from app.main import app


def test_metrics_endpoint_records_route_labels():
    client = TestClient(app)

    client.get("/health")
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "graphmind_http_requests_total" in response.text
    assert 'path="/health"' in response.text

