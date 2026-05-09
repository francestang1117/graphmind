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

The PDF parser now prefers `pdfplumber` over `PyPDF2` so it can extract text
page by page and turn simple tables into searchable table chunks. `PyPDF2`
stays as a fallback for environments where pdfplumber is unavailable.

For now, PDF reading order is basic. It works well enough for simple documents, but complex academic PDFs with multi-column layouts, scanned pages, and figures will need a more deliberate layout/OCR pass later.

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

I refined this again after seeing sparse and noisy graph output. The extractor
now tries to load the local `en_core_web_sm` spaCy model by default, but it does
not download anything during backend startup. If the model is missing, the
backend falls back to the deterministic rule/domain extractor.

I also expanded the domain vocabulary around the actual project direction:
RAG, LLMs, chunking, embeddings, vector databases, semantic search, reranking,
ChromaDB, Redis, Docker, and graph databases. Overlapping phrases now prefer the
more specific term, so `vector embeddings` becomes one `Vector Embedding` node
instead of also creating a generic `Embedding` node. This made the graph less
cluttered without hiding meaningful concepts.

The next graph review exposed a more important issue: most visible edges were
still labeled `mentions`, which made the graph hard to read. I changed document
edges to use more meaningful relation names:

- documents `CONTAINS` concepts
- documents `USES` languages, frameworks, libraries, databases, and tools
- documents `DEFINES` functions and classes
- documents `REFERENCES` people, organizations, locations, and products

I also added noise filters for version/build strings, hash-like fragments,
timestamps, weekday/date fragments, tiny numeric labels, and article-led text
snippets. The goal is for the main graph to show knowledge-bearing entities,
while low-level parser artifacts stay out of the default visualization.

I then added two smaller improvements to make the extractor cheaper and the
graph less document-centered. spaCy models are now cached by model name, so the
backend does not reload `en_core_web_sm` every time an extractor is created.
Same-sentence entity pairs also get low-confidence type-pair relation hints,
such as `FastAPI -> WRITTEN_IN -> Python` or `React -> WRITTEN_IN -> JavaScript`.
These hints are deliberately weaker than explicit pattern matches, but they
help the graph show connections between entities instead of only document-to-
entity spokes.

After testing the graph visually, I adjusted the frontend to treat those weak
`RELATED_TO` edges differently. The main canvas now lays out and renders strong
edges first, while weak low-confidence edges stay hidden until a node is focused.
The caption also reports shown edges separately from hidden weak edges. This
keeps the default graph readable without throwing away the extra relation hints.

I made one more graph readability pass after seeing labels collide and generic
location/snippet entities creep back in. The main graph now hides location/date
nodes by default, filters possessive location fragments such as `New York City's`,
and drops generic one-word fragments like `jargon`, `Method`, and `Generate`.
Relation labels are no longer always-on; they appear when a node is focused so
the graph can stay quiet until the user asks for detail. I also added a simple
label collision check in the canvas renderer and made the graph controls smaller.

Finally, I added an optional relation-enhancer hook for a future GPT pass. This
lets the backend accept LLM-suggested relation triples later without making GPT
part of the current default pipeline.

The next cleanup focused on the remaining noise I could see in real uploads.
spaCy was still technically correct when it found places like Halifax or New
York City, but those nodes did not help a technical knowledge graph unless the
document was actually about geography. I added a small domain-relevance score:
technical/domain entities stay high priority, generic words are filtered, and
location entities from spaCy only survive when their surrounding context looks
geographic.

I also made the deduplication layer more explicit. Curated aliases still handle
the common cases (`js` -> `JavaScript`, `ML` -> `Machine Learning`, `LLM` ->
`Large Language Model`), and the extractor now has an optional semantic
similarity hook for future sentence-embedding merges. That keeps the current
project dependency-light, but gives a clean insertion point for merging near
duplicates before the graph builder inserts nodes.

On the frontend, I added stronger minimum node separation to the graph force
layout. Labels are still truncated at word boundaries, full names live in the
hover tooltip, and the canvas skips labels that would collide with already drawn
labels. The graph still needs a richer relation-extraction pass, but it is much
closer to a readable working view than the first dense cluster.

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

## 2026-05 — Graph Export

I added a small export layer to the graph API so the graph is not trapped inside
the browser view. The same rebuilt graph can now be downloaded as:

- Cytoscape-style JSON for frontend graph tooling
- GEXF for Gephi
- CSV for quick spreadsheet inspection

