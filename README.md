# Roxanne

A local-first personal research copilot. Chat with your papers, notes, and knowledge base using Anthropic, OpenAI, or local Ollama models.

## Quick Start

### Prerequisites

- **Python 3.10+** and **Node.js 20+**
- (Optional) [Ollama](https://ollama.com) for local models

### 1. Clone and install

```bash
git clone <repo-url> && cd roxanne
```

### 2. Backend

```bash
cd apps/backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

### 3. Frontend

```bash
cd apps/desktop
npm install
```

### 4. Run (development)

Open **two terminals**:

```bash
# Terminal 1 — backend with hot reload
cd apps/backend
source .venv/bin/activate
python -m uvicorn roxanne_backend.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — Electron + React dev server
cd apps/desktop
npm run dev
```

Or from the repo root:

```bash
# Backend
npm run dev:backend

# Desktop (separate terminal)
npm run dev:desktop
```

The app opens automatically. Walk through the setup wizard to connect your LLM, Zotero library, and Obsidian vaults.

### 5. Run (production)

```bash
# Build the frontend
cd apps/desktop && npm run build

# Start backend
cd apps/backend
source .venv/bin/activate
python -m uvicorn roxanne_backend.main:app --host 127.0.0.1 --port 8000

# Start Electron (loads built files)
cd apps/desktop
npx electron dist-electron/main.js
```

## Running Tests

```bash
cd apps/backend
source .venv/bin/activate
pip install -e ".[test]"
pytest                    # all tests
pytest -x                 # stop on first failure
pytest --cov              # with coverage report
pytest -k "test_models"   # run specific test file
```

## Stack

| Layer | Technology |
|-------|-----------|
| UI | Electron, React, TypeScript, Rsbuild, Tailwind CSS |
| Backend | FastAPI, Pydantic, Uvicorn |
| LLM | Anthropic SDK, OpenAI SDK, Ollama (local) |
| Retrieval | ChromaDB, FastEmbed (BAAI/bge) |
| PDF | PyMuPDF |
| Speech | Vosk (STT), Piper (TTS) |

## Repo Layout

```
apps/
  backend/          FastAPI backend, tools, indexing, orchestration
    roxanne_backend/  Python package
    tests/            pytest suite
  desktop/          Electron shell + React renderer
    src/main/         Electron main process
    src/renderer/     React app
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ROXANNE_BACKEND_URL` | `http://127.0.0.1:8000` | Backend URL for the Electron app |
| `ROXANNE_CORS_ORIGINS` | dev defaults | Comma-separated allowed origins |
| `ROXANNE_RENDERER_URL` | (built files) | Dev server URL for hot reload |

## Design System

See [`apps/desktop/src/renderer/DESIGN_SYSTEM.md`](apps/desktop/src/renderer/DESIGN_SYSTEM.md) for UI tokens, component patterns, and styling rules.
