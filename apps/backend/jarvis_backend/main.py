from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple
from uuid import uuid4

import anyio
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

from jarvis_backend.config import ConfigStore
from jarvis_backend.ingestion.indexer import ContentIndexer
from jarvis_backend.models import (
    AppConfig,
    ChatRequest,
    IndexRequest,
    SpeechSynthesisRequest,
)
from jarvis_backend.orchestrator import ChatOrchestrator
from jarvis_backend.retrieval import RetrievalStore, SessionMemoryStore
from jarvis_backend.speech import SpeechService
from jarvis_backend.storage import AppPaths
from jarvis_backend.tools.obsidian import ReadNotesTool, WriteNoteTool
from jarvis_backend.tools.registry import ToolRegistry
from jarvis_backend.tools.zotero import (
    GetCollectionPapersTool,
    GetPaperAnnotationsTool,
    GetPaperMetadataTool,
    GetPaperNotesTool,
    ListZoteroCollectionsTool,
    OpenPdfTool,
    RetrievePaperChunksTool,
    SearchZoteroMetadataTool,
    SearchZoteroNotesTool,
    SearchZoteroTool,
)


def allowed_origins() -> list[str]:
    configured = os.getenv("JARVIS_ALLOWED_ORIGINS")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "null",
        "file://",
    ]


class ServiceContainer:
    def __init__(self) -> None:
        self.paths = AppPaths()
        self.paths.ensure()
        self.paths.prune_audio_files()
        self.config_store = ConfigStore(self.paths)
        self.speech = SpeechService(self.paths)
        from jarvis_backend.conversations import ConversationStore
        self.conversations = ConversationStore(self.paths.root)
        self._retrieval_cache: Optional[Tuple[str, RetrievalStore]] = None

    def load_config(self) -> AppConfig:
        return self.config_store.load()

    def save_config(self, config: AppConfig) -> AppConfig:
        saved = self.config_store.save(config)
        self._retrieval_cache = None
        return saved

    def retrieval(self, config: AppConfig) -> RetrievalStore:
        signature = (
            f"{config.embeddings.provider}:"
            f"{config.embeddings.model}:"
            f"{bool(config.embeddings.openai_api_key)}"
        )
        if self._retrieval_cache and self._retrieval_cache[0] == signature:
            return self._retrieval_cache[1]
        store = RetrievalStore(self.paths, config.embeddings)
        self._retrieval_cache = (signature, store)
        return store

    def indexer(self, config: AppConfig) -> ContentIndexer:
        return ContentIndexer(self.retrieval(config))

    def tool_registry(self, config: AppConfig) -> ToolRegistry:
        retrieval = self.retrieval(config)
        return ToolRegistry(
            [
                # Zotero vector search
                SearchZoteroTool(retrieval),
                RetrievePaperChunksTool(retrieval),
                OpenPdfTool(retrieval),
                # Zotero database tools
                GetPaperMetadataTool(self.config_store, retrieval),
                ListZoteroCollectionsTool(self.config_store),
                SearchZoteroMetadataTool(self.config_store),
                GetPaperNotesTool(self.config_store, retrieval),
                GetPaperAnnotationsTool(self.config_store, retrieval),
                SearchZoteroNotesTool(retrieval),
                GetCollectionPapersTool(self.config_store),
                # Obsidian
                ReadNotesTool(retrieval),
                WriteNoteTool(self.config_store, self.indexer(config)),
            ]
        )

    def orchestrator(self) -> ChatOrchestrator:
        return ChatOrchestrator(
            config_loader=self.load_config,
            registry_factory=self.tool_registry,
            memory_factory=lambda config: SessionMemoryStore(self.retrieval(config)),
        )


