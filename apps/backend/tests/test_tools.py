"""Tests for tool registry and tool execution."""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from roxanne_backend.models import EmbeddingConfig, IndexedDocument
from roxanne_backend.retrieval import RetrievalStore
from roxanne_backend.tools.base import BaseTool, ToolExecutionError
from roxanne_backend.tools.registry import ToolRegistry
from roxanne_backend.tools.search import SearchSourcesTool


# ── Test Tool Implementations ──────────────────────────────────────


class EchoTool(BaseTool):
    name = "echo"
    description = "Echoes back the input."
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def invoke(self, payload: Dict[str, Any]) -> Dict[str, str]:
        return {"echoed": payload["text"]}


class FailTool(BaseTool):
    name = "fail"
    description = "Always fails."
    input_schema = {"type": "object", "properties": {}}

    async def invoke(self, payload: Dict[str, Any]) -> Any:
        raise ToolExecutionError("Intentional failure")


class MultiplyTool(BaseTool):
    name = "multiply"
    description = "Multiplies two numbers."
    input_schema = {
        "type": "object",
        "properties": {
            "a": {"type": "number"},
            "b": {"type": "number"},
        },
        "required": ["a", "b"],
    }

    async def invoke(self, payload: Dict[str, Any]) -> Dict[str, float]:
        return {"result": payload["a"] * payload["b"]}


# ── ToolRegistry Tests ─────────────────────────────────────────────


class TestToolRegistry:
    @pytest.fixture
    def registry(self) -> ToolRegistry:
        return ToolRegistry([EchoTool(), FailTool(), MultiplyTool()])

    def test_schemas(self, registry: ToolRegistry):
        schemas = registry.schemas()
        assert len(schemas) == 3
        names = {s["name"] for s in schemas}
        assert names == {"echo", "fail", "multiply"}

    def test_schema_has_description(self, registry: ToolRegistry):
        schemas = registry.schemas()
        for s in schemas:
            assert "description" in s
            assert len(s["description"]) > 0

    @pytest.mark.asyncio
    async def test_execute_echo(self, registry: ToolRegistry):
        result = await registry.execute("echo", {"text": "hello"})
        assert result == {"echoed": "hello"}

    @pytest.mark.asyncio
    async def test_execute_multiply(self, registry: ToolRegistry):
        result = await registry.execute("multiply", {"a": 3, "b": 7})
        assert result == {"result": 21}

    @pytest.mark.asyncio
    async def test_execute_fail(self, registry: ToolRegistry):
        with pytest.raises(ToolExecutionError, match="Intentional failure"):
            await registry.execute("fail", {})

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, registry: ToolRegistry):
        with pytest.raises((KeyError, ToolExecutionError)):
            await registry.execute("nonexistent", {})


# ── BaseTool Tests ─────────────────────────────────────────────────


class TestBaseTool:
    def test_anthropic_schema(self):
        tool = EchoTool()
        schema = tool.anthropic_schema()
        assert schema["name"] == "echo"
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"

    def test_tool_execution_error(self):
        err = ToolExecutionError("something broke")
        assert str(err) == "something broke"
        assert isinstance(err, Exception)


class TestSearchSourcesTool:
    @pytest.mark.asyncio
    async def test_returns_mixed_paper_and_note_hits(self, app_paths):
        retrieval = RetrievalStore(app_paths, EmbeddingConfig(provider="fastembed", model="BAAI/bge-small-en-v1.5"))
        retrieval.upsert(
            RetrievalStore.PAPER_COLLECTION,
            [
                IndexedDocument(
                    id="paper-1",
                    text="RNA targeting compounds can be optimized with graph neural networks.",
                    metadata={
                        "paper_id": "paper-1",
                        "title": "RNA Paper",
                        "file_path": "/tmp/rna-paper.pdf",
                        "page_start": 4,
                    },
                )
            ],
        )
        retrieval.upsert(
            RetrievalStore.NOTE_COLLECTION,
            [
                IndexedDocument(
                    id="note-1",
                    text="Obsidian note about RNA targeting and graph neural network design ideas.",
                    metadata={
                        "note_id": "note-1",
                        "title": "RNA Ideas",
                        "vault_name": "Research",
                        "relative_path": "Ideas/RNA Ideas.md",
                        "absolute_path": "/tmp/RNA Ideas.md",
                    },
                )
            ],
        )

        tool = SearchSourcesTool(retrieval)
        results = await tool.invoke({"query": "RNA graph neural networks", "limit": 6})

        assert any(result["source_type"] == "paper" for result in results)
        assert any(result["source_type"] == "note" for result in results)
        assert all(result.get("citation_path") for result in results)
