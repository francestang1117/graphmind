# Improvements Backlog

This backlog keeps future ideas separate from the README so the GitHub landing page stays honest. It is organized by priority and should be updated as modules become real.

## High Priority

These items affect the core product experience and should come before advanced extensions.

### 1. User Authentication

Current state:

- The app is effectively single-user.
- Upload/list/delete endpoints do not require a real account.
- `auth.py` is currently a placeholder.

Target:

```text
POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/auth/me
```

Likely implementation:

- JWT access tokens
- password hashing
- user table in the database
- frontend auth state

### 2. Data Persistence

Current state:

- Uploaded file bytes are stored locally.
- File metadata is stored in sidecar JSON files.
- The document model still uses an in-memory registry for some future workflow pieces.

Target:

- PostgreSQL + SQLAlchemy for document metadata, users, and processing records.
- Later, either Neo4j or a relational graph schema for graph persistence.

Possible direction:

```text
Document metadata -> PostgreSQL
Knowledge graph   -> Neo4j or PostgreSQL edge tables
Uploaded files    -> local disk first, S3/MinIO later
```

### 3. Real Vector Search

Current state:

- The frontend search panel exists.
- Backend semantic search is not implemented yet.

Target:

- Generate embeddings for document chunks.
- Store vectors in ChromaDB or another vector database.
- Add `/api/v1/search` endpoint.

Local service option:

```bash
docker run -p 8001:8000 chromadb/chroma
```

## Medium Priority

These improve functionality once the core upload, parse, graph, and search path is stable.

### 4. WebSocket Progress

Current state:

- WebSocket endpoint exists as a placeholder.
- Upload progress is mostly frontend upload progress, not backend processing progress.

Target:

```python
@app.websocket("/ws/process/{job_id}")
async def processing_progress(websocket: WebSocket, job_id: str):
    await websocket.accept()
    while True:
        progress = await get_job_progress(job_id)
        await websocket.send_json(progress)
        if progress["status"] == "done":
            break
```

Likely needs:

- job table or Redis job state
- background worker updates
- frontend progress subscription hook

### 5. PDF Parsing Upgrade

Current state:

- PDF parsing uses PyPDF2 for basic text extraction.

Target:

- Use `pdfplumber` for stronger table and layout extraction.

Possible dependency:

```bash
pip install pdfplumber
```

### 6. Graph Export

Current state:

- Graph backend is planned.
- Graph UI currently uses demo/fallback data.

Target:

```text
GET /api/v1/graph/export?format=json
GET /api/v1/graph/export?format=gexf
GET /api/v1/graph/export?format=csv
```

Use cases:

- Cytoscape.js JSON for frontend visualization.
- GEXF for Gephi.
- CSV for spreadsheet workflows.

## Low Priority

These are ecosystem features that become valuable after the main graph/search product works.

### 7. Browser Extension

Goal:

```text
User browses a page -> clicks extension -> page content enters GraphMind
```

Possible stack:

- Chrome Extension Manifest V3
- Readability-style article extraction
- normal document ingestion pipeline

### 8. Multilingual Support

Goal:

- Chinese and English document understanding.
- Language-aware entity extraction.

Possible direction:

```bash
python -m spacy download zh_core_web_sm
```

### 9. Scheduled Jobs

Goal:

- Re-index stale documents.
- Refresh graph relation strength.
- Run cleanup tasks.

Possible direction:

```python
@celery.task
def reindex_document(filename: str):
    pipeline.process(filename)
```

## Technical Debt

| Area | Current State | Improvement |
| --- | --- | --- |
| User system | No real login | JWT + OAuth2-style flow |
| Metadata storage | Local sidecars / in-memory pieces | PostgreSQL + SQLAlchemy |
| Graph storage | Not implemented yet | Neo4j or persistent edge tables |
| File storage | Local disk | S3 / MinIO later |
| Task queue | FastAPI background tasks | Celery + Redis for heavy jobs |
| WebSocket progress | Placeholder | Real job progress events |
| Error tracking | Local logs | Sentry or similar |
| Logging | Mixed simple logging/prints | Structured logging |
| Tests | Backend coverage for current modules | Add frontend tests and coverage targets |
| API docs | Auto-generated OpenAPI + docs/API.md | Add examples as endpoints mature |
| Monitoring | None | Prometheus metrics |

## Frontend Notes

The current frontend contains four main panels:

- Documents
- Graph
- Search
- Chat

What is real now:

- document upload
- drag-and-drop file selection
- upload progress rows
- document list
- delete action
- Markdown parse summary viewer

What is currently demo/fallback:

- graph data
- search results
- chat replies

The API wrapper already has functions for future graph/search/chat endpoints, but the panels fall back gracefully when those backend modules are missing.

## Suggested Next Step

The next practical milestone is:

1. Keep Docker running with the backend and frontend.
2. Expand the Markdown viewer to show full structure and chunks.
3. Add persistent document metadata.
4. Build the first graph extraction module from Markdown chunks.