This is still based on the current in-memory graph rebuild, not long-term graph
persistence. That feels right for now: export is useful for debugging and demos,
while keeping the storage model flexible until the graph layer matures.

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

## 2026-05 — Retrieval-Based Chat MVP

I added the first version of Module 6 and Module 7: a question-answering engine
and a `/api/v1/chat` endpoint. The first draft called an external LLM provider
directly during service initialization, which made the backend too fragile for
the current stage. A missing package or API key should not stop upload, parsing,
graph, or search from working.

I changed the chat module into a retrieval-first MVP:

- rebuild the vector index from current uploaded documents before answering
- rebuild the in-memory graph before collecting graph context
- keep short in-memory conversation history
- return source documents from retrieved chunks
- answer locally from retrieved context when no LLM key is configured
- leave a clean future path for GPT/OpenAI answer generation
- expose `/api/v1/chat` through the main API router

This is not full GPT/OpenAI RAG yet. It is a stable bridge between the search
module and the future AI layer. The chat panel can now talk to real backend
context instead of only showing demo replies, while still running on a fresh
checkout without paid API keys.

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

## 2026-05 — Opening Uploaded Files Safely

I added an open-file action to the document list because it is useful to inspect the original upload, especially while debugging parser output.

That feature needed a small security boundary. Uploaded files are user-controlled content, so the backend should not blindly render everything inline in the browser. The current rule is:

- passive formats such as text, Markdown, JSON, PDF, and images can open inline
- active formats such as HTML and code are forced to download
- every open response includes `X-Content-Type-Options: nosniff`
- inline previews also get a sandbox-style content security policy
- paths are still resolved through stored metadata, not arbitrary filesystem input

This keeps the workflow convenient without turning uploaded source files into pages that can execute inside the app.

## 2026-05 — Auth And User Isolation Pass

I started the authentication module after the document/search/chat flows were
already usable. The first question was whether to lock every endpoint
immediately. Technically that would be cleaner, but the frontend does not have a
login screen yet, so forcing auth now would make the current app hard to test.

I chose a transition step instead:

- `/api/v1/auth/register`
- `/api/v1/auth/login`
- `/api/v1/auth/refresh`
- `/api/v1/auth/logout`
- `/api/v1/auth/me`

Access tokens are short-lived JWTs, and refresh tokens are opaque random tokens.
Redis is used for refresh-token storage when available, with an in-process
fallback for local development. User records are still in memory for now; the
real version should move them into PostgreSQL when the database module lands.

I also hit a dependency issue here. `passlib[bcrypt]` was installed, but the
local `passlib`/`bcrypt` combination failed while hashing passwords. Instead of
letting auth break the backend, I changed the password helper to prefer the
`bcrypt` package directly, then fall back to passlib, then to PBKDF2 for local
development. That keeps the project runnable while still using bcrypt when the
environment supports it.

The bigger change was user scoping. New file metadata now includes `user_id`,
and the document, graph, search, and chat flows all read through the current
user context. To avoid breaking the current frontend, missing tokens resolve to
a stable `local-dev` user while `AUTH_REQUIRED=false`. When the frontend login
UI is ready, I can flip `AUTH_REQUIRED=true` and the same endpoints become
properly protected.

Tests now cover the token lifecycle and the existing upload/search/chat paths:
register, login, refresh, logout, document upload, file storage, vector search,
and local QA.

## 2026-05 — Rate Limiting Boundary

After adding auth, I added the first real rate-limiting boundary. This is mainly
about protecting the expensive parts of the system before the app grows into
multi-user usage.

The risks are different by endpoint:

- uploads can fill disk and trigger parsing work
- chat will eventually call GPT/OpenAI and cost money
- search can be spammed with repeated large queries
- graph reads are cheaper, but still rebuild in-memory state right now
- video generation is planned to be much more expensive than everything else

I added a `slowapi` wrapper in `app/core/rate_limit.py` with named endpoint
limits instead of hardcoding strings in every route. The current limits are:

- upload: `10/minute;100/hour`
- chat: `30/minute;500/day`
- search: `60/minute`
- graph reads: `120/minute`
- future video generation: `5/hour`

The limiter is designed to use Redis so counters are shared across API
instances. I also kept a no-op fallback for local development. If `slowapi` is
not installed yet, or Redis is not reachable, the backend logs that rate
limiting is disabled instead of failing startup. That keeps the project usable
while still making the production path clear.

