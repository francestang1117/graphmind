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

## 2026-04 — Upload UI Polish

After testing the upload flow with real files, I found several small UI problems that made the app feel less stable than the backend actually was.

The first issue was duplicate rows. A successful upload briefly showed both the temporary upload row and the saved document row. I changed the flow so the temporary row is removed before the refreshed backend list is applied.

The second issue was unsupported files. Dropping a PNG used to create an error row in the document list and show raw request text like `status code 400`. That was technically true, but not useful. Unsupported files are now blocked at the dropzone, and the user sees a short supported-types message instead.

I also tightened a few details that became obvious only after clicking around:

- Markdown preview can be toggled from the eye button.
- The active preview row now gets a highlighted eye state.
- The preview panel title uses the filename, while the Markdown H1 stays inside the structure details.
- Time labels now move from `just now` to minute/hour/day labels.
- File icons are easier to scan: Markdown, DOCX, code, PDF, and text no longer all look the same.

## 2026-04 — Multi-format Parse Summaries

Markdown was the first format with a visible parse summary. After adding PDF, DOCX, code, JSON, CSV, and HTML parsers, I noticed the UI still behaved as if Markdown was the only parseable file.

I changed the parsed summary endpoint and viewer so every supported file can expose what was actually extracted. PDF summaries now focus on the dimensions that matter for document quality:

- base text
- tables
- figures/images
- reading order

For now, PDF reading order is basic. It works well enough for simple documents, but complex academic PDFs with multi-column layouts will need a more deliberate reading-order pass later.

## 2026-04 — Real Upload Edge Cases

Testing with real files exposed a few problems that did not show up with simple sample documents.

The first issue was JSON storage. Uploaded `.json` files are stored as `hash.json`, while their sidecar metadata is stored as `hash.json.json`. My list endpoint was scanning every `*.json` file and accidentally tried to read the uploaded document itself as metadata. That broke the document list with a missing `created_at` field. I fixed this by validating the sidecar metadata schema before including a file in the list.

The second issue was duplicate uploads. Content-addressed storage already used SHA-256 filenames, but the API still behaved as if uploading the same content again was normal. I changed this into an explicit duplicate flow: the backend detects repeated content by hash and returns a `409`, and the frontend shows a `Duplicate` state instead of adding another row.

The third issue was HTML validation. I originally blocked any HTML containing scripts or inline handlers. That is too strict for this project because HTML is uploaded as source material to parse, not as a page to execute. The validator now allows script tags in `.html` source files while still blocking dangerous URL schemes such as `javascript:` and `data:text/html`.

The last issue was DOCX structure. A resume template used a Word table for layout, so the parser reported `paragraphs: 3` and `tables: 1`, even though the visible document had many more text blocks and no real data table. I updated the DOCX parser to read visible XML paragraphs, treat layout tables as searchable text, and only count compact grid-like content as actual tables.

## 2026-04 — Entity Extraction MVP

I started Module 3 with a small entity extraction layer. The first draft had the right idea, but the file accidentally lived under `__pycache__`, and the test file was closer to a demo script than an automated test.

I moved the extractor into `app/services/entity_extractor.py` and made the first version deliberately modest:

- rule-based technical entities for languages, frameworks, libraries, and concepts
- optional spaCy support for general named entities
- Markdown-aware extraction from headings, links, and code blocks
- import extraction from Python and JS/TS code fences
- entity normalization and deduplication
- lightweight relation hints such as `USES`, `DEVELOPED_BY`, and co-mentions

The important design choice was to make spaCy optional. The project should still start and the tests should still run if the local machine does not have `en_core_web_sm` installed. spaCy can improve recall later, but it should not make the module fragile during early development.

After testing the graph view, I tightened the entity extractor again. Simply
creating more nodes made the graph noisier, not smarter. I added a small domain
vocabulary, confidence filtering, and a dependency-free optional LLM hook:

