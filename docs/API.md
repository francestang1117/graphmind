# API Reference

Base URL: `http://localhost:8000/api/v1`  
Auth: `Authorization: Bearer <access_token>` when `AUTH_REQUIRED=true`. In local development the same routes can fall back to the `local-dev` user while `AUTH_REQUIRED=false`.  
Interactive docs: `http://localhost:8000/docs`

---

## Operations

### `GET /metrics`

Prometheus scrape endpoint. It is outside the `/api/v1` prefix.

```bash
curl http://localhost:8000/metrics
```

It includes request counters, request latency, upload counts, pipeline timing,
search counts, and chat counts. Set `METRICS_ENABLED=false` to hide it in local
runs where you do not want the endpoint.

---

## Auth

### `GET /auth/providers`

Returns the external login methods configured on the backend:

```json
{ "github": true }
```

### GitHub OAuth

`GET /auth/github/start?return_origin=http://localhost:5173` starts the GitHub
authorization-code flow with `state` and PKCE. GitHub returns to
`GET /auth/github/callback`; the callback creates or finds the local user, sets
the normal refresh cookie, and sends a one-time handoff code to the opener.

The frontend exchanges that code once:

```http
POST /auth/oauth/exchange
Content-Type: application/json

{ "code": "one-time-code" }
```

GitHub's numeric user ID is stored in `oauth_identities` and linked to the
existing local user. This keeps the same workspace if the GitHub username or
email changes.

### `POST /auth/register`

Create a new account.

```json
// Request
{ "email": "you@example.com", "password": "a-long-passphrase", "name": "Alice" }

// Response 201
{ "access_token": "eyJ...", "refresh_token": "abc123...", "token_type": "bearer" }
```

Passwords must contain at least 8 characters, fit within bcrypt's 72-byte
input limit, and must not match the small built-in list of common passwords.

### `POST /auth/login`

Authenticate with form data (OAuth2 compatible).

```
Content-Type: application/x-www-form-urlencoded
username=you@example.com&password=secret
```

### `POST /auth/refresh`

Exchange a refresh token for a new access token. Browsers use the HttpOnly
`graphmind_refresh` cookie set during registration or login. API clients can
still send the token in JSON:

```json
{ "refresh_token": "abc123..." }
```

### `POST /auth/logout`

Invalidate a refresh token immediately and clear the browser cookie. The JSON
body remains available for non-browser clients:

```json
{ "refresh_token": "abc123..." }
```

### `GET /auth/me`

```json
{
  "id": "abc123",
  "email": "you@example.com",
  "name": "Alice",
  "created_at": "..."
}
```

---

## Documents

### `POST /documents/upload`

Upload a file. The file is validated and stored immediately. Local dev queues
parsing through FastAPI background work; when `CELERY_ENABLED=true`, parsing is
sent to Redis/Celery and the response includes a `job_id`.

```bash
curl -X POST /api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@report.md"
```

```json
// Response 200
{
  "filename": "a1b2c3d4e5f6a7b8.md",
  "original_filename": "report.md",
  "file_size": 14500,
  "file_type": ".md",
  "file_hash": "a1b2c3d4...",
  "status": "uploaded",
  "job_id": "4c1b2..."
}
```

**Validation pipeline (all in memory, before disk write):**

1. Filename and extension are normalized.
2. Unsupported extension → `400`.
3. Empty or oversized file → `400`.
4. Text-like files must decode as text; binary formats keep stricter signature checks.
5. Unsafe content patterns are rejected.
6. ClamAV scan runs when `VIRUS_SCAN_ENABLED=true`.
7. File is written to content-addressed local storage.
8. Duplicate content returns `409`.
9. Parser work is queued as FastAPI background work or a Celery job.

### `GET /documents/`

```json
{ "total": 3, "files": [{ "filename": "...", "file_size": 14500, ... }] }
```

Pagination is not implemented yet; the current endpoint returns all visible files for the current user.

### `GET /documents/{filename}`

Single file metadata.

### `GET /documents/{filename}/parsed`

Returns a compact parsed summary for supported formats: Markdown, TXT, PDF, DOCX, Python, JavaScript, TypeScript, JSON, CSV, and HTML.

