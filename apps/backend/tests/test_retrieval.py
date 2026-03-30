"""Tests for RetrievalStore — vector DB operations."""
from __future__ import annotations

import pytest

from roxanne_backend.models import EmbeddingConfig, IndexedDocument
from roxanne_backend.retrieval import RetrievalStore
from roxanne_backend.storage import AppPaths


@pytest.fixture
def retrieval(app_paths: AppPaths) -> RetrievalStore:
    """RetrievalStore using fastembed (no external service needed)."""
    config = EmbeddingConfig(provider="fastembed", model="BAAI/bge-small-en-v1.5")
    return RetrievalStore(app_paths, config)


class TestRetrievalStore:
    def test_upsert_and_count(self, retrieval: RetrievalStore):
        docs = [
            IndexedDocument(id="d1", text="Machine learning uses neural networks.", metadata={"source": "test"}),
            IndexedDocument(id="d2", text="Transformers use attention mechanisms.", metadata={"source": "test"}),
        ]
        count = retrieval.upsert("test_collection", docs)
        assert count == 2

    def test_upsert_idempotent(self, retrieval: RetrievalStore):
        docs = [IndexedDocument(id="d1", text="Same document.", metadata={"source": "test"})]
        retrieval.upsert("test_idem", docs)
        retrieval.upsert("test_idem", docs)
        result = retrieval.list_collection("test_idem")
        assert result["total"] == 1

    def test_query_returns_results(self, retrieval: RetrievalStore):
        docs = [
            IndexedDocument(id="p1", text="Antibodies bind to specific antigens.", metadata={"type": "bio"}),
            IndexedDocument(id="p2", text="Python is a programming language.", metadata={"type": "cs"}),
        ]
        retrieval.upsert("test_query", docs)
        results = retrieval.query("test_query", "immune system", n_results=2)
        assert len(results) >= 1
        # The biology doc should rank higher
        assert results[0]["metadata"]["type"] == "bio"

    def test_query_with_where(self, retrieval: RetrievalStore):
        docs = [
            IndexedDocument(id="a1", text="Deep learning paper one.", metadata={"paper_id": "paper_A"}),
            IndexedDocument(id="b1", text="Deep learning paper two.", metadata={"paper_id": "paper_B"}),
        ]
        retrieval.upsert("test_where", docs)
        results = retrieval.query("test_where", "deep learning", n_results=5, where={"paper_id": "paper_A"})
        assert all(r["metadata"]["paper_id"] == "paper_A" for r in results)

    def test_delete_where(self, retrieval: RetrievalStore):
        docs = [
            IndexedDocument(id="x1", text="Delete me", metadata={"group": "remove"}),
            IndexedDocument(id="x2", text="Keep me", metadata={"group": "keep"}),
        ]
        retrieval.upsert("test_delete", docs)
        retrieval.delete_where("test_delete", {"group": "remove"})
        remaining = retrieval.list_collection("test_delete")
        assert remaining["total"] == 1

    def test_list_collection(self, retrieval: RetrievalStore):
        docs = [IndexedDocument(id=f"l{i}", text=f"Doc {i}", metadata={"idx": str(i)}) for i in range(5)]
        retrieval.upsert("test_list", docs)
        result = retrieval.list_collection("test_list", limit=3)
        assert result["total"] == 5
        assert len(result["items"]) == 3

    def test_list_collection_pagination(self, retrieval: RetrievalStore):
        docs = [IndexedDocument(id=f"pg{i}", text=f"Page {i}", metadata={"idx": str(i)}) for i in range(10)]
        retrieval.upsert("test_paginate", docs)
        page1 = retrieval.list_collection("test_paginate", limit=5, offset=0)
        page2 = retrieval.list_collection("test_paginate", limit=5, offset=5)
        all_ids = {item["id"] for item in page1["items"]} | {item["id"] for item in page2["items"]}
        assert len(all_ids) == 10

    def test_get_by_metadata(self, retrieval: RetrievalStore):
        docs = [
            IndexedDocument(id="m1", text="A", metadata={"paper_id": "target"}),
            IndexedDocument(id="m2", text="B", metadata={"paper_id": "other"}),
        ]
        retrieval.upsert("test_meta", docs)
        results = retrieval.get_by_metadata("test_meta", {"paper_id": "target"})
        assert len(results) == 1
        assert results[0]["id"] == "m1"

    def test_empty_collection_query(self, retrieval: RetrievalStore):
        results = retrieval.query("nonexistent", "anything", n_results=5)
        assert results == []


class TestRetrievalStoreEdgeCases:
    def test_unicode_text(self, retrieval: RetrievalStore):
        docs = [IndexedDocument(id="u1", text="α-synuclein aggregation in Parkinson's disease. ∑ᵢ xᵢ", metadata={"source": "test"})]
        count = retrieval.upsert("test_unicode", docs)
        assert count == 1
        results = retrieval.query("test_unicode", "protein aggregation")
        assert len(results) >= 1

    def test_long_text(self, retrieval: RetrievalStore):
        long_text = "word " * 2000
        docs = [IndexedDocument(id="long1", text=long_text, metadata={"source": "test"})]
        count = retrieval.upsert("test_long", docs)
        assert count == 1

    def test_empty_text(self, retrieval: RetrievalStore):
        docs = [IndexedDocument(id="empty1", text="", metadata={"source": "test"})]
        # Should handle gracefully (chromadb may reject empty)
        try:
            retrieval.upsert("test_empty_txt", docs)
        except Exception:
            pass  # Acceptable to fail on empty text
