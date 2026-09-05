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
│   │   │   ├── workspace_scope.py
│   │   │   └── endpoints/
│   │   │       ├── auth.py
│   │   │       ├── chat.py
│   │   │       ├── documents.py
│   │   │       ├── documents_with_markdown.py
│   │   │       ├── graph.py
│   │   │       ├── jobs.py
│   │   │       ├── scraper.py
│   │   │       ├── search.py
│   │   │       ├── websocket.py
│   │   │       └── workspaces.py
│   │   ├── core/
│   │   │   ├── celery_app.py
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── errors.py
│   │   │   ├── metrics.py
│   │   │   ├── rate_limit.py
│   │   │   ├── sentry.py
│   │   │   └── workspace.py
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
│   │   │   ├── medical/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── analyzer.py
│   │   │   │   ├── document_classifier.py
│   │   │   │   ├── models.py
│   │   │   │   ├── paper_structure_parser.py
│   │   │   │   ├── repository.py
│   │   │   │   └── section_normalizer.py
│   │   │   ├── parsed_artifact_repository.py
│   │   │   ├── persistence_service.py
│   │   │   ├── qa_engine.py
│   │   │   ├── vector_store.py
│   │   │   ├── virus_scanner.py
│   │   │   ├── web_scraper.py
│   │   │   ├── websocket_ticket.py
│   │   │   └── workspace_repository.py
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
│       ├── test_medical_analyzer.py
│       ├── test_medical_api.py
│       ├── test_medical_classifier.py
│       ├── test_medical_repository.py
│       ├── test_parsed_artifact_repository.py
│       ├── test_paper_structure_parser.py
│       ├── test_persistence_service.py
│       ├── test_qa_engine.py
│       ├── test_rate_limit.py
│       ├── test_vector_store.py
│       ├── test_virus_scanner.py
│       ├── test_websocket.py
│       └── test_workspace_isolation.py
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
        │       ├── JobHistory.tsx
        │       ├── UploadDropzone.tsx
        │       └── UploadRow.tsx
        ├── hooks/
        │   ├── useGraph.ts
        │   ├── useJobs.ts
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
  search, chat, scraper, jobs, and workspaces.
- `documents.py` is the active upload/list/detail/delete/open-file API. It uses
  validation, optional virus scanning, content-hash deduplication, storage, parse
  caching, user scoping, and stable application error codes.
- `documents_with_markdown.py` is still a helper module for cached parsing and
  parsed-structure responses. It is used by document/search/graph/chat code, but
  it is not registered as its own router.
- `services/medical/` classifies medical documents, normalizes paper headings,
  builds page-aware sections and chunks, and stores the resulting analysis.
- `auth.py` handles email/password login, GitHub OAuth, JWT access tokens,
  HttpOnly refresh cookies, and the optional local-dev workspace.
- `workspaces.py` creates and lists account-owned research projects. The
  existing APIs use the user's stable default workspace when no ID is given.
- `graph.py`, `search.py`, and `chat.py` are connected to real uploaded content.
  They are MVP implementations, not demo-only screens anymore.
- `jobs.py` exposes small HTTP controls for worker jobs: check status and cancel.
- `jobs.py` also issues one-use, job-bound WebSocket tickets after ownership is
  checked.
- `websocket.py` exposes Celery-style job progress snapshots. The socket accepts
  those short-lived tickets instead of reusable access tokens.

## Core Layer

- `config.py` holds Pydantic settings and environment defaults.
- `database.py` provides SQLAlchemy setup. Local development can use SQLite;
  PostgreSQL is the intended production direction.
- `workspace.py` defines the stable compatibility workspace ID used for older
  routes and rows created before project selection existed.
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
- `medical/repository.py` stores the medical profile and structured paper
  sections with the same user, workspace, and document boundary.
- `graph_repository.py` persists graph nodes and edges in relational tables.
  The API reads those rows first and only rebuilds from documents when no
  persisted graph exists yet.
- `job_repository.py` stores recent background job state so upload work remains
  visible after refreshes and old finished jobs can be cleaned up.
- `websocket_ticket.py` stores short-lived job-bound socket tickets in Redis,
  with an in-memory fallback for local development.
- `workspace_repository.py` stores account-owned research project metadata and
  creates the default workspace used by the compatibility routes.
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
- workspace ownership, same-file multi-project support, and graph isolation
- medical document classification, multilingual section parsing, paper analysis
  persistence, and the medical analysis API

Run the current backend suite with:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests
```

## Current Scope

Workspace-scoped persistence is ready for the first V2 research workflow. This
branch adds the first medical analysis layer:

- explainable medical document classification with an `unknown` fallback
- English, Chinese, and Japanese paper section normalization
- page-aware paper sections and section-aware chunks with source ranges
- study cards, sentence-level citations, and paper-focused chat are still next
- the frontend workspace picker and research-card pages
- staging OAuth and `AUTH_REQUIRED=true` checks behind HTTPS and secure cookies

## Still Early

The project now has real modules for upload, parsing, entity extraction, graph,
search, chat, auth, rate limiting, persistence, metrics, Celery workers,
WebSocket progress, and the first medical analysis layer. The remaining gaps are:

- deeper graph persistence tooling beyond the current node/edge tables
- study cards, sentence-level citations, and paper-focused chat
- the frontend workspace picker and research-card pages
- staging OAuth and `AUTH_REQUIRED=true` checks behind HTTPS
- GPT-backed answer generation
- richer relation extraction and graph quality tuning
- a real Prometheus/Grafana deployment around the `/metrics` endpoint