services = ServiceContainer()
app = FastAPI(title="Jarvis Assistant Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
async def health() -> Dict[str, object]:
    config = services.load_config()
    return {
        "status": "ok",
        "config_complete": config.is_complete(),
        "app_home": str(services.paths.root),
    }


@app.get("/api/config")
async def get_config() -> Dict[str, object]:
    return services.load_config().public_dump()


@app.post("/api/config")
async def save_config(config: AppConfig) -> Dict[str, object]:
    return services.save_config(config).public_dump()


@app.get("/api/tools")
async def list_tools() -> Dict[str, object]:
    config = services.load_config()
    return {"tools": services.tool_registry(config).schemas()}


@app.post("/api/index")
async def run_index(request: IndexRequest) -> Dict[str, object]:
    config = services.load_config()
    indexer = services.indexer(config)

    if request.scope == "papers":
        report = await anyio.to_thread.run_sync(indexer.index_papers, config)
    elif request.scope == "notes":
        report = await anyio.to_thread.run_sync(indexer.index_notes, config)
    else:
        report = await anyio.to_thread.run_sync(indexer.index_all, config)

    return {"scope": request.scope, "report": report}


@app.get("/api/index/browse/{collection}")
async def browse_index(
    collection: str, limit: int = 500, offset: int = 0, full_text: bool = False
) -> Dict[str, object]:
    """Browse indexed documents in a collection (papers, notes, memories)."""
    allowed = {"papers", "notes", "memories", "zotero_notes"}
    if collection not in allowed:
        return {"error": f"Unknown collection. Use one of: {allowed}"}
    config = services.load_config()
    try:
        store = services.retrieval(config)
        return store.list_collection(
            collection, limit=min(limit, 2000), offset=offset, full_text=full_text
        )
    except Exception as exc:
        return {"error": str(exc), "total": 0, "items": []}


@app.get("/api/index/tree/{collection}")
async def index_tree(collection: str) -> Dict[str, object]:
    """Return items grouped by their hierarchy (collections for papers, folders for notes)."""
    allowed = {"papers", "notes", "zotero_notes"}
    if collection not in allowed:
        return {"error": f"Unknown collection. Use one of: {allowed}"}
    config = services.load_config()
    try:
        store = services.retrieval(config)
        data = store.list_collection(collection, limit=2000, offset=0, full_text=False)
        items = data.get("items", [])

        if collection == "papers":
            return _build_paper_tree(items)
        elif collection == "notes":
            return _build_note_tree(items)
        else:
            return _build_zotero_note_tree(items)
    except Exception as exc:
        return {"error": str(exc), "groups": []}


def _build_paper_tree(items: list) -> Dict[str, object]:
    """Group papers by Zotero collection, then by paper."""
    from collections import defaultdict

    collection_papers: dict = defaultdict(dict)  # collection -> paper_id -> info
    uncategorized: dict = {}

    for item in items:
        meta = item.get("metadata", {})
        paper_id = meta.get("paper_id", item["id"])
        title = meta.get("title", "Untitled")
        collections_str = meta.get("collections", "")
        collections = [c.strip() for c in collections_str.split(";") if c.strip()] if collections_str else []

        paper_info = {
            "paper_id": paper_id,
            "title": title,
            "authors": meta.get("authors", ""),
            "year": meta.get("year", ""),
            "tags": meta.get("tags", ""),
            "total_chunks": meta.get("total_chunks", 0),
            "total_pages": meta.get("total_pages", 0),
        }

        if not collections:
            uncategorized[paper_id] = paper_info
        else:
            for coll in collections:
                collection_papers[coll][paper_id] = paper_info

    groups = []
    for coll_name in sorted(collection_papers.keys()):
        papers = list(collection_papers[coll_name].values())
        groups.append({
            "name": coll_name,
            "type": "collection",
            "paper_count": len(papers),
            "papers": papers,
        })
    if uncategorized:
        groups.append({
            "name": "Uncategorized",
            "type": "collection",
            "paper_count": len(uncategorized),
            "papers": list(uncategorized.values()),
        })

    return {"groups": groups, "total_papers": len({item.get("metadata", {}).get("paper_id") for item in items})}


def _build_note_tree(items: list) -> Dict[str, object]:
    """Build a folder tree for Obsidian notes."""
    from collections import defaultdict

    vault_folders: dict = defaultdict(lambda: defaultdict(list))  # vault -> folder -> notes

    seen_notes: dict = {}
    for item in items:
        meta = item.get("metadata", {})
        note_id = meta.get("note_id", item["id"])
        if note_id in seen_notes:
            continue
        seen_notes[note_id] = True
        vault_name = meta.get("vault_name", "Unknown")
        folder = meta.get("folder_path", "") or ""
        vault_folders[vault_name][folder].append({
            "note_id": note_id,
            "title": meta.get("title", "Untitled"),
            "relative_path": meta.get("relative_path", ""),
            "total_chunks": meta.get("total_chunks", 0),
        })

    groups = []
    for vault_name in sorted(vault_folders.keys()):
        folders = []
        for folder_path in sorted(vault_folders[vault_name].keys()):
            notes = vault_folders[vault_name][folder_path]
            folders.append({
                "path": folder_path or "(root)",
                "note_count": len(notes),
                "notes": notes,
            })
        groups.append({
            "name": vault_name,
            "type": "vault",
            "folder_count": len(folders),
            "total_notes": sum(len(f["notes"]) for f in folders),
            "folders": folders,
        })

    return {"groups": groups, "total_notes": len(seen_notes)}


def _build_zotero_note_tree(items: list) -> Dict[str, object]:
    """Group Zotero notes by parent paper."""
    seen: dict = {}
    for item in items:
        meta = item.get("metadata", {})
        note_id = meta.get("note_id", item["id"])
        if note_id in seen:
            continue
        parent_title = meta.get("parent_title", "Unknown paper")
        seen[note_id] = {
            "note_id": note_id,
            "note_type": meta.get("note_type", "note"),
            "parent_title": parent_title,
            "collections": meta.get("collections", ""),
            "total_chunks": meta.get("total_chunks", 0),
        }

    from collections import defaultdict
    by_parent: dict = defaultdict(list)
    for info in seen.values():
        by_parent[info["parent_title"]].append(info)

    groups = [
        {"parent_title": title, "notes": notes, "note_count": len(notes)}
        for title, notes in sorted(by_parent.items())
    ]
    return {"groups": groups, "total_notes": len(seen)}


@app.get("/api/index/stats")
async def index_stats() -> Dict[str, object]:
    """Return document counts for each vector collection."""
    config = services.load_config()
    try:
        store = services.retrieval(config)
        papers = store._collection(store.PAPER_COLLECTION).count()
        notes = store._collection(store.NOTE_COLLECTION).count()
        memories = store._collection(store.MEMORY_COLLECTION).count()
        zotero_notes = store._collection("zotero_notes").count()
    except Exception:
        papers = notes = memories = zotero_notes = 0
    return {
        "papers": papers,
        "notes": notes,
        "memories": memories,
        "zotero_notes": zotero_notes,
    }


# ── Conversations ───────────────────────────────────────────────

@app.get("/api/conversations")
async def list_conversations():
    return services.conversations.list_all()


@app.post("/api/conversations")
async def create_conversation(body: Dict = None):
    title = (body or {}).get("title", "New conversation")
    return services.conversations.create(title)


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    data = services.conversations.get(conv_id)
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return data


@app.post("/api/conversations/{conv_id}/messages")
async def append_conversation_message(conv_id: str, body: Dict):
    services.conversations.append_message(conv_id, body["role"], body["content"])
    return {"ok": True}


@app.patch("/api/conversations/{conv_id}")
async def update_conversation(conv_id: str, body: Dict):
    if "title" in body:
        services.conversations.update_title(conv_id, body["title"])
    return {"ok": True}


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    ok = services.conversations.delete(conv_id)
    return {"ok": ok}


# ── Chat ────────────────────────────────────────────────────────

@app.post("/api/chat/stream")
async def stream_chat(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        services.orchestrator().stream(request),
        media_type="application/x-ndjson",
    )


@app.post("/api/audio/transcribe-upload")
async def transcribe_audio_upload(file: UploadFile = File(...)) -> Dict[str, str]:
    config = services.load_config()
    services.paths.ensure()

    audio_bytes = await file.read()
    text = await anyio.to_thread.run_sync(
        lambda: services.speech.transcribe_bytes(audio_bytes, config)
    )
    return {"text": text}


@app.post("/api/audio/speak")
async def synthesize_audio(request: SpeechSynthesisRequest) -> Dict[str, str]:
    config = services.load_config()
    audio_path = await anyio.to_thread.run_sync(services.speech.synthesize, request.text, config)
    # Return both the path and a URL the renderer can use to play the audio
    filename = Path(audio_path).name
    return {"audio_path": audio_path, "audio_url": f"/api/audio/files/{filename}"}


@app.get("/api/audio/files/{filename}")
async def serve_audio_file(filename: str):
    """Serve a synthesized audio file so the renderer can play it via HTTP."""
    # Sanitize filename to prevent path traversal
    safe_name = Path(filename).name
    file_path = services.paths.audio_path / safe_name
    if not file_path.exists() or not file_path.is_file():
        return JSONResponse(status_code=404, content={"error": "Audio file not found"})
    return FileResponse(str(file_path), media_type="audio/wav")


@app.get("/api/voices")
async def list_voices() -> Dict[str, object]:
    return services.speech.list_voices()


@app.post("/api/voices/download/{voice_id}")
async def download_voice(voice_id: str) -> StreamingResponse:
    """Download a voice model with streaming progress."""
    import queue
    import threading

    event_queue: queue.Queue = queue.Queue()
    done_sentinel = object()

    def run():
        try:
            path = services.speech.download_voice(voice_id)
            event_queue.put({"status": "done", "voice_id": voice_id, "path": path})
        except Exception as exc:
            event_queue.put({"status": "error", "detail": str(exc)})
        finally:
            event_queue.put(done_sentinel)

    async def generate():
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        # Yield a starting event immediately
        yield (json.dumps({"status": "downloading", "voice_id": voice_id}) + "\n").encode()
        while True:
            events = []
            try:
                while True:
                    item = event_queue.get_nowait()
                    if item is done_sentinel:
                        for ev in events:
                            yield (json.dumps(ev) + "\n").encode()
                        return
                    events.append(item)
            except queue.Empty:
                pass
            for ev in events:
                yield (json.dumps(ev) + "\n").encode()
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/api/zotero/detect")
async def detect_zotero() -> Dict[str, object]:
    """Auto-detect Zotero data directory on this machine."""
    import platform as _platform

    home = Path.home()
    system = _platform.system().lower()

    # Zotero default data directories per platform
    candidates = []
    if system == "darwin":
        candidates = [
            home / "Zotero",
            home / "Library" / "Application Support" / "Zotero" / "Profiles",
        ]
    elif system == "linux":
        candidates = [
            home / "Zotero",
            home / ".zotero" / "zotero",
        ]
    elif system == "windows":
        candidates = [
            home / "Zotero",
            home / "AppData" / "Roaming" / "Zotero" / "Zotero" / "Profiles",
        ]

    # Also check the Zotero prefs for a custom data directory
    # But the most reliable approach: look for ~/Zotero/storage
    storage_path = None
    database_path = None

    for candidate in candidates:
        s = candidate / "storage"
        d = candidate / "zotero.sqlite"
        if s.is_dir():
            storage_path = str(s)
            if d.is_file():
                database_path = str(d)
            break
        # Also check if the candidate itself has zotero.sqlite (profile-based)
        if d.is_file() and not storage_path:
            database_path = str(d)

    return {
        "found": storage_path is not None,
        "storage_path": storage_path,
        "database_path": database_path,
    }


# ── Ollama management ───────────────────────────────────────────

@app.get("/api/ollama/status")
async def get_ollama_status() -> Dict[str, object]:
    from jarvis_backend.ollama_manager import ollama_status
    return await anyio.to_thread.run_sync(ollama_status)


@app.post("/api/ollama/start")
async def start_ollama() -> Dict[str, object]:
    from jarvis_backend.ollama_manager import start_ollama_server
    return await anyio.to_thread.run_sync(start_ollama_server)


@app.get("/api/ollama/install-info")
async def ollama_install_info() -> Dict[str, object]:
    from jarvis_backend.ollama_manager import install_instructions
    return install_instructions()


@app.post("/api/ollama/pull/{model_name:path}")
async def pull_ollama_model(model_name: str) -> StreamingResponse:
    """Pull an Ollama model with streaming progress."""
    import queue
    import threading
    from jarvis_backend.ollama_manager import pull_model_streaming

    event_queue: queue.Queue = queue.Queue()
    done_sentinel = object()

    def run():
        try:
            for event in pull_model_streaming(model_name):
                event_queue.put(event)
        except Exception as exc:
            event_queue.put({"status": "error", "progress": 0, "detail": str(exc)})
        finally:
            event_queue.put(done_sentinel)

    async def generate():
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        while True:
            events = []
            try:
                while True:
                    item = event_queue.get_nowait()
                    if item is done_sentinel:
                        for ev in events:
                            yield (json.dumps(ev) + "\n").encode()
                        return
                    events.append(item)
            except queue.Empty:
                pass
            for ev in events:
                yield (json.dumps(ev) + "\n").encode()
            await asyncio.sleep(0.3)

    return StreamingResponse(generate(), media_type="application/x-ndjson")


# ── Speech ──────────────────────────────────────────────────────

@app.get("/api/speech/status")
async def speech_status() -> Dict[str, object]:
    return services.speech.speech_status()


@app.post("/api/speech/setup")
async def speech_setup() -> StreamingResponse:
    """Stream speech setup progress as NDJSON events.

    Runs the blocking download in a thread, polls progress, and yields
    NDJSON events to the client every 300ms so the UI stays responsive.
    """
    import queue
    import threading
    import time

    event_queue: queue.Queue = queue.Queue()
    done_sentinel = object()

    def run_setup():
        """Run in background thread, push events to queue."""
        try:
            for event in services.speech.setup_speech_streaming():
                event_queue.put(event)
        except Exception as exc:
            event_queue.put({"step": "error", "status": "error", "progress": 0, "detail": str(exc)})
        finally:
            event_queue.put(done_sentinel)

    async def generate():
        thread = threading.Thread(target=run_setup, daemon=True)
        thread.start()
        print("[speech-setup] Endpoint called, streaming thread started.", flush=True)

        while True:
            # Drain all available events from the queue
            events = []
            try:
                while True:
                    item = event_queue.get_nowait()
                    if item is done_sentinel:
                        # Yield any remaining events then stop
                        for ev in events:
                            line = json.dumps(ev) + "\n"
                            print(f"[speech-setup] -> {ev['step']}/{ev['status']}: {ev.get('detail','')}", flush=True)
                            yield line.encode()
                        print("[speech-setup] Streaming complete.", flush=True)
                        return
                    events.append(item)
            except queue.Empty:
                pass

            # Yield collected events
            for ev in events:
                line = json.dumps(ev) + "\n"
                print(f"[speech-setup] -> {ev['step']}/{ev['status']}: {ev.get('detail','')}", flush=True)
                yield line.encode()

            # Wait a bit before polling again
            await asyncio.sleep(0.3)

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/api/stt/models")
async def list_stt_models() -> Dict[str, object]:
    """List available STT models with install status."""
    return services.speech.list_stt_models()


@app.post("/api/stt/download/{model_id:path}")
async def download_stt_model(model_id: str) -> StreamingResponse:
    """Download an STT model with streaming progress."""
    import queue
    import threading

    event_queue: queue.Queue = queue.Queue()
    done_sentinel = object()

    def run():
        try:
            for event in services.speech.download_stt_model(model_id):
                event_queue.put(event)
        except Exception as exc:
            event_queue.put({"status": "error", "progress": 0, "detail": str(exc)})
        finally:
            event_queue.put(done_sentinel)

    async def generate():
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        yield (json.dumps({"status": "downloading", "model_id": model_id}) + "\n").encode()
        while True:
            events = []
            try:
                while True:
                    item = event_queue.get_nowait()
                    if item is done_sentinel:
                        for ev in events:
                            yield (json.dumps(ev) + "\n").encode()
                        return
                    events.append(item)
            except queue.Empty:
                pass
            for ev in events:
                yield (json.dumps(ev) + "\n").encode()
            await asyncio.sleep(0.3)

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.websocket("/api/audio/stream")
async def ws_stream_transcription(ws: WebSocket):
    """
    Real-time streaming transcription via WebSocket using Vosk.

    Protocol:
    - Client sends binary audio chunks (PCM float32, 16kHz mono) continuously
    - Vosk processes each chunk instantly and returns partial/final results in real time
    - Client sends text message "END" to signal end of utterance (get final result + reset)
    - Client sends text message "RESET" to discard current recognizer and start fresh
    - Server sends JSON: {"type": "partial", "text": "..."} or {"type": "final", "text": "..."}
    """
    await ws.accept()

    sample_rate = 16000
    recognizer = None
    last_partial = ""

    try:
        # Pre-load the vosk model using configured STT model
        config = services.config_store.load()
        recognizer = services.speech.create_recognizer(sample_rate, config)

        while True:
            message = await ws.receive()

            if message.get("type") == "websocket.disconnect":
                break

            # Text message = control signal
            if "text" in message:
                text_msg = message["text"]

                if text_msg == "END":
                    # Get final result from recognizer
                    if recognizer is not None:
                        final = json.loads(recognizer.FinalResult())
                        final_text = final.get("text", "").strip()
                        await ws.send_json({"type": "final", "text": final_text})
                        # Reset recognizer for next utterance
                        recognizer = services.speech.create_recognizer(sample_rate)
                        last_partial = ""
                    continue

                if text_msg == "RESET":
                    recognizer = services.speech.create_recognizer(sample_rate)
                    last_partial = ""
                    continue

                # Config update (e.g., sample rate)
                try:
                    ctrl = json.loads(text_msg)
                    if "sample_rate" in ctrl:
                        sample_rate = int(ctrl["sample_rate"])
                        recognizer = services.speech.create_recognizer(sample_rate)
                        last_partial = ""
                    continue
                except (json.JSONDecodeError, ValueError):
                    continue

            # Binary message = audio data
            if "bytes" in message and recognizer is not None:
                raw = message["bytes"]

                # Convert float32 PCM to int16 PCM (Vosk expects 16-bit PCM)
                import numpy as np
                floats = np.frombuffer(raw, dtype=np.float32)
                int16_data = (floats * 32767).clip(-32768, 32767).astype(np.int16).tobytes()

                # Feed to Vosk — it processes immediately
                if recognizer.AcceptWaveform(int16_data):
                    # Vosk detected end of phrase — send final result
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").strip()
                    if text:
                        await ws.send_json({"type": "final", "text": text})
                        last_partial = ""
                else:
                    # Partial result — send as interim transcript
                    partial = json.loads(recognizer.PartialResult())
                    partial_text = partial.get("partial", "").strip()
                    if partial_text and partial_text != last_partial:
                        last_partial = partial_text
                        await ws.send_json({"type": "interim", "text": partial_text})

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"WebSocket transcription error: {exc}")
        try:
            await ws.send_json({"type": "error", "text": str(exc)})
        except Exception:
            pass


@app.exception_handler(Exception)
async def handle_error(_, exc: Exception):
    return JSONResponse(status_code=500, content={"error": str(exc)})
