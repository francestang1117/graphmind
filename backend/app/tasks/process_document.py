"""Background entrypoint for parsing a stored document."""

from typing import Any, Dict

from app.core.celery_app import celery_app
from app.services.document_parser import DocumentParser


@celery_app.task(bind=True, name="app.tasks.process_document.process_document")
def process_document(self, file_path: str, filename: str = "") -> Dict[str, Any]:
    _progress(self, 10, "Queued document parser")
    _progress(self, 35, "Parsing document")
    parsed = DocumentParser().parse(file_path)
    _progress(self, 75, "Collecting parse summary")
    return {
        "filename": filename or parsed["metadata"]["filename"],
        "format": parsed["metadata"]["format"],
        "chunks": len(parsed["chunks"]),
        "content_length": len(parsed["content"]),
    }


def _progress(task, pct: int, step: str) -> None:
    """Best-effort progress update for Celery workers and the local fallback."""
    update_state = getattr(task, "update_state", None)
    if update_state:
        update_state(state="PROGRESS", meta={"pct": pct, "step": step})