One implementation detail mattered: `slowapi` needs a `request` parameter in
decorated route functions. I added that to upload, search, chat, and graph
endpoints while keeping the existing direct endpoint tests working.

## 2026-05 — Database Foundation

I started the persistence work with a small database foundation instead of
moving the entire graph into a database at once. The graph schema is still
changing as entity extraction improves, so persisting every node and edge now
would create extra migration work before the model has settled.

The first database pass adds:

- `DATABASE_URL` configuration
- SQLAlchemy engine/session setup
- startup table creation
- `users` table
- `documents` table
- PostgreSQL service in Docker Compose
- SQLite as the lightweight local default

The current app still reads document metadata from sidecar JSON files, but new
users and uploaded document metadata are mirrored into the database when
SQLAlchemy is available. This gives the project a real persistence path without
forcing a risky rewrite of upload, search, graph, and chat in one step.

I kept the database module optional during local development. If SQLAlchemy is
not installed yet, the backend still starts and the existing workflows keep
using local files. Once dependencies are installed and PostgreSQL is running,
the same code begins creating tables and writing users/documents.

The next persistence steps should be parsed chunks, extracted entities, and
graph nodes/edges. Neo4j can still be useful later for heavier graph traversal,
but PostgreSQL is the right source of truth for the current app.

I then replaced the sidecar-first document metadata read path with a small
SQLAlchemy `DocumentRepository`. File bytes still live in local storage, but
document list/detail now prefer the `documents` table when the database is
available. If the table is empty or the database is disabled, the service falls
back to sidecar JSON so older local uploads do not disappear.

This is the first real step away from the old in-memory/document-sidecar model:

- uploads mirror metadata into the database
- list/detail can read from the database
- delete soft-deletes the database row after removing the local file
- tests cover repository save/list/get/update/delete behavior

## 2026-05 — Virus Scanning Boundary

I added the first real virus scanning boundary around uploads. The first version
of this module looked more complete than it actually was: `virus_scanner.py`
had a ClamAV client, but the upload flow was not calling it yet. That meant the
code existed, but uploaded bytes still went straight from validation into local
storage.

I fixed the upload order so the pipeline is now:

1. validate extension, size, MIME, and basic content safety
2. stream the bytes to ClamAV when virus scanning is enabled
3. write the file only after both checks pass

The important part is that the scanner runs before `save_file()`. I do not want
the project to write suspicious bytes to disk and only then decide whether they
are safe.

I also made the scanner behavior configurable. Local development should not
depend on a running ClamAV daemon, so `VIRUS_SCAN_ENABLED=false` by default.
Docker Compose enables it and points the API at the `clamav` service. In that
environment, `VIRUS_SCAN_FAIL_OPEN=false`, so scanner outages block uploads
instead of quietly allowing them.

That split feels like the right compromise for this stage:

- local venv: keep upload/parsing easy to test
- Docker/production path: scan before storage and fail closed

I added tests for the scanner response parser and the upload integration. The
tests verify clean responses, threat responses, scanner outages, and the fact
that a detected threat never reaches storage. I still need to do a manual EICAR
test with the real Docker ClamAV service, but the backend boundary is now wired
instead of just documented.

## 2026-05 — WebSocket Progress Stream

I replaced the old placeholder WebSocket endpoint with a real job progress
stream. The route is now mounted at `/ws/jobs/{job_id}` and watches Celery task
state through `AsyncResult`.

The first version of this module looked complete from the outside, but it had
two gaps: the router was not included in the FastAPI app, and the background
document task never called `update_state()`. That meant the browser would not
have received real processing stages even if it connected successfully.

The current version sends compact progress messages:

- `PENDING` while the job is waiting
- `PROGRESS` with `pct` and `step`
- `SUCCESS` with the final result
- `FAILURE` or `REVOKED` for terminal errors

For local development, the Celery fallback now supports the small part of the
bound-task API that this needs. It is still not a full queue, but tests can
exercise progress-aware tasks without requiring Redis and a worker process.

## 2026-05 — Error Handling Cleanup

As the backend grew past upload and parsing, the rough exception handling became
more noticeable. A few places were still catching broad `Exception`s and either
returning an empty result or hiding the reason behind a generic message. That
made debugging feel worse than the actual bugs.

I added a small application error layer with stable error codes, then started
using it at the user-facing boundaries:

