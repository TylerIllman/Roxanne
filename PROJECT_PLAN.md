# Jarvis Assistant Project Plan

Status date: 2026-03-25

This document is the canonical project reference for Jarvis Assistant. Future conversations should use this file as the source of truth for:

- current product scope
- architecture decisions already made
- implemented features
- security decisions
- immediate next work
- known gaps and risks

## 1. Product Summary

Jarvis Assistant is a local-first personal research copilot designed for:

- Zotero paper and PDF retrieval
- Obsidian note retrieval and note writing
- conversational research assistance
- local indexing and retrieval rather than full-context dumping
- desktop-first use on macOS

The MVP is intentionally not a generic autonomous agent. It is a retrieval-first, tool-using assistant with a local UI and a local backend.

## 2. Confirmed Product Decisions

These are already decided and should not be re-litigated unless explicitly changed:

- UI is a local desktop app, not a browser-only web app
- Desktop shell is Electron
- Frontend stack is React + TypeScript
- Frontend styling uses Tailwind CSS with local shadcn-style component primitives
- Backend is Python
- Reasoning model is Anthropic Claude via API key
- Default embeddings are local-first via FastEmbed
- Multiple Obsidian vaults are supported from day one
- Web search is deferred until after the core research workflow is solid
- Local codebase search is deferred for now

## 3. Architecture

### High-level topology

```text
[ Electron desktop app ]
        |
        v
[ React renderer ]
        |
        v
[ Local FastAPI backend ]
        |
        +--> Anthropic API
        +--> Chroma vector store
        +--> Zotero storage / PDFs
        +--> Obsidian vault filesystem
        +--> Local speech tools
```

### Frontend

- Electron app shell
- React + TypeScript renderer
- Rsbuild bundler
- Tailwind CSS
- Local shadcn-style primitives for:
  - buttons
  - cards
  - inputs
  - select
  - textarea
  - badge
  - switch

### Backend

- FastAPI app
- config + settings store
- OS keychain-backed secret storage
- Chroma persistent vector DB
- FastEmbed local embeddings by default
- OpenAI embeddings as optional provider
- PyMuPDF for PDF extraction
- faster-whisper for STT
- Piper path support for local TTS

## 4. Current Implemented Scope

### 4.1 Desktop UI

Implemented:

- onboarding flow with multiple steps
- settings capture for:
  - Anthropic API key
  - Claude model
  - Zotero storage path
  - Zotero database path
  - multiple Obsidian vaults
  - embedding provider and model
  - optional OpenAI embedding settings
  - optional speech settings
- main workspace/chat shell
- paper results panel
- note results panel
- voice input trigger
- auto-speak toggle

Current limitation:

- the UI is functional but still early-stage product UI, not final polished UX

### 4.2 Tool-Orchestration Backend

Implemented:

- dynamic tool registry
- Claude tool-calling orchestration loop
- streaming NDJSON chat events to the renderer
- local tool execution on the Python side

Implemented tools:

- `search_zotero`
- `retrieve_paper_chunks`
- `open_pdf`
- `read_notes`
- `write_note`

Not implemented yet:

- `search_web`

### 4.3 Retrieval and Indexing

Implemented:

- PDF text extraction
- word-based chunking
- Chroma indexing for papers
- Chroma indexing for notes
- vector retrieval for papers and notes
- lightweight session-summary memory store

Current limitation:

- Zotero metadata enrichment is still shallow and mostly PDF-derived
- we are not yet reading full Zotero metadata relationships out of `zotero.sqlite`

### 4.4 Speech

Implemented:

- audio upload transcription endpoint
- local Whisper-based transcription service
- Piper-based synthesis endpoint

Current limitation:

- current voice flow is request/response, not true low-latency streaming STT/TTS

## 5. Sensitive Data and Security Model

This section matters. Future work should preserve these constraints unless explicitly changed.

### Secrets

Current design:

- Anthropic API key is stored in OS keychain
- OpenAI embedding API key is stored in OS keychain
- secrets are not persisted to `config.json`

Rationale:

- API keys are sensitive and should not live in plaintext project config

### Non-secret config

Stored locally in app data:

- model names
- Zotero paths
- Obsidian vault paths
- embedding provider selection
- speech paths and defaults

### Local storage

Stored locally:

- vector DB contents for papers, notes, and memory summaries
- extracted/indexed research content
- temporary or generated audio artifacts

Security hardening already added:

- app data directories use restrictive permissions where supported
- transcription upload temp files are deleted after use
- old audio files are pruned
- backend CORS is restricted to local desktop/dev origins instead of `*`

Remaining privacy caveat:

- indexed content and memory summaries are still stored locally on disk in the vector store
- this is expected for MVP, but encryption-at-rest for indexed content is not yet implemented

