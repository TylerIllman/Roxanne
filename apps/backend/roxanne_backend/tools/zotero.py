from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from roxanne_backend.config import ConfigStore
from roxanne_backend.retrieval import RetrievalStore
from roxanne_backend.tools.base import BaseTool, ToolExecutionError
from roxanne_backend.zotero_db import ZoteroDB, format_item_summary

logger = logging.getLogger(__name__)


# ─── helpers ────────────────────────────────────────────────────────

def _open_zotero(config_store: ConfigStore) -> ZoteroDB:
    """Open a read-only handle to the configured Zotero database."""
    config = config_store.load()
    db_path = config.zotero.database_path
    if not db_path:
        raise ToolExecutionError(
            "Zotero database path is not configured. "
            "Please set it in Settings → Zotero → Database path."
        )
    db = ZoteroDB(db_path)
    db.open()
    return db


def _paper_id_to_item(
    db: ZoteroDB, paper_id: str, retrieval: RetrievalStore
) -> Optional[Dict[str, Any]]:
    """Resolve a vector-store paper_id back to a Zotero itemID via the PDF path."""
    rows = retrieval.get_by_metadata(
        RetrievalStore.PAPER_COLLECTION, {"paper_id": paper_id}, limit=1
    )
    if not rows:
        return None
    file_path = rows[0]["metadata"].get("file_path")
    if not file_path:
        return None
    # Walk up from the PDF to find the Zotero attachment key (folder name)
    pdf = Path(file_path)
    att_key = pdf.parent.name  # e.g. "ABCD1234"
    item = db.get_item_by_key(att_key)
    if item:
        return item
    # Fallback: build the full map and look up by resolved path
    config = db._conn  # we already have the db open
    # Try matching via the pdf-to-item map
    storage_dir = str(pdf.parent.parent)
    mapping = db.build_pdf_to_item_map(storage_dir)
    parent_id = mapping.get(str(pdf.resolve()))
    if parent_id:
        return db.get_item_by_id(parent_id)
    return None


# ─── existing tools (enhanced) ──────────────────────────────────────