```json
{
  "title": "Report Title",
  "format": "md",
  "headers_count": 12,
  "sections_count": 8,
  "chunks_count": 18,
  "code_blocks_count": 3,
  "tables_count": 0,
  "entities_count": 6,
  "word_count": 2400,
  "reading_time": 10,
  "languages": ["python"]
}
```

### `DELETE /documents/{filename}`

Deletes the stored file, soft-deletes the database document record when persistence is enabled, and clears cached parsed artifacts for that file.

### `GET /documents/{filename}/open`

Open or download the original upload through a guarded file response.

Passive formats such as `.pdf`, `.txt`, `.md`, `.json`, and `.csv` can open inline. Active formats such as HTML and code are forced to download. Responses include `nosniff`, sandbox-style CSP, and private no-store cache headers.

---

## Knowledge Graph

Graph endpoints read persisted `graph_nodes` / `graph_edges` rows when they
exist. If a workspace has not been reprocessed since graph persistence was
added, the API falls back to rebuilding the graph from stored documents.

### `GET /graph`

Full graph for visualisation:

```json
{
  "nodes": [{
    "id": "abc",
    "label": "TensorFlow",
    "type": "FRAMEWORK",
    "size": 15.4,
    "importance": 0.67,
    "connections": 4
  }],
  "edges": [["node1", "node2"]],
  "edge_details": [{
    "source": "node1",
    "target": "node2",
    "type": "USES",
    "weight": 3,
    "confidence": 0.9
  }]
}
```

`weight` counts supporting relation evidence across document slices. The visual
response maps weighted connectivity to a normalized `importance` score, which
the frontend uses for node size.

### `GET /graph/stats`

```json
{
  "total_nodes": 247,
  "total_edges": 189,
  "node_types": { "CONCEPT": 80, "FRAMEWORK": 30 },
  "density": 0.043
}
```

### `GET /graph/nodes/{node_id}`

Node detail with neighbours:

```json
{
  "node": { "id": "...", "label": "...", "type": "..." },
  "neighbors": [{ "node": {...}, "relation": { "type": "USES" } }]
}
```

### `GET /graph/search?q=python&node_type=CONCEPT&limit=10`

Search graph nodes by label.

### `GET /graph/debug`

Development-only graph shape with full node/edge metadata and stats.

### `GET /graph/export?format=json`

Export the current graph as Cytoscape.js JSON. This is useful for frontend
graph tools or for saving a portable graph snapshot.

```json
{
  "format": "cytoscape",
  "elements": {
    "nodes": [{ "data": { "id": "node-id", "label": "Python", "type": "PROGRAMMING_LANGUAGE" } }],
    "edges": [{ "data": { "source": "doc-id", "target": "node-id", "label": "CONTAINS" } }]
  }
}
```

### `GET /graph/export?format=gexf`

Export the current graph as GEXF XML for Gephi and other graph analysis tools.
Node and edge attributes include type, confidence, sources, and edge weight.

### `GET /graph/export?format=csv`

Export the current graph as a single CSV table for spreadsheet tools. Rows use
`kind=node` or `kind=edge`, so the file can be filtered without needing two
separate downloads.

---

## Semantic Search

### `POST /search`

```json
// Request
{ "query": "neural network backpropagation", "limit": 10, "search_type": "hybrid" }

// Response
{
  "query": "neural network backpropagation",
  "results": [
    {
      "title": "Backpropagation",
      "type": "CONCEPT",
      "score": 0.94,
      "excerpt": "Training algorithm that computes gradients...",
      "source": "neural-nets.pdf"
    }
  ]
}
```

`search_type`: `"semantic"` | `"hybrid"` (recommended). Keyword-only search is not exposed as a separate API mode yet.

---

## AI Chat

### `POST /chat`

```json
// Request
{ "message": "What frameworks are used in my documents?", "conversation_id": null }

// Response
{
  "answer": "Your documents reference TensorFlow (Google), PyTorch (Meta)...",
  "sources": [{ "document": "ml-intro.md", "relevance": "87%" }],
  "conversation_id": "uuid-here",
  "mode": "local",
  "fallback_reason": "openai_not_configured"
}
```

Pass `conversation_id` from previous response to continue a conversation.

Set `"stream": true` to receive the same answer as Server-Sent Events.

`mode` is `"local"` while the GPT provider is not configured. In that case,
`fallback_reason` explains why the answer came from the local retrieval fallback
instead of the optional LLM path.

---

## WebSocket

