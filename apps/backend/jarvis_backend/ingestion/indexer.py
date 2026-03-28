from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional

import fitz

from jarvis_backend.ingestion.chunker import chunk_pages, chunk_text
from jarvis_backend.models import AppConfig, IndexedDocument, VaultConfig
from jarvis_backend.retrieval import RetrievalStore

logger = logging.getLogger(__name__)

ZOTERO_NOTES_COLLECTION = "zotero_notes"


class ContentIndexer:
    def __init__(self, retrieval: RetrievalStore) -> None:
        self.retrieval = retrieval

    def index_all(self, config: AppConfig) -> Dict[str, Dict[str, int]]:
        return {
            "papers": self.index_papers(config),
            "notes": self.index_notes(config),
            "zotero_notes": self.index_zotero_notes(config),
        }

    # ─── PDF papers ─────────────────────────────────────────────────

    def index_papers(self, config: AppConfig) -> Dict[str, int]:
        if not config.zotero.storage_path:
            return {"files_scanned": 0, "chunks_indexed": 0}

        root = Path(config.zotero.storage_path).expanduser()
        if not root.exists():
            return {"files_scanned": 0, "chunks_indexed": 0}

        # Build PDF→Zotero item map for metadata enrichment
        item_map = self._build_zotero_map(config)

        total_chunks = 0
        pdf_files = sorted(root.rglob("*.pdf"))
        for pdf_path in pdf_files:
            zotero_meta = item_map.get(str(pdf_path.resolve()))
            total_chunks += self._index_pdf(pdf_path, zotero_meta)
        return {"files_scanned": len(pdf_files), "chunks_indexed": total_chunks}

    # ─── Obsidian notes ─────────────────────────────────────────────

    def index_notes(self, config: AppConfig) -> Dict[str, int]:
        files_scanned = 0
        chunks_indexed = 0
        for vault in config.obsidian_vaults:
            vault_root = Path(vault.path).expanduser()
            if not vault_root.exists():
                continue
            for note_path in sorted(vault_root.rglob("*.md")):
                files_scanned += 1
                chunks_indexed += self.index_note_file(vault, note_path)
        return {"files_scanned": files_scanned, "chunks_indexed": chunks_indexed}

    def index_note_file(self, vault: VaultConfig, note_path: Path) -> int:
        note_id = self._stable_id(note_path)
        content = note_path.read_text(encoding="utf-8")
        chunks = chunk_text(content)
        self.retrieval.delete_where(RetrievalStore.NOTE_COLLECTION, {"note_id": note_id})

        vault_root = Path(vault.path).expanduser()
        rel_path = str(note_path.relative_to(vault_root))
        # Build folder path for hierarchy display (e.g. "Research/ML/Transformers")
        folder_path = str(note_path.parent.relative_to(vault_root)) if note_path.parent != vault_root else ""
        if folder_path == ".":
            folder_path = ""

        documents = []
        for index, chunk in enumerate(chunks):
            documents.append(
                IndexedDocument(
                    id=f"{note_id}:{index}",
                    text=chunk,
                    metadata={
                        "note_id": note_id,
                        "title": note_path.stem,
                        "vault_id": vault.id,
                        "vault_name": vault.name,
                        "relative_path": rel_path,
                        "folder_path": folder_path,
                        "absolute_path": str(note_path),
                        "chunk_index": index,
                        "total_chunks": len(chunks),
                    },
                )
            )
        return self.retrieval.upsert(RetrievalStore.NOTE_COLLECTION, documents)

    # ─── Zotero notes & annotations ────────────────────────────────

    def index_zotero_notes(self, config: AppConfig) -> Dict[str, int]:
        """Index all Zotero user notes and PDF annotations into a dedicated collection."""
        db_path = config.zotero.database_path
        if not db_path:
            return {"notes_indexed": 0, "annotations_indexed": 0}

        try:
            from jarvis_backend.zotero_db import ZoteroDB
        except ImportError:
            logger.warning("zotero_db module not available, skipping Zotero note indexing")
            return {"notes_indexed": 0, "annotations_indexed": 0}

        notes_count = 0
        annotations_count = 0

        try:
            with ZoteroDB(db_path) as db:
                # Index all user notes attached to items
                all_notes = db.get_all_notes()
                for note in all_notes:
                    text = note["text"].strip()
                    if len(text) < 20:
                        continue
                    parent_item = db.get_item_by_id(note["parentItemID"])
                    parent_title = ""
                    collections_str = ""
                    if parent_item:
                        parent_title = parent_item.get("metadata", {}).get("title", "")
                        collections_str = "; ".join(parent_item.get("collections", []))

                    note_id = f"zn-{note['noteItemID']}"
                    chunks = chunk_text(text)
                    self.retrieval.delete_where(ZOTERO_NOTES_COLLECTION, {"note_id": note_id})
                    documents = []
                    for idx, chunk in enumerate(chunks):
                        documents.append(
                            IndexedDocument(
                                id=f"{note_id}:{idx}",
                                text=chunk,
                                metadata={
                                    "note_id": note_id,
                                    "note_type": "note",
                                    "zotero_item_id": note["parentItemID"],
                                    "parent_title": parent_title,
                                    "collections": collections_str,
                                    "note_key": note["noteKey"],
                                    "chunk_index": idx,
                                    "total_chunks": len(chunks),
                                },
                            )
                        )
                    notes_count += self.retrieval.upsert(ZOTERO_NOTES_COLLECTION, documents)

                # Index PDF annotations for all items
                all_items = db.get_all_items()
                for item in all_items:
                    annotations = db.get_item_annotations(item["itemID"])
                    if not annotations:
                        continue
                    title = item.get("metadata", {}).get("title", "Untitled")
                    collections_str = "; ".join(item.get("collections", []))
                    ann_texts = []
                    for ann in annotations:
                        parts = []
                        if ann.get("text"):
                            parts.append(f"[Highlight p.{ann.get('pageLabel', '?')}] {ann['text']}")
                        if ann.get("comment"):
                            parts.append(f"[Comment p.{ann.get('pageLabel', '?')}] {ann['comment']}")
                        if parts:
                            ann_texts.append(" ".join(parts))

                    if not ann_texts:
                        continue

                    combined = "\n".join(ann_texts)
                    ann_id = f"za-{item['itemID']}"
                    chunks = chunk_text(combined)
                    self.retrieval.delete_where(ZOTERO_NOTES_COLLECTION, {"note_id": ann_id})
                    documents = []
                    for idx, chunk in enumerate(chunks):
                        documents.append(
                            IndexedDocument(
                                id=f"{ann_id}:{idx}",
                                text=chunk,
                                metadata={
                                    "note_id": ann_id,
                                    "note_type": "annotation",
                                    "zotero_item_id": item["itemID"],
                                    "parent_title": title,
                                    "collections": collections_str,
                                    "chunk_index": idx,
                                    "total_chunks": len(chunks),
                                },
                            )
                        )
                    annotations_count += self.retrieval.upsert(ZOTERO_NOTES_COLLECTION, documents)

        except Exception:
            logger.exception("Error indexing Zotero notes/annotations")

        return {"notes_indexed": notes_count, "annotations_indexed": annotations_count}

    # ─── private helpers ────────────────────────────────────────────

    def _index_pdf(self, pdf_path: Path, zotero_meta: Optional[Dict] = None) -> int:
        paper_id = self._stable_id(pdf_path)
        pages = self._extract_pdf_pages(pdf_path)
        page_chunks = chunk_pages(pages)
        self.retrieval.delete_where(RetrievalStore.PAPER_COLLECTION, {"paper_id": paper_id})

        # Determine title from Zotero metadata first, then PDF metadata, then filename
        title = ""
        authors = ""
        year = ""
        collections_str = ""
        tags_str = ""
        if zotero_meta:
            title = zotero_meta.get("title") or ""
            authors = zotero_meta.get("authors", "")
            year = zotero_meta.get("year", "")
            collections_str = zotero_meta.get("collections", "")
            tags_str = zotero_meta.get("tags", "")

        if not title:
            title = self._extract_pdf_title(pdf_path)

        total_pages = len(pages)

        documents: List[IndexedDocument] = []
        for pc in page_chunks:
            documents.append(
                IndexedDocument(
                    id=f"{paper_id}:{pc.chunk_index}",
                    text=pc.text,
                    metadata={
                        "paper_id": paper_id,
                        "title": title,
                        "authors": authors,
                        "year": year,
                        "collections": collections_str,
                        "tags": tags_str,
                        "file_path": str(pdf_path),
                        "chunk_index": pc.chunk_index,
                        "total_chunks": len(page_chunks),
                        "page_start": pc.page_start,
                        "page_end": pc.page_end,
                        "total_pages": total_pages,
                    },
                )
            )
        return self.retrieval.upsert(RetrievalStore.PAPER_COLLECTION, documents)

    def _extract_pdf_pages(self, pdf_path: Path) -> List[str]:
        """Extract text from each page of a PDF, returned as a list of strings.

        Uses PyMuPDF flags to preserve mathematical notation, superscripts,
        subscripts, and equation layout as much as possible.
        """
        try:
            # Flags to preserve whitespace layout and ligatures (helps with math)
            flags = (
                fitz.TEXT_PRESERVE_WHITESPACE
                | fitz.TEXT_PRESERVE_LIGATURES
                | fitz.TEXT_MEDIABOX_CLIP
            )
            with fitz.open(pdf_path) as document:
                return [page.get_text("text", flags=flags) for page in document]
        except Exception:
            logger.warning("Failed to extract text from %s", pdf_path)
            return []

    def _extract_pdf_title(self, pdf_path: Path) -> str:
        """Fallback title extraction from PDF metadata or first line."""
        try:
            with fitz.open(pdf_path) as document:
                metadata_title = (document.metadata or {}).get("title") or ""
                if metadata_title.strip() and not metadata_title.strip().isdigit():
                    return metadata_title.strip()
                # Use first non-empty line from page 1
                if document.page_count > 0:
                    text = document[0].get_text("text")
                    for line in text.splitlines():
                        line = line.strip()
                        if line and len(line) > 5 and not line.isdigit():
                            return line[:180]
        except Exception:
            pass
        return pdf_path.stem.replace("_", " ").replace("-", " ")

    def _build_zotero_map(self, config: AppConfig) -> Dict[str, Dict]:
        """Build a map from PDF path -> {title, authors, year, collections, tags} using Zotero DB."""
        db_path = config.zotero.database_path
        storage_path = config.zotero.storage_path
        if not db_path or not storage_path:
            return {}

        try:
            from jarvis_backend.zotero_db import ZoteroDB

            with ZoteroDB(db_path) as db:
                pdf_to_item = db.build_pdf_to_item_map(storage_path)
                result: Dict[str, Dict] = {}
                for pdf_path_str, item_id in pdf_to_item.items():
                    item = db.get_item_by_id(item_id)
                    if not item:
                        continue
                    meta = item.get("metadata", {})
                    creators = item.get("creators", [])
                    author_names = [
                        f"{c.get('lastName', '')}, {c.get('firstName', '')}"
                        for c in creators
                        if c.get("creatorType") == "author"
                    ]
                    result[pdf_path_str] = {
                        "title": meta.get("title", ""),
                        "authors": "; ".join(author_names[:5]),
                        "year": (meta.get("date") or "")[:4],
                        "collections": "; ".join(item.get("collections", [])),
                        "tags": "; ".join(item.get("tags", [])),
                    }
                return result
        except Exception:
            logger.exception("Could not build Zotero metadata map")
            return {}

    def _stable_id(self, path: Path) -> str:
        return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