## 6. Current File/Module Responsibility

### Backend

- `apps/backend/jarvis_backend/main.py`
  - FastAPI entrypoint
  - API routes
  - service container

- `apps/backend/jarvis_backend/config.py`
  - config load/save
  - keychain integration for secrets

- `apps/backend/jarvis_backend/secret_store.py`
  - secret storage abstraction

- `apps/backend/jarvis_backend/retrieval.py`
  - Chroma store
  - embeddings
  - session memory summaries

- `apps/backend/jarvis_backend/ingestion/indexer.py`
  - PDF and note indexing

- `apps/backend/jarvis_backend/orchestrator.py`
  - Claude tool loop

- `apps/backend/jarvis_backend/tools/`
  - tool implementations

### Frontend

- `apps/desktop/src/renderer/App.tsx`
  - onboarding shell
  - workspace shell
  - renderer-side UX logic

- `apps/desktop/src/renderer/components/ui/`
  - local UI primitive library

- `apps/desktop/src/main/main.ts`
  - Electron main process
  - backend process spawning
  - path picker bridge

## 7. What Is Not Done Yet

These are known gaps, not surprises.

### Product gaps

- no web search tool yet
- no codebase retrieval yet
- no polished citation cards or paper detail view yet
- no packaged desktop distribution yet
- no proper settings export/import yet

### Retrieval gaps

- no robust Zotero database metadata import
- no deduplicated paper identity layer beyond file-based indexing
- no incremental indexing scheduler or file watching

### Voice gaps

- no streaming STT partials
- no chunked streaming TTS playback
- no hotkey-triggered push-to-talk flow

### Engineering gaps

- no automated tests yet
- no typed API client generation
- no structured logging / diagnostics panel
- no production packaging pipeline

## 8. Immediate Next Plan

This is the current recommended order of work.

### Phase 1: Stabilize local dev flow

Goal:

- make local development predictable

Tasks:

- ensure Electron prefers the project backend venv automatically
- verify Tailwind/Rsbuild install path is stable
- verify onboarding save/load works across app restarts
- fix any renderer build/runtime errors from the latest UI refactor

Definition of done:

- `npm run dev:desktop` works without manual backend confusion
- onboarding survives restart
- saved secrets remain available through keychain

### Phase 2: Improve Zotero fidelity

Goal:

- move from PDF-only indexing toward real Zotero-aware retrieval

Tasks:

- parse Zotero sqlite metadata
- map paper IDs to Zotero item metadata
- include title, authors, year, collections, and attachment links
- improve paper citations shown in answers

Definition of done:

- search results show real paper metadata
- citations are traceable to indexed source records, not just PDF filenames

### Phase 3: Upgrade research UX

Goal:

- make the app feel like a serious research tool rather than a prototype

Tasks:

- improve chat answer rendering
- add citations panel with click-to-open behavior
- add paper chunk preview view
- add better note-write confirmations and vault targeting UX

Definition of done:

- user can clearly see which evidence was used and open the source quickly

### Phase 4: Streaming voice UX

Goal:

- reduce latency and improve hands-free interaction

Tasks:

- partial transcription pipeline
- streaming token-to-speech chunking
- microphone hotkey
- audio playback state and interruption handling

Definition of done:

- user can speak, interrupt, and hear responses with lower latency

### Phase 5: Optional memory/privacy controls

Goal:

- give the user explicit control over local retention

Tasks:

- add setting to disable session-summary memory
- add UI to clear stored memory summaries
- optionally add local encryption for vector store payloads

Definition of done:

- user can understand and control what is retained locally

## 9. Current Acceptance Criteria For MVP

The MVP should be considered working when all of the following are true:

- user can install and run the local desktop app
- user can onboard Anthropic, Zotero, and one or more Obsidian vaults
- app can index Zotero PDFs locally
- app can index Obsidian notes locally
- user can ask a research question and trigger paper retrieval
- assistant can synthesize answers with paper references
- user can search notes and write notes into a chosen vault
- user can open returned papers and notes from the UI

## 10. Current Risks

- Electron/backend startup is still somewhat fragile because local Python resolution can vary by machine
- Tailwind integration may require one clean reinstall after dependency changes
- Zotero metadata quality is not yet strong enough for polished citations
- session memory is useful but may be too permissive for privacy-sensitive use unless controls are added
- no automated tests means regressions are currently caught manually

## 11. How To Use This Document In Future Conversations

Recommended instruction for future threads:

> Use `PROJECT_PLAN.md` in the repo root as the canonical project brief and current status document before making changes.

If there is ever a conflict between a casual chat message and this file, this file should be treated as the more reliable project baseline unless the user explicitly changes direction.