### `POST /jobs/{job_id}/ws-ticket`

Create a one-use WebSocket ticket after the current user has been verified as
the owner of the job:

```json
{ "ticket": "short-lived-random-value", "expires_in": 60 }
```

The ticket is valid for 60 seconds, is tied to this `job_id`, and is removed
when the WebSocket consumes it. It is not an access token and cannot be used
with the normal HTTP API.

### `WS /ws/jobs/{job_id}`

Call the ticket endpoint with the normal Bearer token first, then connect with
the returned ticket:

```js
const { ticket } = await fetch("http://localhost:8000/api/v1/jobs/job123/ws-ticket", {
  method: "POST",
  headers: { Authorization: `Bearer ${accessToken}` },
}).then((response) => response.json());

const ws = new WebSocket(`ws://localhost:8000/ws/jobs/job123?ticket=${encodeURIComponent(ticket)}`);
ws.onmessage = (e) => {
  const { state, pct, step, result, error } = JSON.parse(e.data);
  // state: PENDING | PROGRESS | SUCCESS | FAILURE
};
```

Connection closes automatically when the job reaches a terminal state.

When `CELERY_ENABLED=true`, the upload response returns `job_id`. The frontend
requests a ticket and then connects to this WebSocket URL to show real
processing progress. A reusable access token is never put in the WebSocket
request URL.

## Jobs

### `GET /jobs/`

Return recent background jobs for the current user. This is the lightweight
history behind upload processing; the UI does not have a full job center yet.

```json
{
  "total": 1,
  "jobs": [
    {
      "job_id": "4c1b2...",
      "document_id": "hash.md",
      "original_filename": "report.md",
      "status": "SUCCESS",
      "step": "Done",
      "progress": 100,
      "error": "",
      "created_at": "2026-05-29T00:00:00+00:00",
      "updated_at": "2026-05-29T00:00:03+00:00",
      "finished_at": "2026-05-29T00:00:03+00:00"
    }
  ]
}
```

### `GET /jobs/{job_id}`

Return the latest job snapshot without keeping a WebSocket open.

```json
{
  "state": "PROGRESS",
  "pct": 45,
  "step": "Extracting entities"
}
```

### `POST /jobs/{job_id}/cancel`

Ask the worker to stop a queued or running job. The frontend uses this for the
cancel button on an active upload row.

```json
{
  "state": "REVOKED",
  "pct": 0,
  "step": "Cancelled"
}
```

---

## Web Scraper

### `POST /scraper`

Fetch a public web page, extract readable text, and store it as a normal
Markdown document so search, graph, and chat can reuse the same pipeline.

```json
// Request
{ "url": "https://example.com/article" }

// Response
{
  "filename": "hash.md",
  "original_filename": "web-example.com-article-title.md",
  "file_hash": "hash",
  "file_size": 2048,
  "source_url": "https://example.com/article",
  "title": "Article Title",
  "excerpt": "First readable text from the page...",
  "status": "indexed"
}
```

The scraper only accepts `http` and `https` URLs, allows only globally routable
destination addresses, follows redirects with the same checks, limits response
size, and only ingests readable text/HTML responses.

---

## Planned Later

These are roadmap items, not current endpoints:

- `GET /graph/gaps`
- video generation endpoints
- browser extension ingestion

---

## Error Responses

Most endpoint errors use FastAPI's normal `detail` field. Common app-level
failures also include a stable `code` that the frontend can branch on:

```json
{
  "detail": "This file has already been uploaded.",
  "code": "duplicate_file",
  "details": {
    "existing_filename": "abc.md"
  }
}
```

Current app-level codes include:

- `upload_validation_failed`
- `duplicate_file`
- `malware_detected`
- `virus_scanner_unavailable`
- `parse_failed`
- `stored_file_path_invalid`
- `stored_file_missing`
- `storage_operation_failed`
- `database_operation_failed`

| Code | Meaning                                      |
| ---- | -------------------------------------------- |
| 400  | Validation failed (bad file, bad request)    |
| 401  | Missing or invalid JWT                       |
| 404  | Resource not found                           |
| 409  | Conflict (e.g. email already registered)     |
| 422  | Request body validation error                |
| 429  | Rate limit exceeded (see Retry-After header) |
| 503  | Dependency unavailable                       |
| 500  | Internal server error                        |
