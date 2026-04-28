# Roadmap

GraphMind is planned as a staged knowledge graph product. The current repository focuses on the first two modules: file upload and document parsing. Later phases will build graph intelligence, retrieval, AI assistance, and media generation on top of that foundation.

## Development Phases

### Phase 1: Infrastructure

Target: weeks 1-2

Status: partially complete

- Project initialization and environment setup
- Basic FastAPI backend
- Frontend application shell
- Docker Compose for local API + frontend
- Configuration management
- Basic test coverage

Planned next:

- Persistent database connection
- Initial migration setup
- Cleaner CI workflow

### Phase 2: Document Processing

Target: weeks 3-4

Status: in progress

- File upload API
- File validation
- Local content-addressed storage
- Frontend drag-and-drop upload
- Markdown parser
- Basic PDF parser
- Basic DOCX parser
- Basic code file parser
- Parsed Markdown summary endpoint
- Frontend Markdown summary viewer

Planned next:

- Expand the Markdown viewer to show full structure and chunks
- Improve PDF table/image handling
- Improve DOCX structure extraction
- Add parser-level error reporting in the UI

### Phase 3: Knowledge Graph Core

Target: weeks 5-6

Status: planned

- Named entity recognition
- Relationship extraction
- Graph construction engine
- Graph persistence
- Node and edge API endpoints
- Graph statistics

### Phase 4: Search and Retrieval

Target: weeks 7-8

Status: planned

- Vector embedding module
- Semantic search engine
- Keyword search
- Graph path search
- Hybrid ranking

### Phase 5: AI Enhancement

Target: weeks 9-10

Status: planned

- LLM integration
- AI Q&A engine
- Context-enhanced retrieval
- Multi-turn conversation state
- Source citations

### Phase 6: Visualization

Target: weeks 11-12

Status: planned

- Knowledge graph visualization
- Interactive graph operations
- Node detail panel
- Relationship filtering
- Graph expansion and path exploration

## Current Module Details

### Module 1: File Upload System

Status: active

Scope:

- Backend upload API
- Extension and MIME validation
- File size limits
- Basic content safety scan
- Local storage management
- Frontend drag-and-drop upload
- Upload progress states
- Document list and delete action

Architecture:

```text
User -> Frontend upload component -> API endpoint -> Validator -> Storage service -> Metadata response
```

### Module 2: Markdown Parser

Status: in progress

Scope:

- Heading extraction
- Section extraction
- Paragraph chunking
- Fenced code block extraction
- Link extraction
- Image extraction
- Basic metadata such as word count and reading time

Current limitation:

- Parsed Markdown summaries are visible in the frontend, but full structure and chunks are not shown yet.

## Future Expansion Ideas

### 1. Web Capture and Browser Extension

Priority: high

Why it matters:

- Most user knowledge lives on the web.
- Browser extensions are a natural capture surface.
- This can become a daily-use feature instead of a one-time upload tool.

Possible scope:

- Save current page to GraphMind
- Extract readable article text
- Attach URL/source metadata
- Send page content into the normal document pipeline

Implementation difficulty: medium

### 2. Code Repository Analysis

Priority: high

Why it matters:

- Developers need better ways to understand large codebases.
- It is a strong differentiator from simple document graph tools.
- It can reuse the graph model for functions, classes, modules, and dependencies.

Possible scope:

- Parse repository structure
- Extract functions/classes/imports
- Build dependency graph
- Link code comments and docs to implementation nodes

Implementation difficulty: hard

### 3. Audio and Video Transcription

Priority: medium

Why it matters:

- Meetings, lectures, and courses contain valuable knowledge.
- Transcription can feed the same document-to-graph pipeline.

Possible scope:

- Upload audio/video files
- Transcribe with Whisper or another ASR service
- Chunk transcript by timestamp
- Link graph nodes back to time ranges

Implementation difficulty: medium

### 4. Chat Log Analysis

Priority: medium

Why it matters:

- Team knowledge often lives in Slack, Discord, or similar tools.
- Conversation history can reveal decisions, owners, and unresolved questions.

Possible scope:

- Import exported chat logs
- Extract topics, decisions, action items, and participants
- Build timelines and knowledge graph relations

Implementation difficulty: low to medium

### 5. Email Integration

Priority: later

Why it matters:

- Email is still a major source of workplace knowledge.
- Threads contain decisions and context that are often hard to rediscover.

Possible scope:

- Gmail import
- Thread summarization
- Entity and decision extraction
- Link email threads to project/document nodes

Implementation difficulty: medium

## Knowledge Graph to Video

This is a larger product direction: use the knowledge graph to automatically generate explainer videos.

### Example Use Cases

Scientific explainer:

```text
User uploads: Introductory quantum mechanics notes
GraphMind extracts: core concepts and relationships
Output: 5-minute explainer video with narration, subtitles, and visual concept flow
```

Course visualization:

```text
Teacher uploads: syllabus and textbook notes
GraphMind generates: chapter-level lesson videos with concept maps and explanations
```

Research presentation:

```text
Researcher uploads: paper and data notes
GraphMind generates: presentation-style video covering background, method, and results
```

### Video Generation Phase 1: PPT-Style MVP

Target duration: 2-3 weeks after graph/search modules exist

Workflow:

```text
Knowledge graph
-> extract key nodes
-> generate narration script
-> text-to-speech
-> graph screenshots or simple slides
-> MP4 video
```

Possible stack:

- TTS: Edge TTS, Azure TTS, or ElevenLabs
- Visuals: Matplotlib, Plotly, or frontend graph screenshots
- Video: FFmpeg or MoviePy
- Subtitles: generated from script timestamps

Output:

- 3-5 minute MP4
- narration
- simple graph visuals
- subtitles

### Video Generation Phase 2: Animation

Target duration: 1-2 months after MVP

Features:

- Graph nodes appear one by one
- Relationship lines animate
- Concept explanation cards
- Scene transitions

Possible stack:

- Manim
- FFmpeg
- TTS provider

### Video Generation Phase 3: AI Presenter

Target duration: later

Features:

- Virtual presenter
- More polished voice and scene design
- Generated visuals or clips
- Smarter editing

Possible stack:

- D-ID or HeyGen
- ElevenLabs
- Runway or similar video tools
- FFmpeg for assembly

## Product Entry Point For Video

Possible UI flow:

```text
Knowledge graph page
-> Generate video
-> Configure style, length, language, and voice
-> Start generation
-> Show progress
-> Download or share video
```

Progress steps:

- Analyze graph
- Generate script
- Generate narration
- Render visuals
- Compose video
- Export MP4

## Guiding Principle

Each phase should become useful before the next phase is added. The project should avoid importing or documenting future services as complete until they are actually wired into the app.
