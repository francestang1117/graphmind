# GraphMind

GraphMind is a Graph RAG-style document intelligence platform. It ingests files,
parses them into structured chunks, extracts entities and relationships, builds
an interactive knowledge graph, and lets users search or ask questions over the
uploaded content.

The project is intentionally honest about its current stage: the upload,
parsing, entity extraction, graph, search, chat fallback, async jobs,
observability, and safety layers are working MVPs. A production vector database,
GPT/OpenAI answer generation, and deeper graph querying are planned upgrades.

## What Works Today

- FastAPI backend with React + TypeScript frontend
- Drag-and-drop upload for Markdown, PDF, DOCX, TXT, JSON, CSV, HTML, Python,
  JavaScript, and TypeScript files
- Secure upload path with extension/MIME checks, SHA-256 deduplication, safe
  preview/download boundaries, and optional ClamAV scanning
- Local content-addressed storage by default, with optional S3/MinIO object
  storage for Docker/production-style runs
- SQLAlchemy-backed document metadata, parsed chunks, extracted entities,
  graph nodes/edges, and background job history
- Unified parser for Markdown, TXT, PDF, DOCX, code, JSON, CSV, and HTML
- Entity extraction with curated technical terms, alias cleanup, relation hints,
  and optional spaCy NER
- NetworkX-style knowledge graph with SQLAlchemy-backed node/edge persistence
- Local vector-style / hybrid retrieval search over parsed chunks
- Chat API that answers from retrieved document and graph context, with an
  optional future LLM provider path
- Redis-backed Celery worker and Celery Beat in Docker Compose
- WebSocket job progress, upload cancel/retry controls, recent-job UI,
  persistent job history, and scheduled reindex/cleanup tasks
- Email/password and optional GitHub OAuth login with JWT access tokens and
  HttpOnly refresh cookies
- Redis-backed rate limiting
- Prometheus-compatible `/metrics`
- Optional Sentry error tracking with release names based on `VERSION` and
  optional `GIT_SHA`
- 150+ backend tests covering the current core modules

## Project Status

| Area | Status | Notes |
| --- | --- | --- |
| Upload and storage | Working | Local SHA-256 content-addressed storage, duplicate detection, safe open/download |
| Parsing | Working MVP | Markdown, TXT, PDF, DOCX, code, JSON, CSV, HTML |
| Entity extraction | Working MVP | Domain rules, aliases, optional spaCy NER, noise filtering |
| Knowledge graph | Working MVP | Nodes/edges persist in relational tables; Neo4j-style querying is still planned |
| Search | Working MVP | Local hashed-vector / hybrid retrieval over parsed chunks |
| Chat | Working MVP | Retrieval-grounded local fallback; GPT/OpenAI provider planned |
| Async jobs | Working | Redis/Celery path, WebSocket progress, cancel/retry, job history |
| Persistence | Partial | Documents, parsed chunks/entities, graph nodes/edges, users, and jobs |
| Observability | Working MVP | Prometheus metrics and optional Sentry |
| File storage backend | Working MVP | Local by default; optional S3/MinIO keeps a local parser cache |
| Authentication | Working MVP | Email/password, optional GitHub OAuth, user-scoped workspaces |

## Quick Start

### Docker

Docker Compose starts the API, frontend, Postgres, Redis, Celery worker, Celery
Beat, and ClamAV.

```bash
docker compose up --build
```

Then open:

- Frontend: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`
- Metrics: `http://localhost:8000/metrics`

To include the current commit in Sentry release names:

```bash
GIT_SHA=$(git rev-parse HEAD) docker compose up --build
```

To test the optional MinIO path:

```bash
STORAGE_BACKEND=s3 docker compose --profile storage up --build
```

MinIO console: `http://localhost:9001` (`minioadmin` / `minioadmin`).
PostgreSQL is exposed on host port `5433` by default so it can run beside a
local PostgreSQL installation. Set `POSTGRES_PORT` to override it.

### Local Development

Backend:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
PYTHONPATH=backend uvicorn app.main:app --reload --app-dir backend --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Local mode keeps `CELERY_ENABLED=false` by default. Upload rows show `Local`
briefly after processing. Docker mode enables Celery, returns `job_id`, and lets
the frontend follow worker progress over WebSocket.

## API Snapshot

Base URL: `http://localhost:8000/api/v1`

- `POST /documents/upload` uploads, validates, stores, and queues a document.
- `GET /documents/` lists stored documents.
- `GET /documents/{filename}` returns metadata for one stored document.
- `GET /documents/{filename}/parsed` returns a parsed-structure summary.
- `GET /documents/{filename}/open` safely previews or downloads an uploaded file.
- `DELETE /documents/{filename}` deletes a stored document.
- `GET /jobs/` lists recent background jobs.
- `GET /jobs/{job_id}` returns a job snapshot.
- `POST /jobs/{job_id}/cancel` cancels a queued/running worker job.
- `WS /ws/jobs/{job_id}` streams worker progress.
- `GET /graph/` returns the current in-memory graph.
- `GET /graph/export?format=json|gexf|csv` exports the current graph view.
- `POST /search/` searches parsed document chunks.
- `POST /chat/` answers from retrieved document and graph context.
- `POST /scraper/` turns a public web page into a stored Markdown document.

More detail is in [docs/API.md](docs/API.md).

## Repository Layout

```text
GraphMind/
  backend/
    app/
      api/endpoints/       Documents, jobs, graph, search, chat, scraper, auth
      core/                Settings, DB, Celery, errors, metrics, rate limits, Sentry
      models/              SQLAlchemy persistence models
      services/            Storage, parsing, extraction, graph, search, jobs, QA
      tasks/               Celery document processing and cleanup tasks
      utils/               Upload validation
    tests/                 Backend unit and integration tests

  frontend/
    src/
      components/          Upload, jobs, graph, search, and chat panels
      hooks/               Upload, jobs, and graph data hooks
      services/            API client helpers
      stores/              Shared app state
      styles/              Main UI styling
      utils/               File display helpers

  docs/
    API.md
    DEVLOG.md
    ROADMAP.md
    STRUCTURE.md
    TESTING.md
  IMPROVEMENTS.md
  docker-compose.yml
```

The full current structure is tracked in [docs/STRUCTURE.md](docs/STRUCTURE.md).

## Testing

Run the backend suite:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests
```

Current backend coverage includes upload validation/storage, parsers, entity
extraction, graph/search/chat pipeline pieces, auth, rate limiting, Sentry,
metrics, WebSocket progress, job history, and cleanup behavior.

Build the frontend:

```bash
cd frontend
npm run build
```

More testing notes are in [docs/TESTING.md](docs/TESTING.md).

## Engineering Notes

- Development decisions and resolved issues are tracked in
  [docs/DEVLOG.md](docs/DEVLOG.md).
- Future work and technical debt are tracked in [IMPROVEMENTS.md](IMPROVEMENTS.md).
- The staged product roadmap is tracked in [docs/ROADMAP.md](docs/ROADMAP.md).
- Generated folders such as `.venv`, `node_modules`, `dist`, `__pycache__`,
  `.pytest_cache`, SQLite files, and uploaded files should not be committed.

## Near-Term Roadmap

1. Replace the local vector-search MVP with a real embedding model and vector DB.
2. Add OpenAI/GPT-backed answer generation behind the existing chat interface.
3. Add graph migrations and stronger persisted graph queries.
4. Run the GitHub OAuth and `AUTH_REQUIRED=true` flow behind staging HTTPS.
5. Expand the jobs panel with filters and a full task detail drawer.
