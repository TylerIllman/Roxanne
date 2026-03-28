# Jarvis Assistant

Jarvis Assistant is a local-first personal research copilot with:

- an Electron desktop UI built with React and TypeScript
- a Python backend for orchestration, retrieval, and local integrations
- onboarding for Anthropic, Zotero, Obsidian, embeddings, and speech settings
- a modular tool registry designed for Claude tool use
- OS keychain storage for API secrets

Project reference: see `PROJECT_PLAN.md` for the current architecture, status, and next-step implementation plan.

## Stack

- UI: Electron, React, TypeScript, Rsbuild, Tailwind CSS
- Backend: FastAPI, Pydantic, Anthropic SDK
- Retrieval: Chroma, local embeddings via FastEmbed
- PDF parsing: PyMuPDF
- Speech: faster-whisper, Piper

## Repo Layout

```text
apps/
  backend/   FastAPI backend, tools, indexing, and orchestration
  desktop/   Electron shell and React renderer
```

## Prerequisites

This workspace currently only has `python3` available on PATH. You will also need:

- Node.js 20+
- npm 10+
- Python 3.10+ recommended

## Backend Setup

```bash
cd apps/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m uvicorn jarvis_backend.main:app --reload
```

If you already had the backend environment created before the security update, rerun `pip install -e .` so the new `keyring` dependency is installed.

## Desktop Setup

```bash
cd apps/desktop
npm install
npm run dev
```

The Electron app spawns the Python backend with `python3` by default. You can override the backend entrypoint with:

```bash
export JARVIS_BACKEND_CMD="python3 -m uvicorn jarvis_backend.main:app --host 127.0.0.1 --port 8000"
```

## Current MVP Scope In This Scaffold

- onboarding for Anthropic API key, model, Zotero paths, multiple Obsidian vaults, embeddings, and speech settings
- a streaming chat endpoint with Claude tool orchestration
- local tools for Zotero search, note read/write, and PDF open
- indexing services for PDFs and markdown notes

## Not Finished Yet

- packaged desktop build
- robust Zotero database metadata extraction
- web search provider integration
- production-grade speech streaming