class SearchZoteroTool(BaseTool):
    name = "search_zotero"
    description = "Search indexed Zotero papers by semantic similarity. Returns paper_id, title, authors, and score."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Research question or paper topic."}
        },
        "required": ["query"],
    }

    def __init__(self, retrieval: RetrievalStore) -> None:
        self.retrieval = retrieval

    async def invoke(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        query = payload["query"].strip()
        rows = self.retrieval.query(RetrievalStore.PAPER_COLLECTION, query, n_results=10)

        deduped: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            metadata = row["metadata"]
            paper_id = metadata.get("paper_id")
            if not paper_id:
                continue
            score = row["distance"]
            current = deduped.get(paper_id)
            if current is None or score < current["score"]:
                deduped[paper_id] = {
                    "paper_id": paper_id,
                    "title": metadata.get("title", "Untitled paper"),
                    "authors": metadata.get("authors", ""),
                    "year": metadata.get("year", ""),
                    "collections": metadata.get("collections", ""),
                    "tags": metadata.get("tags", ""),
                    "file_path": metadata.get("file_path"),
                    "score": score,
                }
        return list(deduped.values())[:6]


class RetrievePaperChunksTool(BaseTool):
    name = "retrieve_paper_chunks"
    description = "Retrieve relevant text chunks from a specific paper by paper_id. Use this to read specific sections, find details, equations, or formulas within a paper."
    input_schema = {
        "type": "object",
        "properties": {
            "paper_id": {"type": "string", "description": "The paper_id from search_zotero results."},
            "query": {"type": "string", "description": "What to look for in this paper."},
        },
        "required": ["paper_id", "query"],
    }

    def __init__(self, retrieval: RetrievalStore) -> None:
        self.retrieval = retrieval

    async def invoke(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        query = payload["query"].strip()
        paper_id = payload["paper_id"].strip()
        if not paper_id:
            raise ToolExecutionError("paper_id is required.")
        rows = self.retrieval.query(
            RetrievalStore.PAPER_COLLECTION,
            query,
            n_results=5,
            where={"paper_id": paper_id},
        )
        return [
            {
                "paper_id": row["metadata"].get("paper_id"),
                "title": row["metadata"].get("title"),
                "authors": row["metadata"].get("authors", ""),
                "year": row["metadata"].get("year", ""),
                "file_path": row["metadata"].get("file_path"),
                "citation_path": row["metadata"].get("file_path"),
                "citation_page": row["metadata"].get("page_start"),
                "chunk": row["document"],
                "chunk_index": row["metadata"].get("chunk_index"),
                "page_start": row["metadata"].get("page_start"),
                "page_end": row["metadata"].get("page_end"),
                "total_pages": row["metadata"].get("total_pages"),
                "score": row["distance"],
            }
            for row in rows
        ]


class OpenPdfTool(BaseTool):
    name = "open_pdf"
    description = "Resolve a paper_id to a local PDF path so the UI can open it."
    input_schema = {
        "type": "object",
        "properties": {"paper_id": {"type": "string"}},
        "required": ["paper_id"],
    }

    def __init__(self, retrieval: RetrievalStore) -> None:
        self.retrieval = retrieval

    async def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        paper_id = payload["paper_id"].strip()
        rows = self.retrieval.get_by_metadata(
            RetrievalStore.PAPER_COLLECTION, {"paper_id": paper_id}, limit=1
        )
        if not rows:
            raise ToolExecutionError(f"No indexed paper found for paper_id={paper_id}.")
        metadata = rows[0]["metadata"]
        return {
            "paper_id": paper_id,
            "title": metadata.get("title"),
            "file_path": metadata.get("file_path"),
        }


# ─── new tools ──────────────────────────────────────────────────────


class GetPaperMetadataTool(BaseTool):
    name = "get_paper_metadata"
    description = (
        "Get full bibliographic metadata for a paper from the Zotero database: "
        "title, authors, year, journal, DOI, abstract, tags, and collections. "
        "Use paper_id from search_zotero or a Zotero item key."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "paper_id": {
                "type": "string",
                "description": "The paper_id from search results (vector store ID).",
            },
            "zotero_key": {
                "type": "string",
                "description": "Alternatively, a Zotero item key (8-char alphanumeric).",
            },
        },
    }

    def __init__(self, config_store: ConfigStore, retrieval: RetrievalStore) -> None:
        self.config_store = config_store
        self.retrieval = retrieval

    async def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        paper_id = (payload.get("paper_id") or "").strip()
        zotero_key = (payload.get("zotero_key") or "").strip()
        if not paper_id and not zotero_key:
            raise ToolExecutionError("Provide either paper_id or zotero_key.")

        db = _open_zotero(self.config_store)
        try:
            item = None
            if zotero_key:
                item = db.get_item_by_key(zotero_key)
            if not item and paper_id:
                item = _paper_id_to_item(db, paper_id, self.retrieval)
            if not item:
                raise ToolExecutionError("Could not find this paper in the Zotero database.")

            meta = item.get("metadata", {})
            creators = item.get("creators", [])
            authors = [
                f"{c.get('lastName', '')}, {c.get('firstName', '')}"
                for c in creators
                if c.get("creatorType") == "author"
            ]
            config = self.config_store.load()
            pdf_path = db.resolve_pdf_path(
                item["itemID"], config.zotero.storage_path or ""
            )
            return {
                "zotero_item_id": item["itemID"],
                "zotero_key": item["key"],
                "item_type": item["typeName"],
                "title": meta.get("title", "Untitled"),
                "authors": authors,
                "year": (meta.get("date") or "")[:4],
                "date": meta.get("date", ""),
                "journal": meta.get("publicationTitle", "") or meta.get("proceedingsTitle", ""),
                "doi": meta.get("DOI", ""),
                "abstract": meta.get("abstractNote", ""),
                "url": meta.get("url", ""),
                "tags": item.get("tags", []),
                "collections": item.get("collections", []),
                "pdf_path": pdf_path,
                "date_added": item.get("dateAdded", ""),
            }
        finally:
            db.close()


class ListZoteroCollectionsTool(BaseTool):
    name = "list_zotero_collections"
    description = "List all Zotero collections (folders) with their item counts."
    input_schema = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, config_store: ConfigStore) -> None:
        self.config_store = config_store

    async def invoke(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        db = _open_zotero(self.config_store)
        try:
            collections = db.get_collections()
            return [
                {
                    "collection_id": c["collectionID"],
                    "name": c["collectionName"],
                    "parent_id": c["parentCollectionID"],
                    "item_count": c["itemCount"],
                    "key": c["key"],
                }
                for c in collections
            ]
        finally:
            db.close()


class SearchZoteroMetadataTool(BaseTool):
    name = "search_zotero_metadata"
    description = (
        "Search Zotero papers by metadata: author name, title keywords, tags, or year. "
        "Unlike search_zotero (which is semantic/vector search of PDF content), this does "
        "structured text matching against the Zotero database fields."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term to match against titles, authors, tags.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, config_store: ConfigStore) -> None:
        self.config_store = config_store

    async def invoke(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        query = payload["query"].strip()
        if not query:
            raise ToolExecutionError("query is required.")

        db = _open_zotero(self.config_store)
        try:
            items = db.search_items(query)
            results = []
            for item in items[:15]:
                meta = item.get("metadata", {})
                creators = item.get("creators", [])
                authors = [
                    f"{c.get('lastName', '')}, {c.get('firstName', '')}"
                    for c in creators
                    if c.get("creatorType") == "author"
                ]
                results.append({
                    "zotero_item_id": item["itemID"],
                    "zotero_key": item["key"],
                    "item_type": item["typeName"],
                    "title": meta.get("title", "Untitled"),
                    "authors": authors[:5],
                    "year": (meta.get("date") or "")[:4],
                    "journal": meta.get("publicationTitle", "") or meta.get("proceedingsTitle", ""),
                    "tags": item.get("tags", []),
                    "collections": item.get("collections", []),
                })
            return results
        finally:
            db.close()


class GetPaperNotesTool(BaseTool):
    name = "get_paper_notes"
    description = (
        "Get all notes attached to a Zotero paper. These are the rich-text notes "
        "the user has written in Zotero about a specific paper. "
        "Use paper_id from search_zotero or a zotero_item_id."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "paper_id": {
                "type": "string",
                "description": "The paper_id from vector search results.",
            },
            "zotero_item_id": {
                "type": "integer",
                "description": "Alternatively, the Zotero itemID (integer).",
            },
        },
    }

    def __init__(self, config_store: ConfigStore, retrieval: RetrievalStore) -> None:
        self.config_store = config_store
        self.retrieval = retrieval

    async def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        paper_id = (payload.get("paper_id") or "").strip() if isinstance(payload.get("paper_id"), str) else ""
        zotero_item_id = payload.get("zotero_item_id")

        db = _open_zotero(self.config_store)
        try:
            item_id = zotero_item_id
            if not item_id and paper_id:
                item = _paper_id_to_item(db, paper_id, self.retrieval)
                if item:
                    item_id = item["itemID"]
            if not item_id:
                raise ToolExecutionError("Could not resolve paper. Provide paper_id or zotero_item_id.")

            notes = db.get_item_notes(item_id)
            return {
                "zotero_item_id": item_id,
                "note_count": len(notes),
                "notes": [
                    {
                        "note_key": n["noteKey"],
                        "text": n["text"][:3000],
                        "date_added": n["dateAdded"],
                        "date_modified": n["dateModified"],
                    }
                    for n in notes
                ],
            }
        finally:
            db.close()


class GetPaperAnnotationsTool(BaseTool):
    name = "get_paper_annotations"
    description = (
        "Get PDF annotations (highlights, comments, underlines) made in the Zotero PDF reader "
        "for a specific paper. Returns highlighted text, comments, page numbers, and colors."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "paper_id": {
                "type": "string",
                "description": "The paper_id from vector search results.",
            },
            "zotero_item_id": {
                "type": "integer",
                "description": "Alternatively, the Zotero itemID (integer).",
            },
        },
    }

    def __init__(self, config_store: ConfigStore, retrieval: RetrievalStore) -> None:
        self.config_store = config_store
        self.retrieval = retrieval

    async def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        paper_id = (payload.get("paper_id") or "").strip() if isinstance(payload.get("paper_id"), str) else ""
        zotero_item_id = payload.get("zotero_item_id")

        db = _open_zotero(self.config_store)
        try:
            item_id = zotero_item_id
            if not item_id and paper_id:
                item = _paper_id_to_item(db, paper_id, self.retrieval)
                if item:
                    item_id = item["itemID"]
            if not item_id:
                raise ToolExecutionError("Could not resolve paper. Provide paper_id or zotero_item_id.")

            annotations = db.get_item_annotations(item_id)
            return {
                "zotero_item_id": item_id,
                "annotation_count": len(annotations),
                "annotations": [
                    {
                        "type": a.get("type", ""),
                        "highlighted_text": a.get("text", ""),
                        "comment": a.get("comment", ""),
                        "page": a.get("pageLabel", ""),
                        "color": a.get("color", ""),
                    }
                    for a in annotations
                ],
            }
        finally:
            db.close()


