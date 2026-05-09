# Testing Guide

This project currently has backend tests for upload, validation, parsing, auth,
search, graph construction, chat, persistence, rate limiting, virus scanning,
and WebSocket progress.

## Quick Start

From the project root:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests
```

Expected current result:

```text
95 passed
```

If you are starting from a fresh environment:

```bash
cd backend
python -m venv ../.venv
../.venv/bin/pip install -r requirements.txt
cd ..
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests
```

## Current Test Files

| File | What it covers |
| --- | --- |
| `backend/tests/unit/test_file_validator.py` | Extension allowlist, text/binary checks, MIME edge cases, unsafe content patterns |
| `backend/tests/unit/test_file_storage.py` | Content-addressed save/list/load/delete behavior |
| `backend/tests/integration/test_upload_api.py` | Upload/list/get/delete/open endpoints and parse persistence hook |
| `backend/tests/integration/test_documents_markdown.py` | Markdown parse cache and summary helpers |
| `backend/tests/test_markdown_parser.py` | Markdown headers, links, images, code blocks, lists, chunks, metadata |
| `backend/tests/test_document_parser_pdf.py` | pdfplumber PDF page/table extraction and table cleanup |
| `backend/tests/test_entity_extractor.py` | Domain entity extraction, spaCy fallback behavior, aliases, noise filtering |
| `backend/tests/test_full_pipeline.py` | Markdown parse -> entities -> graph construction |
| `backend/tests/test_vector_store.py` | Lightweight local vector search and hybrid scoring |
| `backend/tests/test_qa_engine.py` | Retrieval-based local QA behavior |
| `backend/tests/test_auth.py` | Register/login/refresh/logout/me flow |
| `backend/tests/test_document_repository.py` | SQLAlchemy document metadata repository |
| `backend/tests/test_persistence_service.py` | Lightweight persistence helpers |
| `backend/tests/test_parsed_artifact_repository.py` | Database persistence for parsed chunks and entities |
| `backend/tests/test_rate_limit.py` | slowapi wrapper and no-op fallback |
| `backend/tests/test_virus_scanner.py` | ClamAV response parsing and upload scan boundary |
| `backend/tests/test_websocket.py` | Celery-style job progress snapshots and WebSocket stream |

## Running Specific Tests

```bash
# One file
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_document_parser_pdf.py

# One test
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_websocket.py::test_job_progress_websocket_streams_until_success

# Stop on first failure
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -x

# Show print/log output
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -s
```

## Useful Manual Checks

Upload a Markdown file:

```bash
curl -X POST "http://localhost:8000/api/v1/documents/upload" \
  -F "file=@README.md"
```

List documents:

```bash
curl "http://localhost:8000/api/v1/documents/"
```

Inspect parsed output:

```bash
curl "http://localhost:8000/api/v1/documents/<stored_filename>/parsed"
```

Check database-backed parsed artifacts:

```bash
sqlite3 graphmind.db "select count(*) from parsed_chunks;"
sqlite3 graphmind.db "select label, text from parsed_entities limit 10;"
```

## Notes

- The current tests use the backend service functions directly in many places,
  so no running API server is needed for the normal test suite.
- ClamAV is optional in local development. The scanner is tested with fake
  responses; a real EICAR test still requires the Docker ClamAV service.
- WebSocket progress is implemented on the backend, but the upload API does not
  yet return a Celery `job_id`, so the frontend is not fully wired to it yet.
- Coverage reporting is useful later, but there is no enforced 80% coverage gate
  in this repo right now.
