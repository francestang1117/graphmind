# API Reference

Base URL: `http://localhost:8000/api/v1`

Interactive OpenAPI docs: `http://localhost:8000/docs`

## Health

### `GET /health`

Returns the backend status and upload directory information.

```json
{
  "status": "healthy",
  "upload_dir_exists": true,
  "upload_dir": "/path/to/uploads"
}
```

## Documents

### `POST /documents/upload`

Upload one document. The backend validates the file in memory, stores it using a SHA-256 content-addressed filename, and queues lightweight background parsing.

Supported extensions:

- `.md`
- `.pdf`
- `.txt`
- `.docx`
- `.py`
- `.js`
- `.ts`

Example:

```bash
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@notes.md"
```

Response:

```json
{
  "filename": "98f0c2....md",
  "original_filename": "notes.md",
  "file_size": 14500,
  "file_type": ".md",
  "file_hash": "98f0c2...",
  "status": "uploaded"
}
```

### `GET /documents/`

List stored document metadata.

```json
{
  "files": [
    {
      "filename": "98f0c2....md",
      "original_filename": "notes.md",
      "file_size": 14500,
      "file_extension": ".md",
      "file_type": ".md",
      "file_hash": "98f0c2...",
      "mime_type": "text/plain",
      "created_at": "2026-04-28T00:00:00+00:00",
      "modified_at": "2026-04-28T00:00:00+00:00"
    }
  ],
  "total": 1
}
```

### `GET /documents/{filename}`

Return metadata for a single stored document.

### `DELETE /documents/{filename}`

Delete a stored document and its metadata sidecar.

```json
{ "message": "File deleted" }
```

## Markdown Parsing

Markdown parsing is wired into upload background work. When a Markdown file is uploaded, the backend parses it and keeps the result in a lightweight local cache.

The parser can extract:

- title
- headings
- sections
- links
- images
- fenced code blocks
- typed chunks
- word count and reading time
- code language metadata

### `GET /documents/{filename}/parsed`

Return a compact Markdown parse summary for a stored Markdown file.

```json
{
  "filename": "98f0c2....md",
  "title": "Test Document",
  "headers_count": 2,
  "sections_count": 2,
  "links_count": 1,
  "images_count": 0,
  "code_blocks_count": 1,
  "word_count": 45,
  "reading_time": 1,
  "has_code": true,
  "languages": ["python"]
}
```

Full structure and chunk endpoints are planned next.

## Planned APIs

These modules are visible in the frontend as product direction, but their backend endpoints are not implemented yet:

- graph query endpoints
- semantic search endpoints
- AI chat/RAG endpoints
- authentication endpoints
- job progress WebSocket backed by real processing events
