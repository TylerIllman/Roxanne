"""Tests for ChatOrchestrator — system prompts, event encoding."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from roxanne_backend.models import ToolEvent
from roxanne_backend.orchestrator import ChatOrchestrator


@pytest.fixture
def orchestrator() -> ChatOrchestrator:
    return ChatOrchestrator(
        config_loader=MagicMock(),
        registry_factory=MagicMock(),
        memory_factory=MagicMock(),
    )


class TestSystemPrompt:
    def test_default_prompt(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=False)
        assert "Roxanne" in prompt
        assert "TYPING MODE" in prompt
        assert "VOICE CONVERSATION MODE" not in prompt

    def test_voice_mode_prompt(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=True)
        assert "Roxanne" in prompt
        assert "VOICE CONVERSATION MODE" in prompt
        assert "MAX 2-3 sentences" in prompt
        assert "TYPING MODE" not in prompt

    def test_citation_rules_in_typing(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=False)
        assert "[CITE:" in prompt
        assert "file_path" in prompt.lower() or "CITE" in prompt

    def test_no_cite_format_in_voice(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=True)
        assert "never [CITE" in prompt or "Verbal citations" in prompt

    def test_latex_instructions_in_typing(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=False)
        assert "LaTeX" in prompt
        assert "$" in prompt

    def test_tool_guidance(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=False)
        assert "search_zotero" in prompt
        assert "retrieve_paper_chunks" in prompt
        assert "read_notes" in prompt

    def test_memory_included(self, orchestrator: ChatOrchestrator):
        memories = [{"document": "User prefers concise answers.", "metadata": {}}]
        prompt = orchestrator._system_prompt(memories, voice_mode=False)
        assert "concise answers" in prompt

    def test_voice_narration_rules(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=True)
        assert "Searching now" in prompt or "Let me check" in prompt or "3-6 words" in prompt


class TestEventEncoding:
    def test_encode_status(self, orchestrator: ChatOrchestrator):
        event = ToolEvent(type="status", message="Searching...")
        encoded = orchestrator._encode(event)
        assert isinstance(encoded, bytes)
        assert b"Searching" in encoded
        assert encoded.endswith(b"\n")

    def test_encode_delta(self, orchestrator: ChatOrchestrator):
        event = ToolEvent(type="assistant_delta", delta="Hello")
        encoded = orchestrator._encode(event)
        assert b"Hello" in encoded

    def test_encode_tool_result(self, orchestrator: ChatOrchestrator):
        event = ToolEvent(type="tool_result", tool="search_zotero", payload=[{"title": "Test Paper"}])
        encoded = orchestrator._encode(event)
        assert b"search_zotero" in encoded
        assert b"Test Paper" in encoded


class TestToolStatusMsg:
    def test_known_tools(self, orchestrator: ChatOrchestrator):
        msg = orchestrator._tool_status_msg("search_zotero")
        assert len(msg) > 0

    def test_unknown_tool(self, orchestrator: ChatOrchestrator):
        msg = orchestrator._tool_status_msg("unknown_tool_xyz")
        assert len(msg) > 0  # Should return a fallback message
