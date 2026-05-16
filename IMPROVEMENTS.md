# Improvements Backlog

This backlog keeps future ideas separate from the README so the GitHub landing page stays honest. It is organized by priority and should be updated as modules become real.

## High Priority

These items affect the core product experience and should come before advanced extensions.

### 1. User Authentication

Current state:

- JWT authentication exists as an MVP.
- Access tokens, refresh tokens, logout, and `/auth/me` are implemented.
- Auth can stay optional in local development through configuration.

Still needed:

- OAuth2/social login is not implemented.
- Frontend login/register screens still need to be connected cleanly.
- Team/workspace isolation is still future work.

### 2. Data Persistence

Current state:

- Uploaded file bytes are stored locally.
- Document metadata can be mirrored into SQLAlchemy-backed storage.
- Parsed chunks and extracted entities can be persisted.
- The knowledge graph itself is still rebuilt in memory.

Target:

- PostgreSQL for production document/user metadata.
- Either Neo4j or relational edge tables for graph persistence.
- Migrations before the schema becomes harder to change.

Possible direction:

```text
Document metadata -> PostgreSQL
Knowledge graph   -> Neo4j or PostgreSQL edge tables
Uploaded files    -> local disk first, S3/MinIO later
```

### 3. Real Vector Search

Current state:

- Search is implemented as a local hashed-vector MVP over parsed chunks.
- Hybrid scoring combines vector similarity with keyword overlap.
- Search excerpts are cleaned and centered near query terms.

Target:

- Replace the local vector MVP with real embedding models.
- Store vectors in ChromaDB or another vector database.
- Add persistent indexing instead of rebuilding from local state.

Local service option:

```bash
docker run -p 8001:8000 chromadb/chroma
```

## Medium Priority

These improve functionality once the core upload, parse, graph, and search path is stable.

### 4. WebSocket Progress

Current state:

- A WebSocket endpoint exists for Celery-style job progress.
- The processing pipeline reports progress through callbacks.
- Upload does not yet return a real Celery job id to the frontend.

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

- PDF parsing prefers `pdfplumber` and falls back to PyPDF2.
- Basic page chunks and table chunks are supported.

Target:

- Improve complex table extraction.
- Add image/OCR handling.
- Add stronger multi-column layout support if real documents need it.

### 6. Graph Export

Current state:

- Graph export is implemented for the current in-memory graph.

Implemented:

```text
GET /api/v1/graph/export?format=json
GET /api/v1/graph/export?format=gexf
GET /api/v1/graph/export?format=csv
```

Use cases:

- Cytoscape.js JSON for frontend visualization.
- GEXF for Gephi.
- CSV for spreadsheet workflows.

Still needed:

- Persistent graph storage before exports can represent long-term graph history.

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

Current state:

- spaCy model names are configurable.
- English is the primary model by default.
- Chinese `zh_core_web_sm` is an optional extra model.
- A small Chinese technical glossary maps terms such as `知识图谱`, `实体识别`, and `语义搜索` into the same canonical graph nodes as English terms.

Still needed:

- Install and test additional language models only when real documents need them.
- Add language detection if multilingual uploads become common.

### 9. Scheduled Jobs

Current state:

- `reindex_document(filename)` exists.
- `reindex_all_documents()` exists.
- Optional Celery beat schedule is configured behind `CELERY_REINDEX_ENABLED`.

Still needed:

- Run Celery worker/beat with Redis in a real deployment.
- Add cleanup tasks.
- Add relation-strength refresh/decay logic if the graph needs it.

## Technical Debt

| Area | Current State | Remaining Work |
| --- | --- | --- |
| Graph storage | In-memory graph rebuilt from documents | Add Neo4j or persistent relational edge tables |
| User system | JWT + refresh-token MVP | Add frontend auth flow, OAuth2/social login, and workspace/team boundaries |
| Metadata storage | SQLAlchemy-backed document metadata and parsed artifacts are available; local SQLite is the default dev path | Use PostgreSQL in production and add migrations |
| File storage | Local SHA-256 content-addressed storage | Add S3/MinIO backend for multi-instance deployments |
| Task queue | Processing pipeline, Celery-compatible task, and scheduled reindex task exist | Run real Celery worker/beat with Redis and return job ids from upload |
| WebSocket progress | Celery-style progress stream exists | Connect upload UI to real backend job ids |
| Error tracking | Structured API errors and backend logging exist | Add Sentry or another error tracking service |
| Logging | Most service-level `print()` paths have been replaced with logging | Move toward structured JSON logs for production |
| Tests | Pytest suite covers current backend modules | Add frontend tests and define coverage targets |
| API docs | FastAPI OpenAPI plus `docs/API.md` exist | Add more real request/response examples as endpoints stabilize |
| Monitoring | No metrics endpoint yet | Add Prometheus-compatible metrics and health dashboards |

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
- graph data from uploaded documents
- backend search results from parsed chunks
- chat replies from local retrieval context

## Suggested Next Step

The next practical milestone is:

1. Connect upload UI to real backend job ids and WebSocket progress.
2. Move production metadata to PostgreSQL with migrations.
3. Replace the local vector-search MVP with ChromaDB or another vector store.
4. Add graph persistence before the graph model becomes more complex.
