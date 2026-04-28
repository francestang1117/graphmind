# Development Log

This is my personal development log for GraphMind. I started planning the project in November 2025, with the goal of building a document ingestion system that can gradually grow into a knowledge graph workspace.

I am using this file to record what was actually built, what broke along the way, and what decisions changed as the project became more concrete. It is not a formal changelog.

## 2025-11 — Starting Point

The first idea was much bigger than the current codebase: upload documents, parse them, extract entities, build a knowledge graph, add search, and eventually support AI Q&A.

At this point the plan was useful, but too wide. I wrote down the full direction first, then split it into smaller phases so the project would not become a collection of unfinished features.

The phase order became:

1. Basic infrastructure.
2. Document upload.
3. Markdown parsing.
4. Graph construction.
5. Search and retrieval.
6. AI chat and visualization.

The main decision here was to make upload and parsing work first. Everything else depends on having clean input.

## 2025-12 — Backend Skeleton

I started the FastAPI backend and added the first project structure: app setup, settings, API routing, and document-related modules.

One of the first problems was configuration. Some files expected a global `settings` object, while the config module only exposed `get_settings()`. A few setting names also did not match the names used by the app.

I fixed this by making the settings module expose the values the app actually uses, instead of leaving different parts of the backend with different assumptions.

This was a small bug, but it mattered because import-time failures make the whole backend feel broken before any endpoint can even be tested.

## 2026-01 — File Upload Module

I focused on the first real workflow: upload a file, validate it, store it, and show it back to the user.

The early version of the upload module had a mismatch between the API route and the storage service. The route expected a metadata dictionary, but the storage function returned a tuple. That made the code awkward and easy to break.

I refactored storage so the rest of the app can work with clear file metadata:

- original filename
- stored filename
- content hash
- file size
- extension
- storage path
- upload time

I also added validation before writing files to disk:

- allowed extension checks
- empty file rejection
- max size checks
- MIME detection fallback
- PDF and DOCX signature checks
- basic unsafe text pattern scanning
- filename sanitization

This module is now the most complete part of the project. It is still local-file based, but the flow is usable.

## 2026-02 — Markdown Parser

After upload worked, I started the Markdown parser. The goal was not just to convert Markdown to HTML, but to extract structure for future graph building.

The parser now handles:

- document title
- heading hierarchy
- links and images
- fenced code blocks
- list blocks
- section structure
- text chunks
- word count and reading time
- detected code languages

I also added tests around the parser because small Markdown edge cases can quietly break later modules.

The important follow-up was connecting this parser to the upload flow. A parser sitting alone in `services/` does not really help the app. Now, when a Markdown file is uploaded, the backend parses it in background work and the frontend can show a summary.

The current viewer is still simple. It shows summary-level parse information, not the full section tree and chunks yet.

## 2026-03 — Frontend Upload Experience

I built the first frontend around the upload workflow.

The first mockup was a single large HTML block. It was useful for visual direction, but it made the actual app code feel too generated and hard to maintain.

I split the upload UI into smaller React pieces:

- `UploadPanel`
- `UploadDropzone`
- `DocumentOverview`
- `DocumentList`
- `DocumentRow`
- `UploadRow`

This made the code easier to read and gave each part a clearer job.

I also adjusted the UI several times because the first version was too large visually. The current direction is a darker, compact workspace style with smaller typography, file icons, progress states, and status badges like `Done` and `Indexing`.

Graph, search, and chat panels exist in the frontend, but they are still demo-facing. They show where the project is going, not completed backend features.

## 2026-03 — Cutting Back Future Modules

At one point the backend started to look more complete than it really was. There were references to Redis, Celery, ClamAV, WebSockets, auth, vector search, and graph services.

That looked impressive, but it created a problem: some imports pointed to services that were not actually implemented yet. The project felt bigger, but less trustworthy.

I changed those future-facing pieces into smaller boundaries:

- rate limiting is currently a lightweight shim
- virus scanning keeps an interface but does not require ClamAV yet
- WebSocket progress has a placeholder endpoint
- Celery-compatible task code exists, but the current upload flow uses lightweight background work
- graph/search/chat remain planned modules instead of pretending to be done

This made the codebase more honest. It is better to have clear placeholders than fake production systems.

## 2026-04 — Docker And Running The App

I added Docker support so the project can be started more easily.

The first Docker Compose idea included the future full stack: Postgres, Redis, ChromaDB, MinIO, ClamAV, API, frontend, and worker services.

That was too much for the current state. Most of those services are planned, but not required by the app today.

I simplified Compose to the two services that actually run now:

- backend API
- frontend app

The future services are still documented in the roadmap, but the default Compose setup should match the current project.

## 2026-04 — FastAPI Lifespan Cleanup

FastAPI warned that `@app.on_event()` is deprecated.

I replaced the older startup/shutdown event style with a lifespan handler. This is a small cleanup, but it keeps the backend closer to current FastAPI practice and avoids leaving warnings around for later.

## 2026-04 — Documentation Pass

Before preparing the project for GitHub, I reviewed the README and docs.

The main issue was overclaiming. Some earlier text described the long-term product as if every feature already existed. That made the project look less credible.

I rewrote the docs around three buckets:

- working now
- partially wired
- planned later

The README now focuses on the current foundation: upload, validation, storage, Markdown parsing summary, and the React interface. The bigger roadmap lives in `docs/ROADMAP.md`, and future improvements live in `IMPROVEMENTS.md`.

## 2026-04 — Adding Practical Comments

I added short comments/docstrings to the main backend and frontend files to make the implemented features easier to understand at a glance.

The goal was not to explain every line. I only wanted each file to say what part of the current product it owns.

Examples:

- upload route comments list the implemented document API features
- storage comments explain content-addressed local storage
- validator comments summarize current safety checks
- Markdown parser comments list the structures it extracts
- frontend upload components describe their role in the upload workflow

This should make the project easier to read without making the code feel over-commented.

## Current State

As of April 2026, GraphMind has a working foundation:

- FastAPI backend
- React + TypeScript frontend
- document upload API
- drag-and-drop upload UI
- file validation
- local file storage
- document list/detail/delete
- Markdown parser
- Markdown parse summary endpoint
- simple frontend Markdown summary viewer
- basic parsers for TXT, PDF, DOCX, Python, JavaScript, and TypeScript
- Docker Compose for API + frontend
- tests for the core backend pieces

The project is not yet a full knowledge graph system. The graph, search, and chat screens are still mostly product scaffolding.

## Next Steps

The next realistic steps are:

1. Expand the Markdown viewer to show full sections and chunks.
2. Store document metadata in a real database instead of local sidecar metadata only.
3. Start the first graph extraction module from parsed Markdown chunks.
4. Add persistent graph storage.
5. Replace demo search/chat data with real backend flows.
