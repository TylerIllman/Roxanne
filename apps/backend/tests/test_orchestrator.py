"""Tests for ChatOrchestrator — system prompts, event encoding."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from roxanne_backend.models import AppConfig, LLMConfig, ToolEvent
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
        assert "conversational" in prompt
        assert "TYPING MODE" not in prompt

    def test_citation_rules_in_typing(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=False)
        assert "[CITE:" in prompt
        assert "file_path" in prompt.lower() or "CITE" in prompt

    def test_no_cite_format_in_voice(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=True)
        assert "[CITE:" in prompt
        assert "lead author plus year" in prompt or "Smith 2023" in prompt
        assert "ONLY structured markup allowed" in prompt

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

    def test_voice_mode_avoids_metadata_dumps(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=True)
        assert "Do not list long author rosters" in prompt

    def test_voice_mode_requires_plain_text(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=True)
        assert "Return plain text only" in prompt
        assert "only allowed markup is [CITE:...]" in prompt
        assert "Never output literal markdown markers" in prompt

    def test_voice_mode_forbids_list_style_output(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=True)
        assert "NO bullet points" in prompt
        assert "NO numbered lists" in prompt
        assert "rewrite it as a short spoken explanation" in prompt

    def test_typing_mode_defaults_to_moderate_detail(self, orchestrator: ChatOrchestrator):
        prompt = orchestrator._system_prompt([], voice_mode=False)
        assert "moderate detail" in prompt
        assert "explicitly asks for lots of detail" in prompt


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


class TestLoopLimit:
    def test_uses_configured_loop_limit(self, orchestrator: ChatOrchestrator):
        config = AppConfig(anthropic=LLMConfig(max_tool_loops=18))
        assert orchestrator._max_tool_loops(config) == 18

    def test_loop_limit_supports_higher_bound(self, orchestrator: ChatOrchestrator):
        config = AppConfig(anthropic=LLMConfig(max_tool_loops=30))
        assert orchestrator._max_tool_loops(config) == 30
