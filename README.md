# Roxanne

A local-first personal research copilot. Chat with your papers, notes, and knowledge base using Anthropic, OpenAI, or local Ollama models.

## Download

For normal users, the best path is the packaged desktop app:

- [Download the latest Roxanne installer from Releases](../../releases/latest)
- [Browse all published installers](../../releases)

Once you push a version tag such as `v0.1.0`, the release workflow in [`.github/workflows/release.yml`](.github/workflows/release.yml) will build and attach platform-specific installers:

- macOS: `.dmg`
- Windows: `.exe`
- Linux: `AppImage`

## Install The App Locally

If you want a real installable app bundle instead of running Roxanne in dev mode:

### Prerequisites

- **Python 3.10+**
- **Node.js 20+**
- platform build tools for Electron packaging
- optional: code signing/notarization setup if you want polished production installers

### Build an installer

From the repo root:

```bash
npm install
npm run dist:desktop
```

That command now does all of this:

1. installs backend packaging deps into the backend Python environment if needed
2. builds a standalone backend executable with PyInstaller
3. builds the Electron renderer and main process
4. creates installable desktop artifacts in `apps/desktop/release`

Useful variants:

```bash
# Build unpacked app output only
npm run pack:desktop

# Build just the backend executable
npm run build:backend-binary
```

### Install the built app

- macOS: open the generated `.dmg`, drag `Roxanne.app` into `Applications`
- Windows: run the generated `.exe` installer
- Linux: run the generated `AppImage` or unpack the tarball

## Developer Quick Start

### Prerequisites

- **Python 3.10+** and **Node.js 20+**
- optional: [Ollama](https://ollama.com) for local models

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

### 4. Run in development

Open two terminals:

```bash
# Terminal 1
cd apps/backend
source .venv/bin/activate
python -m uvicorn roxanne_backend.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2
cd apps/desktop
npm run dev
```

Or from the repo root:

```bash
npm run dev:backend
npm run dev:desktop
```

The app opens automatically. Walk through the setup wizard to connect your LLM, Zotero library, and Obsidian vaults.

## Release Automation

GitHub Actions now covers both everyday changes and releases:

- push branches or open a PR: [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs backend tests plus the desktop type-check and build
- push a tag like `v0.1.0`: [`.github/workflows/release.yml`](.github/workflows/release.yml) builds macOS, Windows, and Linux installers and uploads them to the matching GitHub Release

You can also trigger the workflow manually from the Actions tab.

### Maintainer release flow

Once the repo is on GitHub, publishing a downloadable app is:

```bash
git tag v0.1.0
git push origin v0.1.0
```

That tag triggers the release workflow, which builds installers and publishes them to GitHub Releases so people can install Roxanne without running any dev commands.

## Running Tests

```bash
cd apps/backend
source .venv/bin/activate
pip install -e ".[test]"
pytest
```

## Stack

| Layer | Technology |
|-------|-----------|
| UI | Electron, React, TypeScript, Rsbuild, Tailwind CSS |
| Backend | FastAPI, Pydantic, Uvicorn |
| Packaging | PyInstaller, Electron Builder, GitHub Actions |
| LLM | Anthropic SDK, OpenAI SDK, Ollama (local) |
| Retrieval | ChromaDB, FastEmbed (BAAI/bge) |
| PDF | PyMuPDF |
| Speech | Vosk (STT), Piper (TTS) |

## Repo Layout

```text
apps/
  backend/            FastAPI backend, tools, indexing, orchestration
    roxanne_backend/  Python package
    tests/            pytest suite
  desktop/            Electron shell + React renderer
    src/main/         Electron main process
    src/renderer/     React app
scripts/
  build-backend-binary.mjs
.github/workflows/
  release.yml
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ROXANNE_BACKEND_URL` | `http://127.0.0.1:8000` | Backend URL for the Electron app |
| `ROXANNE_RENDERER_URL` | built files or dev server | Dev server URL for hot reload |
| `ROXANNE_BACKEND_CMD` | unset | Override the backend command Electron should launch |
| `ROXANNE_PYTHON_BIN` | auto-detected | Override the Python interpreter used when building the backend binary |
| `ROXANNE_HOME` | platform app-data dir | Override where Roxanne stores local config, secrets, and indexes |

## Design System

See [`apps/desktop/src/renderer/DESIGN_SYSTEM.md`](apps/desktop/src/renderer/DESIGN_SYSTEM.md) for UI tokens, component patterns, and styling rules.
