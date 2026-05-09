"""Application error payload tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import ParseError, error_payload
from app.core.errors import UploadRejectedError, register_error_handlers


def test_app_error_payload_includes_code_and_details():
    error = ParseError(details={"filename": "broken.pdf", "reason": "empty text"})

    assert error_payload(error) == {
        "detail": "Could not parse this file.",
        "code": "parse_failed",
        "details": {"filename": "broken.pdf", "reason": "empty text"},
    }


def test_app_error_handler_returns_flat_payload():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    async def boom():
        raise UploadRejectedError("File type .exe is not supported.")

    response = TestClient(app).get("/boom")

    assert response.status_code == 400
    assert response.json() == {
        "detail": "File type .exe is not supported.",
        "code": "upload_validation_failed",
    }
