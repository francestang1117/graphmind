# Project Structure

This file documents the structure that exists in the repository today. Future modules are listed in the roadmap section instead of being described as completed files.

```text
GraphMind/
├── README.md
├── IMPROVEMENTS.md
├── docker-compose.yml
├── docs/
│   ├── API.md
│   ├── DEVLOG.md
│   ├── ROADMAP.md
│   └── STRUCTURE.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example
│   └── app/
│       ├── main.py
│       ├── api/
│       │   ├── __init__.py
│       │   └── endpoints/
│       │       ├── auth.py
│       │       ├── documents.py
│       │       ├── documents_with_markdown.py
│       │       └── websocket.py
│       ├── core/
│       │   ├── celery_app.py
│       │   ├── config.py
│       │   └── rate_limit.py
│       ├── models/
│       │   └── document.py
│       ├── services/
│       │   ├── document_parser.py
│       │   ├── document_service.py
│       │   ├── file_storage.py
│       │   ├── markdown_parser.py
│       │   └── virus_scanner.py
│       ├── tasks/
│       │   └── process_document.py
│       └── utils/
│           └── file_validator.py
├── backend/tests/
│   ├── integration/
│   │   ├── test_documents_markdown.py
│   │   └── test_upload_api.py
│   ├── unit/
│   │   ├── test_file_storage.py
│   │   └── test_file_validator.py
│   ├── test_markdown_parser.py
│   └── test_websocket.py
└── frontend/
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── App.tsx
        ├── main.tsx
        ├── components/
        │   ├── ChatPanel.tsx
        │   ├── GraphPanel.tsx
        │   ├── SearchPanel.tsx
        │   ├── UploadPanel.tsx
        │   └── upload/
        ├── hooks/
        ├── services/
        ├── stores/
        ├── styles/
        ├── types/
        └── utils/
```

## Backend Notes

- `documents.py` is the active document API.
- `documents_with_markdown.py` contains Markdown helper functions, not a registered router.
- `celery_app.py` is a lightweight compatibility layer. The current app uses FastAPI background tasks.
- `virus_scanner.py` is an interface placeholder for a later ClamAV integration.
- Document metadata is currently in memory and file-backed metadata sidecars; a database layer is planned.

## Frontend Notes

- The document upload view is connected to the backend.
- Graph, search, and chat views currently use demo/fallback data where backend modules do not exist yet.
- Shared frontend state lives in `stores/appStore.ts`.
- API calls are centralized in `services/api.ts`.

## Future Structure

Likely future additions:

- `services/graph_builder.py`
- `services/vector_store.py`
- `services/entity_extractor.py`
- `api/endpoints/graph.py`
- `api/endpoints/search.py`
- `api/endpoints/chat.py`
- database models and migrations
- real job progress events
