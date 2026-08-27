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
156 passed
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
| `backend/tests/test_auth.py` | Email/password auth, refresh cookies, GitHub OAuth state/PKCE/handoff flow |
| `backend/tests/test_auth_boundaries.py` | Anonymous and signed-in access to private API groups |
| `backend/tests/test_document_repository.py` | SQLAlchemy document metadata repository |
| `backend/tests/test_persistence_service.py` | Lightweight persistence helpers |
| `backend/tests/test_parsed_artifact_repository.py` | Database persistence for parsed chunks and entities |
| `backend/tests/test_graph_repository.py` | Database persistence for graph nodes/edges |
| `backend/tests/test_rate_limit.py` | slowapi wrapper and no-op fallback |
| `backend/tests/test_virus_scanner.py` | ClamAV response parsing and upload scan boundary |
| `backend/tests/unit/test_object_storage.py` | S3/MinIO storage behavior with a fake client |
| `backend/tests/test_websocket.py` | Celery-style job progress snapshots and WebSocket stream |
| `backend/tests/test_job_repository.py` | DB-backed job history and cleanup |

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

Check the production-style auth boundary:

```bash
cd backend
AUTH_REQUIRED=true ../.venv/bin/python -m uvicorn app.main:app --port 8001
```

In another terminal, an anonymous document request should return `401`:

```bash
curl -i "http://localhost:8001/api/v1/documents/"
```

Open the frontend with `VITE_API_URL=http://localhost:8001`. The first private
request opens the sign-in dialog. Registering or signing in retries future
requests with the new access token.

Test GitHub login manually:

1. Create a GitHub OAuth App in **Settings → Developer settings → OAuth Apps**.
2. Set the homepage to `http://localhost:5173`.
3. Set the callback to `http://localhost:8000/api/v1/auth/github/callback`.
4. Copy its Client ID and Client Secret into `backend/.env` using the names in
   `.env.example`.
5. Restart the backend and frontend. The account dialog will show
   **Continue with GitHub**.

The automated tests mock GitHub's token/profile endpoints. A real manual test
is still required after creating the OAuth App because repository secrets are
not stored in this project.

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

Test the MinIO storage path:

```bash
STORAGE_BACKEND=s3 docker compose --profile storage up -d
curl -X POST "http://localhost:8000/api/v1/documents/upload" \
  -F "file=@README.md"
```

The upload response should include a stored filename and `job_id`. Check the
file in the `graphmind` bucket at `http://localhost:9001`, then use the normal
parsed, open, and delete endpoints with the stored filename.

## Notes

- The current tests use the backend service functions directly in many places,
  so no running API server is needed for the normal test suite.
- ClamAV is optional in local development. The scanner is tested with fake
  responses; a real EICAR test still requires the Docker ClamAV service.
- WebSocket progress is implemented on the backend. Upload returns `job_id`
  when `CELERY_ENABLED=true`; local background-task mode still returns `null`.
- Job controls are covered by backend tests. For a manual browser check, upload
  a larger file with Celery enabled, cancel the active row, then retry it from
  the same row.
- Job history is covered by repository tests. With Celery enabled, `GET
  /api/v1/jobs/` should show recent upload jobs, and the Documents panel should
  show the same jobs in the Recent jobs section.
- In local mode, upload rows should show `Local` briefly before disappearing.
  In Celery mode, active rows should show `Worker job` and expose cancel.
- Coverage reporting is useful later, but there is no enforced 80% coverage gate
  in this repo right now.
