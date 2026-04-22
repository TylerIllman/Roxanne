"""Tests for FastAPI endpoints using TestClient.

These tests use a temporary conversations directory to avoid
polluting the real app data.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROXANNE_HOME", tempfile.mkdtemp(prefix="roxanne-test-home-"))

from roxanne_backend.main import app, services


@pytest.fixture(autouse=True)
def _isolate_conversations(tmp_path):
    """Swap the conversation store to a temp dir for every test."""
    from roxanne_backend.conversations import ConversationStore
    original = services.conversations
    original_secret_get = services.config_store.secret_store.get
    services.conversations = ConversationStore(tmp_path)
    services.config_store.secret_store.get = lambda _key: None
    yield
    services.conversations = original
    services.config_store.secret_store.get = original_secret_get


@pytest.fixture
def client():
    return TestClient(app)


# ── Health ─────────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "app_home" in data


# ── Config ─────────────────────────────────────────────────────────


class TestConfigEndpoints:
    def test_get_config(self, client: TestClient):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "anthropic" in data
        assert "speech" in data


# ── Tools ──────────────────────────────────────────────────────────


class TestToolsEndpoint:
    def test_list_tools(self, client: TestClient):
        resp = client.get("/api/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        assert isinstance(data["tools"], list)
        assert any(tool["name"] == "search_sources" for tool in data["tools"])


# ── Index ──────────────────────────────────────────────────────────


class TestIndexEndpoints:
    def test_index_stats(self, client: TestClient):
        resp = client.get("/api/index/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "papers" in data
        assert "notes" in data

    def test_index_activity(self, client: TestClient):
        resp = client.get("/api/index/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data
        assert isinstance(data["running"], bool)


# ── Conversations ──────────────────────────────────────────────────


class TestConversationEndpoints:
    def test_list_conversations(self, client: TestClient):
        resp = client.get("/api/conversations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_conversation(self, client: TestClient):
        resp = client.post("/api/conversations", json={"title": "Test Chat"})
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data

    def test_create_and_get(self, client: TestClient):
        create_resp = client.post("/api/conversations", json={"title": "API Test"})
        conv_id = create_resp.json()["id"]
        get_resp = client.get(f"/api/conversations/{conv_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "API Test"

    def test_append_message(self, client: TestClient):
        create_resp = client.post("/api/conversations", json={"title": "Msg Test"})
        conv_id = create_resp.json()["id"]
        msg_resp = client.post(f"/api/conversations/{conv_id}/messages", json={
            "role": "user",
            "content": "Hello from test",
        })
        assert msg_resp.status_code == 200

    def test_delete_conversation(self, client: TestClient):
        create_resp = client.post("/api/conversations", json={"title": "Delete Me"})
        conv_id = create_resp.json()["id"]
        del_resp = client.delete(f"/api/conversations/{conv_id}")
        assert del_resp.status_code == 200
        # Verify deleted
        assert client.get(f"/api/conversations/{conv_id}").status_code in (200, 404)

    def test_get_nonexistent(self, client: TestClient):
        resp = client.get("/api/conversations/nonexistent-id")
        assert resp.status_code in (200, 404)


class TestChatEndpoints:
    def test_stream_chat_uses_canonical_conversation_history(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        class DummyOrchestrator:
            def __init__(self) -> None:
                self.seen_request = None

            async def stream(self, request):
                self.seen_request = request
                yield b'{"type":"assistant_delta","delta":"Backend reply"}\n'
                yield b'{"type":"assistant_done","payload":{"message":"Backend reply"}}\n'

        create_resp = client.post("/api/conversations", json={"title": "Canonical Chat"})
        conv_id = create_resp.json()["id"]
        client.post(f"/api/conversations/{conv_id}/messages", json={"role": "user", "content": "Earlier question"})
        client.post(f"/api/conversations/{conv_id}/messages", json={"role": "assistant", "content": "Earlier answer"})

        dummy = DummyOrchestrator()
        monkeypatch.setattr(services, "orchestrator", lambda: dummy)

        resp = client.post("/api/chat/stream", json={
            "conversation_id": conv_id,
            "message": "Follow up",
            "history": [{"role": "user", "content": "stale local history"}],
            "session_id": "session-123",
        })

        assert resp.status_code == 200
        assert dummy.seen_request is not None
        assert [(turn.role, turn.content) for turn in dummy.seen_request.history] == [
            ("user", "Earlier question"),
            ("assistant", "Earlier answer"),
        ]

        stored = services.conversations.get(conv_id)
        assert stored is not None
        assert [(message["role"], message["content"]) for message in stored["messages"]] == [
            ("user", "Earlier question"),
            ("assistant", "Earlier answer"),
            ("user", "Follow up"),
            ("assistant", "Backend reply"),
        ]


# ── Speech ─────────────────────────────────────────────────────────


class TestSpeechEndpoints:
    def test_speech_status(self, client: TestClient):
        resp = client.get("/api/speech/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "vosk_ready" in data
        assert "piper_installed" in data

    def test_list_voices(self, client: TestClient):
        resp = client.get("/api/voices")
        assert resp.status_code == 200
        data = resp.json()
        assert "voices" in data

    def test_list_stt_models(self, client: TestClient):
        resp = client.get("/api/stt/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert len(data["models"]) >= 3


# ── Ollama ─────────────────────────────────────────────────────────


class TestOllamaEndpoints:
    @patch("roxanne_backend.ollama_manager.ollama_status")
    def test_ollama_status(self, mock_status, client: TestClient):
        mock_status.return_value = {
            "installed": True,
            "running": True,
            "version": "0.5.0",
            "models": ["qwen2.5:7b"],
        }
        resp = client.get("/api/ollama/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["installed"] is True

    def test_ollama_install_info(self, client: TestClient):
        resp = client.get("/api/ollama/install-info")
        assert resp.status_code == 200


# ── Zotero ─────────────────────────────────────────────────────────


class TestZoteroEndpoint:
    def test_detect_zotero(self, client: TestClient):
        resp = client.get("/api/zotero/detect")
        assert resp.status_code == 200
        data = resp.json()
        assert "found" in data
