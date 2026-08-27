# Project Structure

This file tracks the structure that exists in the repository today. Planned
modules are kept in `ROADMAP.md` instead of being described here as finished
code.

```text
GraphMind/
├── README.md
├── IMPROVEMENTS.md
├── docker-compose.yml
├── docs/
│   ├── API.md
│   ├── DEVLOG.md
│   ├── ROADMAP.md
│   ├── STRUCTURE.md
│   └── TESTING.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── endpoints/
│   │   │       ├── auth.py
│   │   │       ├── chat.py
│   │   │       ├── documents.py
│   │   │       ├── documents_with_markdown.py
│   │   │       ├── graph.py
│   │   │       ├── jobs.py
│   │   │       ├── search.py
│   │   │       └── websocket.py
│   │   ├── core/
│   │   │   ├── celery_app.py
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── errors.py
│   │   │   ├── metrics.py
│   │   │   ├── rate_limit.py
│   │   │   └── sentry.py
│   │   ├── models/
│   │   │   ├── document.py
│   │   │   └── persistence.py
│   │   ├── services/
│   │   │   ├── document_parser.py
│   │   │   ├── document_repository.py
│   │   │   ├── document_service.py
│   │   │   ├── entity_extractor.py
│   │   │   ├── file_storage.py
│   │   │   ├── graph_builder_enhanced.py
│   │   │   ├── job_repository.py
│   │   │   ├── markdown_parser.py
│   │   │   ├── parsed_artifact_repository.py
│   │   │   ├── persistence_service.py
│   │   │   ├── qa_engine.py
│   │   │   ├── vector_store.py
│   │   │   └── virus_scanner.py
│   │   ├── tasks/
│   │   │   ├── __init__.py
│   │   │   └── process_document.py
│   │   └── utils/
│   │       └── file_validator.py
│   └── tests/
│       ├── integration/
│       │   ├── test_documents_markdown.py
│       │   └── test_upload_api.py
│       ├── unit/
│       │   ├── test_file_storage.py
│       │   └── test_file_validator.py
│       ├── test_auth.py
│       ├── test_document_parser_pdf.py
│       ├── test_document_repository.py
│       ├── test_entity_extractor.py
│       ├── test_errors.py
│       ├── test_full_pipeline.py
│       ├── test_markdown_parser.py
│       ├── test_parsed_artifact_repository.py
│       ├── test_persistence_service.py
│       ├── test_qa_engine.py
│       ├── test_rate_limit.py
│       ├── test_vector_store.py
│       ├── test_virus_scanner.py
│       └── test_websocket.py
└── frontend/
    ├── Dockerfile
    ├── README.md
    ├── package.json
    └── src/
        ├── App.css
        ├── App.tsx
        ├── main.tsx
        ├── assets/
        ├── components/
        │   ├── ChatPanel.tsx
        │   ├── GraphPanel.tsx
        │   ├── SearchPanel.tsx
        │   ├── UploadPanel.tsx
        │   └── upload/
        │       ├── DocumentList.tsx
        │       ├── DocumentOverview.tsx
        │       ├── DocumentRow.tsx
        │       ├── FileIcon.tsx
        │       ├── UploadDropzone.tsx
        │       └── UploadRow.tsx
        ├── hooks/
        │   ├── useGraph.ts
        │   └── useUpload.ts
        ├── services/
        │   └── api.ts
        ├── stores/
        │   └── appStore.ts
        ├── styles/
        │   └── index.css
        ├── types/
        │   └── index.ts
        └── utils/
            └── fileMeta.ts
```

Generated folders such as `__pycache__`, `.pytest_cache`, local upload folders,
SQLite files, and virtual environments are intentionally left out of this map.

## Backend Notes

- `main.py` wires the FastAPI app, CORS, lifespan startup, rate limiting, API
  error handlers, `/api/v1/*` routes, and the WebSocket router.
- `api/__init__.py` registers the active REST routers: auth, documents, graph,
  search, and chat.
- `documents.py` is the active upload/list/detail/delete/open-file API. It uses
  validation, optional virus scanning, content-hash deduplication, storage, parse
  caching, user scoping, and stable application error codes.
- `documents_with_markdown.py` is still a helper module for cached parsing and
  parsed-structure responses. It is used by document/search/graph/chat code, but
  it is not registered as its own router.
- `auth.py` handles email/password login, GitHub OAuth, JWT access tokens,
  HttpOnly refresh cookies, and the optional local-dev workspace.
- `graph.py`, `search.py`, and `chat.py` are connected to real uploaded content.
  They are MVP implementations, not demo-only screens anymore.
- `jobs.py` exposes small HTTP controls for worker jobs: check status and cancel.
- `websocket.py` exposes Celery-style job progress snapshots. Upload can return
  a Celery job id, and the frontend upload hook can watch it.