- upload validation now returns `upload_validation_failed`
- duplicate uploads return `duplicate_file`
- parse failures return `parse_failed` with file details
- unsafe stored-file paths and missing stored files have separate codes
- storage write/delete failures now return `storage_operation_failed`
- metadata database failures now return `database_operation_failed`
- ClamAV failures distinguish `malware_detected` from `virus_scanner_unavailable`

I also changed graph and search rebuilds to log skipped files instead of
silently ignoring them. A single bad document still should not break the whole
graph or search panel, but now there is a trail in the logs when that happens.

The service layer still keeps low-level exceptions close to the modules that
raise them, but user-facing operations now cross the API boundary as stable
application errors instead of random Python or database exceptions.

## 2026-05 — QA Fallbacks Made Visible

The chat endpoint can run without an OpenAI key, which is useful while the rest
of the pipeline is still moving quickly. The problem was that every fallback
looked the same from the outside: the user saw a weaker local answer, and the
backend did not always say whether search, graph rebuild, or the optional LLM
step had failed.

I changed the QA engine so the local answer path reports a `fallback_reason`.
For example:

- `openai_not_configured` when no GPT provider is wired yet
- `openai_package_missing` if the key is present but the SDK is not installed
- `openai_request_failed` if the provider call fails
- `no_retrieval_context` when search cannot find usable document context

The chat API still returns a normal answer, but debugging is less guessy now.
Search and graph context failures also write warnings instead of disappearing.
This keeps the MVP usable while making the weak spots easier to improve later.

## 2026-05 — Parser Fallback Logs

I also went back through `document_parser.py` and cleaned up the quiet fallback
paths. Some parser failures are normal, like a DOCX file not having comments or
saved page-count metadata. Those now use debug logs. Cases that usually mean the
file or XML part is damaged use warnings.

The goal is not to make the parser noisy. It is to make parser behavior
traceable when a PDF heading hint disappears, a DOCX XML part cannot be read, or
CSV parsing falls back from pandas to the standard library.

## 2026-05 — Web Scraper MVP

I started the web ingestion module because only supporting local file upload
feels too narrow for the project. A lot of useful knowledge starts as a web
page, and later a browser extension would probably call into the same backend
path.

The current version is intentionally small and fits what the app can honestly do
right now:

- fetch a public page
- remove obvious page chrome like scripts, nav, headers, and footers
- keep the title and source URL
- turn the readable text into a Markdown document
- store it through the same upload service used by normal files

That last part is important. Scraped pages should not become a separate kind of
content that every later module has to special-case. By saving the page as a
normal document, search, graph, and chat can pick it up through the existing
rebuild paths.

I also added a first safety boundary around URL fetching. The scraper blocks
local/private network addresses, checks the final redirected URL too, caps the
response size, accepts only readable HTML/text responses, and has its own rate
limit. This is one of those features where a simple implementation can become
dangerous quickly, so I would rather keep the MVP small and boring than make it
look powerful but unsafe.

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
- pdfplumber-backed PDF text/page/table extraction with PyPDF2 fallback
- entity extraction MVP with rule-based technical entities and optional spaCy NER
- in-memory knowledge graph builder connected to uploaded documents
- vector search MVP over parsed document chunks
- retrieval-based chat endpoint with local fallback answers and visible fallback reasons
- web scraper MVP that stores public pages as searchable Markdown documents
- JWT auth MVP with access/refresh token flow
- user-scoped document, graph, search, and chat reads
- Redis-backed rate-limit wrapper with local no-op fallback
- SQLAlchemy persistence for users and document metadata
- database-backed document metadata repository with sidecar fallback
- optional ClamAV virus scan before file storage
- WebSocket job progress stream for Celery-backed processing
- stable API error codes for common upload, parse, and file access failures
- Docker Compose for API + frontend
- tests for the core backend pieces

The project is not yet a full knowledge graph system. The graph, search, and
chat screens can now use real extracted data, but persistence and production
auth are still early-stage.

## Next Steps

The next realistic steps are:

1. Expand the Markdown viewer to show full sections and chunks.
2. Persist parsed chunks, extracted entities, and graph nodes/edges.
3. Improve graph quality with better relation extraction and edge weighting.
4. Add the frontend login/register flow and send Bearer tokens from the API client.
5. Replace local chat answers with GPT-backed answer generation when the OpenAI layer is ready.
