# GraphMind

GraphMind is an early-stage document ingestion and knowledge graph workspace. The current version focuses on the foundation: uploading documents, validating them safely, storing files locally, parsing supported formats, and presenting the workflow in a React interface.

The project is intentionally built in small phases. Knowledge graph construction, semantic search, and AI chat are represented in the UI as planned workflows, but their backend modules are not fully implemented yet.

## Current Features

- FastAPI backend with `/api/v1/documents` endpoints
- React + TypeScript frontend with document upload, graph, search, and chat panels
- Drag-and-drop document upload UI with progress states
- File validation before storage
- SHA-256 content-addressed local file storage
- Document metadata listing, detail lookup, and deletion
- Markdown parsing helper and summary viewer for headings, links, code blocks, sections, chunks, and metadata
- Multi-format parser for Markdown, TXT, PDF, DOCX, Python, JavaScript, TypeScript, JSON, CSV, and HTML files
- Lightweight Docker Compose setup for the API and frontend

## Project Status

| Area | Status | Notes |
| --- | --- | --- |
| Project setup | Done | FastAPI, React, Docker Compose |
| File upload | Done | Validation, storage, list/get/delete |
| Markdown parsing | In progress | Parser is wired into upload background work with a small summary viewer |
| PDF/DOCX/code/data parsing | Basic | Parser functions exist for PDF, DOCX, code, JSON, CSV, and HTML |
| Knowledge graph | Demo UI only | Backend graph engine is planned |
| Search | Demo UI only | Backend semantic search is planned |
| AI chat | Demo UI only | Backend RAG/chat is planned |

## Quick Start

### Docker

```bash
docker compose up --build
```

Then open:

- Frontend: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`

### Local Development

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## API

Base URL: `http://localhost:8000/api/v1`

- `POST /documents/upload` uploads and validates a document.
- `GET /documents/` lists stored documents.
- `GET /documents/{filename}` returns metadata for one stored document.
- `DELETE /documents/{filename}` deletes a stored document.

Interactive docs are available at `http://localhost:8000/docs`.

## Repository Layout

```text
GraphMind/
  IMPROVEMENTS.md
  backend/
    app/
      api/endpoints/       FastAPI route modules
      core/                Settings, Celery-compatible adapter, rate-limit shim
      models/              In-memory document metadata model
      services/            Validation, storage, parsing helpers
      tasks/               Background parsing entrypoints
      utils/               Upload validation utilities
    tests/
    Dockerfile
    requirements.txt

  frontend/
    src/
      components/          App panels and upload UI pieces
      hooks/               Upload and graph data hooks
      services/            Axios API wrapper
      stores/              Small Zustand store
      styles/              Main app styling
      utils/               File display helpers
    Dockerfile
    package.json

  docs/
    API.md
    DEVLOG.md
    ROADMAP.md
    STRUCTURE.md
  docker-compose.yml
```

## Engineering Notes

Development notes and resolved issues are tracked in [docs/DEVLOG.md](docs/DEVLOG.md). This is where practical fixes, project-stage decisions, and lessons learned are recorded without cluttering the README.

Prioritized future improvements and technical debt are tracked in [IMPROVEMENTS.md](IMPROVEMENTS.md).

## Roadmap

The full staged roadmap is tracked in [docs/ROADMAP.md](docs/ROADMAP.md). The near-term sequence is:

1. Expand the Markdown viewer from summary stats to full structure/chunks.
2. Add persistent document metadata storage.
3. Build the first graph extraction module.
4. Add graph persistence and graph API endpoints.
5. Add semantic search and vector storage.
6. Add graph-augmented AI chat.
7. Explore extensions such as web capture, code repository analysis, transcription, and graph-to-video generation.

## Development Notes

- The current Docker setup runs only the API and frontend. Redis, Postgres, ChromaDB, MinIO, and ClamAV are future infrastructure choices.
- Generated folders such as `.venv`, `node_modules`, `dist`, `__pycache__`, `.pytest_cache`, and uploaded files should not be committed.
- The frontend currently includes demo data for graph, search, and chat so the intended product flow is visible before those backend modules are finished.
