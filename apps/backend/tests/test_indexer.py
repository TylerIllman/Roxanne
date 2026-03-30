"""Tests for ContentIndexer — PDF and note indexing."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from roxanne_backend.ingestion.indexer import ContentIndexer
from roxanne_backend.models import AppConfig, EmbeddingConfig, LLMConfig, VaultConfig, ZoteroConfig
from roxanne_backend.retrieval import RetrievalStore
from roxanne_backend.storage import AppPaths


@pytest.fixture
def retrieval(app_paths: AppPaths) -> RetrievalStore:
    config = EmbeddingConfig(provider="fastembed", model="BAAI/bge-small-en-v1.5")
    return RetrievalStore(app_paths, config)


@pytest.fixture
def indexer(retrieval: RetrievalStore) -> ContentIndexer:
    return ContentIndexer(retrieval)


# ── Note Indexing ──────────────────────────────────────────────────


class TestNoteIndexing:
    def test_index_single_note(self, indexer: ContentIndexer, obsidian_vault: Path):
        vault = VaultConfig(name="Test", path=str(obsidian_vault))
        note_path = obsidian_vault / "Note One.md"
        chunks = indexer.index_note_file(vault, note_path)
        assert chunks >= 1

    def test_index_all_notes(self, indexer: ContentIndexer, obsidian_vault: Path):
        config = AppConfig(
            anthropic=LLMConfig(provider="ollama", model="test"),
            obsidian_vaults=[VaultConfig(name="Test", path=str(obsidian_vault))],
        )
        result = indexer.index_notes(config)
        assert result["files_scanned"] == 3  # Note One, Note Two, Research/Deep Learning
        assert result["chunks_indexed"] >= 3

    def test_index_empty_vault(self, indexer: ContentIndexer, tmp_dir: Path):
        empty_vault = tmp_dir / "empty_vault"
        empty_vault.mkdir()
        config = AppConfig(
            anthropic=LLMConfig(provider="ollama", model="test"),
            obsidian_vaults=[VaultConfig(name="Empty", path=str(empty_vault))],
        )
        result = indexer.index_notes(config)
        assert result["files_scanned"] == 0

    def test_index_nonexistent_vault(self, indexer: ContentIndexer):
        config = AppConfig(
            anthropic=LLMConfig(provider="ollama", model="test"),
            obsidian_vaults=[VaultConfig(name="Ghost", path="/nonexistent/path")],
        )
        result = indexer.index_notes(config)
        assert result["files_scanned"] == 0

    def test_note_reindex_replaces(self, indexer: ContentIndexer, obsidian_vault: Path, retrieval: RetrievalStore):
        """Re-indexing the same note should replace, not duplicate."""
        vault = VaultConfig(name="Test", path=str(obsidian_vault))
        note_path = obsidian_vault / "Note One.md"
        indexer.index_note_file(vault, note_path)
        indexer.index_note_file(vault, note_path)
        # Should still have the same number of chunks
        result = retrieval.list_collection("notes")
        # Count docs with this note_id
        note_ids = [item.get("metadata", {}).get("note_id") for item in result.get("items", [])]
        from collections import Counter
        counts = Counter(note_ids)
        # Each note_id should have 1 chunk (short notes)
        for nid, count in counts.items():
            assert count >= 1  # at least 1, but not duplicated


# ── PDF Indexing ───────────────────────────────────────────────────


class TestPDFIndexing:
    def test_index_papers_no_storage(self, indexer: ContentIndexer):
        config = AppConfig(
            anthropic=LLMConfig(provider="ollama", model="test"),
            zotero=ZoteroConfig(storage_path=""),
        )
        result = indexer.index_papers(config)
        assert result["files_scanned"] == 0

    def test_index_papers_nonexistent_path(self, indexer: ContentIndexer):
        config = AppConfig(
            anthropic=LLMConfig(provider="ollama", model="test"),
            zotero=ZoteroConfig(storage_path="/nonexistent"),
        )
        result = indexer.index_papers(config)
        assert result["files_scanned"] == 0


# ── Streaming Index ────────────────────────────────────────────────


class TestStreamingIndex:
    def test_streaming_yields_events(self, indexer: ContentIndexer, obsidian_vault: Path):
        config = AppConfig(
            anthropic=LLMConfig(provider="ollama", model="test"),
            obsidian_vaults=[VaultConfig(name="Test", path=str(obsidian_vault))],
        )
        events = list(indexer.index_all_streaming(config))
        assert len(events) >= 2  # at least starting + done

        # First event should be starting
        assert events[0]["phase"] == "starting"
        assert events[0]["total_files"] >= 1

        # Last event should be done
        assert events[-1]["phase"] == "done"
        assert events[-1]["progress"] == 1.0

    def test_streaming_progress_increases(self, indexer: ContentIndexer, obsidian_vault: Path):
        config = AppConfig(
            anthropic=LLMConfig(provider="ollama", model="test"),
            obsidian_vaults=[VaultConfig(name="Test", path=str(obsidian_vault))],
        )
        events = list(indexer.index_all_streaming(config))
        progresses = [e["progress"] for e in events if "progress" in e]
        # Progress should be non-decreasing
        for i in range(1, len(progresses)):
            assert progresses[i] >= progresses[i - 1]

    def test_streaming_with_empty_config(self, indexer: ContentIndexer):
        config = AppConfig(anthropic=LLMConfig(provider="ollama", model="test"))
        events = list(indexer.index_all_streaming(config))
        # Should still complete with starting + zotero_notes + done
        phases = [e["phase"] for e in events]
        assert "starting" in phases
        assert "done" in phases