## Core Layer

- `config.py` holds Pydantic settings and environment defaults.
- `database.py` provides SQLAlchemy setup. Local development can use SQLite;
  PostgreSQL is the intended production direction.
- `errors.py` centralizes application error payloads and FastAPI handlers.
- `metrics.py` exposes `/metrics` and records request, upload, search, chat,
  and pipeline counters for Prometheus.
- `rate_limit.py` wraps slowapi. Redis-backed limits are supported, with a local
  fallback for development.
- `sentry.py` initializes optional Sentry reporting when a production DSN is
  configured.
- `celery_app.py` provides Celery configuration and a small eager/local fallback
  so tests can exercise task-style progress without a worker. Docker Compose
  runs the Redis-backed worker and beat services for the production-like path.

## Services

- `file_storage.py` stores files by content hash and keeps file metadata.
- `object_storage.py` adds the optional S3/MinIO backend. It still keeps a
  local cache because the current parsers work with filesystem paths.
- `document_service.py` coordinates validation, storage, persistence, parsing,
  duplicate detection, and document lifecycle actions.
- `document_repository.py` stores document metadata in the database, with a
  sidecar fallback for local development.
- `persistence_service.py` and `parsed_artifact_repository.py` persist parsed
  chunks and extracted entities.
- `graph_repository.py` persists graph nodes and edges in relational tables.
  The API reads those rows first and only rebuilds from documents when no
  persisted graph exists yet.
- `job_repository.py` stores recent background job state so upload work remains
  visible after refreshes and old finished jobs can be cleaned up.
- `pipeline.py` is the current single-document processing path used after
  upload and by the Celery-compatible task: parse, persist artifacts, extract
  entities/relations, persist graph nodes/edges, update the in-memory graph,
  and index search chunks.
- `document_parser.py` is the unified parser for Markdown, TXT, PDF, DOCX,
  Python, JavaScript, TypeScript, JSON, CSV, and HTML. PDF parsing prefers
  pdfplumber and falls back to PyPDF2.
- `markdown_parser.py` is the older dedicated Markdown parser used by tests and
  earlier module work.
- `entity_extractor.py` combines domain rules, optional spaCy NER, noise
  filtering, aliasing, and relation hints.
- `graph_builder_enhanced.py` builds the current in-memory graph view from
  documents, entities, and relations. The graph API can also export that view
  as Cytoscape JSON, GEXF, or CSV.
- `vector_store.py` is the local vector-search MVP over parsed chunks.
- `qa_engine.py` answers chat questions from search/graph context and has a
  visible local fallback while the GPT provider is not configured.
- `web_scraper.py` fetches public web pages, strips noisy HTML, and stores the
  readable result as a normal Markdown document.
- `virus_scanner.py` is the ClamAV integration wrapper. Scanning is optional and
  depends on clamd being configured.

## Frontend Notes

- The frontend is a Vite React + TypeScript app.
- `UploadPanel.tsx` is split into smaller upload components so the first module
  is easier to read and maintain.
- `GraphPanel.tsx`, `SearchPanel.tsx`, and `ChatPanel.tsx` call backend APIs
  instead of relying only on static demo data.
- `services/api.ts` centralizes HTTP calls.
- `stores/appStore.ts` keeps shared UI state.
- `hooks/useUpload.ts` and `hooks/useGraph.ts` keep upload and graph data
  fetching out of the main components. Upload also watches Celery job progress
  when the backend returns a `job_id`, and keeps enough local state to cancel or
  retry an active upload row. Upload rows also show whether the work is running
  locally or as a worker job, which helps during development.
- `hooks/useJobs.ts` and `components/upload/JobHistory.tsx` show recent
  processing jobs in the Documents panel, including status, step, progress,
  errors, and cancel controls for active worker jobs.

## Test Coverage

The backend currently has tests for:

- auth
- upload API behavior
- file validation and storage
- Markdown and unified parsing
- PDF page/table parsing
- document metadata persistence
- parsed chunk/entity persistence
- entity extraction
- graph/search/QA pipeline pieces
- rate limiting
- virus scanner behavior
- WebSocket job snapshots
- job status/cancel endpoints
- job history persistence and cleanup
- application error payloads
- metrics wiring through the FastAPI app

Run the current backend suite with:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests
```

## Still Early

The project now has real modules for upload, parsing, entity extraction, graph,
search, chat, auth, rate limiting, persistence, metrics, Celery workers, and
WebSocket progress. The main things that are still early are:

- deeper graph persistence tooling beyond the current node/edge tables
- production-grade user/workspace isolation across every artifact
- staging OAuth and `AUTH_REQUIRED=true` checks behind HTTPS
- GPT-backed answer generation
- richer relation extraction and graph quality tuning
- a real Prometheus/Grafana deployment around the `/metrics` endpoint
