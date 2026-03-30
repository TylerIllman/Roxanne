"""Tests for Pydantic models — validation, serialization, defaults."""
from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from roxanne_backend.models import (
    AppConfig,
    AudioTranscriptionRequest,
    ChatRequest,
    ConversationTurn,
    EmbeddingConfig,
    IndexedDocument,
    IndexRequest,
    LLMConfig,
    SpeechConfig,
    SpeechSynthesisRequest,
    ToolEvent,
    VaultConfig,
    ZoteroConfig,
)


# ── LLMConfig ──────────────────────────────────────────────────────


class TestLLMConfig:
    def test_defaults(self):
        c = LLMConfig()
        assert c.provider == "anthropic"
        assert c.api_key is None
        assert c.model == ""
        assert c.max_tokens == 1400

    def test_ollama_no_key_needed(self):
        c = LLMConfig(provider="ollama", model="qwen2.5:7b")
        assert c.api_key is None

    def test_secret_str_api_key(self):
        c = LLMConfig(api_key="sk-test-123")
        assert isinstance(c.api_key, SecretStr)
        assert c.api_key.get_secret_value() == "sk-test-123"

    def test_invalid_provider_rejected(self):
        with pytest.raises(ValidationError):
            LLMConfig(provider="google")


# ── AppConfig ──────────────────────────────────────────────────────


class TestAppConfig:
    def test_defaults(self):
        c = AppConfig()
        assert c.anthropic.provider == "anthropic"
        assert c.obsidian_vaults == []
        assert c.speech.speed == 1.15

    def test_is_complete_anthropic(self):
        c = AppConfig(
            anthropic=LLMConfig(api_key="sk-test", model="claude-sonnet-4-20250514"),
            zotero=ZoteroConfig(storage_path="/tmp/z"),
            obsidian_vaults=[VaultConfig(name="V", path="/tmp/v")],
        )
        assert c.is_complete() is True

    def test_is_complete_ollama_no_key(self):
        c = AppConfig(
            anthropic=LLMConfig(provider="ollama", model="qwen2.5:7b"),
            zotero=ZoteroConfig(storage_path="/tmp/z"),
            obsidian_vaults=[VaultConfig(name="V", path="/tmp/v")],
        )
        assert c.is_complete() is True

    def test_is_incomplete_no_model(self):
        c = AppConfig(
            anthropic=LLMConfig(api_key="sk-test", model=""),
            zotero=ZoteroConfig(storage_path="/tmp/z"),
            obsidian_vaults=[VaultConfig(name="V", path="/tmp/v")],
        )
        assert c.is_complete() is False

    def test_is_incomplete_no_storage(self):
        c = AppConfig(
            anthropic=LLMConfig(api_key="sk-test", model="claude-sonnet-4-20250514"),
        )
        assert c.is_complete() is False

    def test_is_incomplete_no_vaults(self):
        c = AppConfig(
            anthropic=LLMConfig(api_key="sk-test", model="claude-sonnet-4-20250514"),
            zotero=ZoteroConfig(storage_path="/tmp/z"),
        )
        assert c.is_complete() is False

    def test_public_dump_hides_key(self):
        c = AppConfig(anthropic=LLMConfig(api_key="sk-secret"))
        dump = c.public_dump()
        assert dump["anthropic"]["api_key"] == "***"

    def test_public_dump_no_key(self):
        c = AppConfig()
        dump = c.public_dump()
        # No key set: should be None or empty string
        assert dump["anthropic"]["api_key"] in (None, "")

    def test_persistence_dump_strips_key(self):
        c = AppConfig(anthropic=LLMConfig(api_key="sk-secret", model="m"))
        dump = c.persistence_dump()
        # Key should be absent or None (not the actual secret)
        key_val = dump["anthropic"].get("api_key")
        assert key_val is None or key_val == ""

    def test_extra_fields_ignored(self):
        c = AppConfig(unknown_field="hello")
        assert not hasattr(c, "unknown_field")


# ── VaultConfig ────────────────────────────────────────────────────


class TestVaultConfig:
    def test_defaults(self):
        v = VaultConfig(name="My Vault", path="/path")
        assert len(v.id) > 0
        assert v.name == "My Vault"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            VaultConfig(name="", path="/path")


# ── ChatRequest ────────────────────────────────────────────────────


class TestChatRequest:
    def test_minimal(self):
        r = ChatRequest(message="hello")
        assert r.message == "hello"
        assert r.history == []
        assert r.voice_mode is False
        assert len(r.session_id) > 0

    def test_message_required(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="")

    def test_with_history(self):
        r = ChatRequest(
            message="follow up",
            history=[ConversationTurn(role="user", content="hi"), ConversationTurn(role="assistant", content="hello")],
        )
        assert len(r.history) == 2

    def test_voice_mode(self):
        r = ChatRequest(message="test", voice_mode=True)
        assert r.voice_mode is True


# ── Other Models ───────────────────────────────────────────────────


class TestIndexRequest:
    def test_default_scope(self):
        r = IndexRequest()
        assert r.scope == "all"

    def test_custom_scope(self):
        r = IndexRequest(scope="papers")
        assert r.scope == "papers"

    def test_invalid_scope(self):
        with pytest.raises(ValidationError):
            IndexRequest(scope="images")


class TestSpeechConfig:
    def test_defaults(self):
        s = SpeechConfig()
        assert s.stt_model == "small"
        assert s.voice_id == "en_US-amy-medium"
        assert s.speed == 1.15

    def test_custom_speed(self):
        s = SpeechConfig(speed=2.0)
        assert s.speed == 2.0


class TestToolEvent:
    def test_minimal(self):
        e = ToolEvent(type="status")
        assert e.type == "status"
        assert e.message is None
        assert e.delta is None

    def test_full(self):
        e = ToolEvent(type="tool_result", tool="search_zotero", payload=[{"title": "Test"}])
        assert e.tool == "search_zotero"

    def test_json_serialization(self):
        e = ToolEvent(type="assistant_delta", delta="hello")
        j = e.model_dump_json()
        assert "hello" in j


class TestIndexedDocument:
    def test_creation(self):
        d = IndexedDocument(id="abc123", text="some text")
        assert d.metadata == {}

    def test_with_metadata(self):
        d = IndexedDocument(id="x", text="y", metadata={"paper_id": "p1"})
        assert d.metadata["paper_id"] == "p1"
