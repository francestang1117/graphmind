"""Optional Celery-compatible task for document parsing.

The current upload endpoint uses this function through FastAPI background
tasks. The Celery decorator keeps the same entrypoint ready for a later worker
without pulling graph or vector services into this phase.

Implemented:
- parse stored files after upload
- return a small processing summary
- keep the function callable by both background tasks and future Celery workers
"""

from typing import Any, Dict

from app.core.celery_app import celery_app
from app.services.document_parser import DocumentParser


@celery_app.task(name="app.tasks.process_document.process_document")
def process_document(file_path: str, filename: str = "") -> Dict[str, Any]:
    parsed = DocumentParser().parse(file_path)
    return {
        "filename": filename or parsed["metadata"]["filename"],
        "format": parsed["metadata"]["format"],
        "chunks": len(parsed["chunks"]),
        "content_length": len(parsed["content"]),
    }