- curated aliases such as `js` -> `JavaScript` and `RAG` -> `Retrieval Augmented Generation`
- local domain terms for frameworks, languages, libraries, and AI/search concepts
- a minimum confidence threshold before entities can enter the graph
- optional spaCy NER for general named entities
- optional LLM enhancer interface, disabled by default

This keeps the default project runnable without API keys or model downloads,
while leaving a clean place to add stronger extraction later.

## 2026-04 — First Knowledge Graph Builder

I added Module 4 to turn extracted entities into a graph. The first version used a demo-style NetworkX wrapper, but it was not wired into the API router and it added a new dependency before the current project really needed it.

I simplified the first graph builder into an in-memory service with a clear shape:

- document nodes
- entity nodes
- `MENTIONS` edges from documents to entities
- relation edges from the entity extractor
- node search
- neighbor lookup
- graph statistics
- frontend-ready visualization export

The graph API now rebuilds from the current uploaded documents, which is not the final persistence model, but it is honest for this stage. It means the Graph panel can show real data from uploaded files without pretending that Neo4j/Postgres graph persistence is already finished.

I also replaced the old full-pipeline demo script with assertions. The test now checks the real path from Markdown parsing to entity extraction to graph construction.

## 2026-04 — Search Module MVP

I added the first version of Module 5 for search. The initial draft used ChromaDB and sentence-transformers directly at import time. That is the right long-term direction, but it made the current backend too fragile because a fresh checkout would fail before the API even started if those heavy dependencies were missing.

I changed the first search module into a lightweight local vector index:

- parsed chunks become searchable records
- text is embedded with deterministic hashed term vectors
- cosine similarity gives a basic semantic score
- keyword overlap boosts direct matches
- the `/api/v1/search` endpoint now searches the current uploaded documents
- a small context endpoint is available for the future chat/RAG module

This is not a production vector database yet. It is a stable MVP that proves the parser output can feed search, and it leaves room to swap in ChromaDB later behind the same service interface.

## 2026-05 — Upload Validation False Positives

After adding more realistic test files, I hit a confusing upload problem: a short Markdown file named `RAG System Design.md` kept failing with "The file contents do not match its extension." Restarting the backend did not help.

The issue was not the file itself. `libmagic` was detecting a tiny Markdown document beginning with `# RAG System Design` as `video/MP2T`. The validator trusted the detected MIME type too much, so a normal `.md` file was rejected before parsing.

I changed the rule for text-like files. For `.md`, `.txt`, `.py`, `.js`, `.ts`, `.json`, `.csv`, and `.html`, the validator now checks:

- the extension is allowed
- the content is readable text
- the text does not contain blocked unsafe patterns

Binary document formats still stay strict. PDF and DOCX uploads continue to require their expected file signatures, so this fix does not make disguised binary files pass as Markdown.

I also added regression tests for the exact false positive:

- Markdown detected as `text/x-shellscript`
- Markdown detected as `video/MP2T`
- binary bytes renamed to `.md`

## Current State

As of May 2026, GraphMind has a working foundation:

- FastAPI backend
- React + TypeScript frontend
- document upload API
- drag-and-drop upload UI
- file validation
- local file storage
- document list/detail/delete
- duplicate detection by content hash
- Markdown parser
- Markdown parse summary endpoint
- frontend parse summary viewer
- basic parsers for TXT, PDF, DOCX, Python, JavaScript, TypeScript, JSON, CSV, and HTML
- entity extraction MVP with rule-based technical entities and optional spaCy NER
- in-memory knowledge graph builder connected to uploaded documents
- vector search MVP over parsed document chunks
- Docker Compose for API + frontend
- tests for the core backend pieces

The project is not yet a full knowledge graph system. The graph and search screens can now use real extracted data, while chat is still mostly product scaffolding.

## Next Steps

The next realistic steps are:

1. Expand the Markdown viewer to show full sections and chunks.
2. Store document metadata in a real database instead of local sidecar metadata only.
3. Improve graph quality with better relation extraction and edge weighting.
4. Add persistent graph storage.
5. Replace chat demo data with real backend retrieval and answer generation.
