from __future__ import annotations

from typing import Any, Dict, List

from roxanne_backend.retrieval import RetrievalStore
from roxanne_backend.tools.base import BaseTool, ToolExecutionError


class SearchSourcesTool(BaseTool):
    name = "search_sources"
    description = (
        "Semantic/vector search across both Zotero paper chunks and Obsidian note chunks "
        "in one shared embedding space. Use this when the answer could be in either papers "
        "or notes, or when you want the best mixed evidence set."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Topic, question, or concept to search across papers and notes.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of mixed results to return.",
                "minimum": 1,
                "maximum": 12,
            },
        },
        "required": ["query"],
    }

    def __init__(self, retrieval: RetrievalStore) -> None:
        self.retrieval = retrieval

    async def invoke(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        query = payload["query"].strip()
        if not query:
            raise ToolExecutionError("query is required.")

        raw_limit = payload.get("limit", 8)
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 8
        limit = max(1, min(limit, 12))

        rows = self.retrieval.query_collections(
            [RetrievalStore.PAPER_COLLECTION, RetrievalStore.NOTE_COLLECTION],
            query,
            n_results=limit,
            per_collection=max(limit, 6),
        )

        results: List[Dict[str, Any]] = []
        for row in rows:
            metadata = row["metadata"]
            collection = row["collection"]
            if collection == RetrievalStore.PAPER_COLLECTION:
                results.append(
                    {
                        "source_type": "paper",
                        "collection": collection,
                        "paper_id": metadata.get("paper_id"),
                        "title": metadata.get("title", "Untitled paper"),
                        "authors": metadata.get("authors", ""),
                        "year": metadata.get("year", ""),
                        "file_path": metadata.get("file_path"),
                        "citation_path": metadata.get("file_path"),
                        "citation_page": metadata.get("page_start"),
                        "page_start": metadata.get("page_start"),
                        "page_end": metadata.get("page_end"),
                        "chunk_index": metadata.get("chunk_index"),
                        "chunk": row["document"],
                        "excerpt": row["document"][:800],
                        "score": row["distance"],
                    }
                )
            elif collection == RetrievalStore.NOTE_COLLECTION:
                results.append(
                    {
                        "source_type": "note",
                        "collection": collection,
                        "note_id": metadata.get("note_id"),
                        "title": metadata.get("title", "Untitled note"),
                        "vault_name": metadata.get("vault_name", ""),
                        "relative_path": metadata.get("relative_path", ""),
                        "absolute_path": metadata.get("absolute_path"),
                        "citation_path": metadata.get("absolute_path"),
                        "citation_page": None,
                        "chunk_index": metadata.get("chunk_index"),
                        "total_chunks": metadata.get("total_chunks"),
                        "chunk": row["document"],
                        "excerpt": row["document"][:800],
                        "score": row["distance"],
                    }
                )
        return results