class SearchZoteroNotesTool(BaseTool):
    name = "search_zotero_notes"
    description = (
        "Semantic search across all indexed Zotero notes and annotations. "
        "Use this to find notes the user wrote about any paper by topic."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Topic or concept to search for in notes."},
        },
        "required": ["query"],
    }

    COLLECTION = "zotero_notes"

    def __init__(self, retrieval: RetrievalStore) -> None:
        self.retrieval = retrieval

    async def invoke(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        query = payload["query"].strip()
        rows = self.retrieval.query(self.COLLECTION, query, n_results=8)
        return [
            {
                "parent_title": row["metadata"].get("parent_title", ""),
                "note_type": row["metadata"].get("note_type", "note"),
                "excerpt": row["document"][:800],
                "zotero_item_id": row["metadata"].get("zotero_item_id"),
                "score": row["distance"],
            }
            for row in rows
        ]


class GetCollectionPapersTool(BaseTool):
    name = "get_collection_papers"
    description = (
        "List all papers in a specific Zotero collection/folder. "
        "Use list_zotero_collections first to find collection IDs."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "collection_id": {
                "type": "integer",
                "description": "The collection_id from list_zotero_collections.",
            },
        },
        "required": ["collection_id"],
    }

    def __init__(self, config_store: ConfigStore) -> None:
        self.config_store = config_store

    async def invoke(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        collection_id = payload["collection_id"]
        db = _open_zotero(self.config_store)
        try:
            items = db.get_collection_items(collection_id)
            results = []
            for item in items:
                meta = item.get("metadata", {})
                creators = item.get("creators", [])
                authors = [
                    f"{c.get('lastName', '')}, {c.get('firstName', '')}"
                    for c in creators
                    if c.get("creatorType") == "author"
                ]
                results.append({
                    "zotero_item_id": item["itemID"],
                    "zotero_key": item["key"],
                    "title": meta.get("title", "Untitled"),
                    "authors": authors[:3],
                    "year": (meta.get("date") or "")[:4],
                    "item_type": item["typeName"],
                })
            return results
        finally:
            db.close()
