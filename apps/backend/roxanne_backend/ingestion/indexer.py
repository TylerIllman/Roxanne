from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional

import fitz

from roxanne_backend.ingestion.chunker import chunk_pages, chunk_text
from roxanne_backend.models import AppConfig, IndexedDocument, VaultConfig
from roxanne_backend.retrieval import RetrievalStore

logger = logging.getLogger(__name__)

ZOTERO_NOTES_COLLECTION = "zotero_notes"

# Type for progress callback / event dict
IndexEvent = Dict[str, Any]


def _file_fingerprint(path: Path) -> str:
    """Return a fingerprint string based on file mtime + size."""
    try:
        stat = path.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return ""


def _meta_fingerprint(meta: Optional[Dict]) -> str:
    """Hash Zotero metadata dict so we detect title/tag/collection changes."""
    if not meta:
        return ""
    return hashlib.md5(json.dumps(meta, sort_keys=True).encode()).hexdigest()[:12]


class _IndexManifest:
    """Tracks what has been indexed and when, to skip unchanged files."""

    def __init__(self, manifest_path: Path) -> None:
        self._path = manifest_path
        self._data: Dict[str, str] = {}  # stable_id -> fingerprint
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except Exception:
                self._data = {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data))

    def needs_index(self, stable_id: str, fingerprint: str) -> bool:
        return self._data.get(stable_id) != fingerprint

    def mark_indexed(self, stable_id: str, fingerprint: str) -> None:
        self._data[stable_id] = fingerprint


class ContentIndexer:
    def __init__(self, retrieval: RetrievalStore) -> None:
        self.retrieval = retrieval

    def index_all(self, config: AppConfig) -> Dict[str, Dict[str, int]]:
        return {
            "papers": self.index_papers(config),
            "notes": self.index_notes(config),
            "zotero_notes": self.index_zotero_notes(config),
        }

    def _get_manifest(self) -> _IndexManifest:
        manifest_path = Path(self.retrieval._paths.root) / "index_manifest.json"
        return _IndexManifest(manifest_path)

    def index_all_streaming(self, config: AppConfig, force: bool = False) -> Generator[IndexEvent, None, None]:
        """Index everything, yielding progress events per file.

        Skips files that haven't changed since last index unless force=True.
        Detects changes via file mtime/size AND Zotero metadata changes
        (new notes, tags, collections attached to a paper).
        """
        manifest = self._get_manifest()

        # Count totals first for progress
        pdf_files: List[Path] = []
        note_files: List[tuple] = []  # (vault, path)
        if config.zotero.storage_path:
            root = Path(config.zotero.storage_path).expanduser()
            if root.exists():
                pdf_files = sorted(root.rglob("*.pdf"))
        for vault in config.obsidian_vaults:
            vault_root = Path(vault.path).expanduser()
            if vault_root.exists():
                for np in sorted(vault_root.rglob("*.md")):
                    note_files.append((vault, np))

        total_files = len(pdf_files) + len(note_files) + 1  # +1 for zotero notes step
        done = 0
        skipped = 0

        yield {"phase": "starting", "total_files": total_files, "done": 0, "progress": 0,
               "detail": f"Found {len(pdf_files)} papers, {len(note_files)} notes"}

        # ── Papers ──
        if pdf_files:
            item_map = self._build_zotero_map(config)
            total_chunks = 0
            for i, pdf_path in enumerate(pdf_files):
                zotero_meta = item_map.get(str(pdf_path.resolve()))
                title = (zotero_meta or {}).get("title", pdf_path.stem)
                paper_id = self._stable_id(pdf_path)

                # Build fingerprint: file content + Zotero metadata
                fp = _file_fingerprint(pdf_path) + "|" + _meta_fingerprint(zotero_meta)

                if not force and not manifest.needs_index(paper_id, fp):
                    skipped += 1
                    done += 1
                    yield {
                        "phase": "papers", "done": done, "total_files": total_files,
                        "progress": done / total_files,
                        "current_file": title[:60],
                        "detail": f"Paper {i+1}/{len(pdf_files)}: {title[:50]} (unchanged)",
                        "chunks": 0, "skipped": True,
                    }
                    continue

                try:
                    chunks = self._index_pdf(pdf_path, zotero_meta)
                    total_chunks += chunks
                    manifest.mark_indexed(paper_id, fp)
                except Exception as exc:
                    logger.warning("Failed to index %s: %s", pdf_path.name, exc)
                    chunks = 0
                done += 1
                yield {
                    "phase": "papers", "done": done, "total_files": total_files,
                    "progress": done / total_files,
                    "current_file": title[:60],
                    "detail": f"Paper {i+1}/{len(pdf_files)}: {title[:50]}",
                    "chunks": chunks,
                }

        # ── Notes ──
        if note_files:
            total_note_chunks = 0
            for i, (vault, note_path) in enumerate(note_files):
                note_id = self._stable_id(note_path)
                fp = _file_fingerprint(note_path)

                if not force and not manifest.needs_index(note_id, fp):
                    skipped += 1
                    done += 1
                    yield {
                        "phase": "notes", "done": done, "total_files": total_files,
                        "progress": done / total_files,
                        "current_file": note_path.stem[:60],
                        "detail": f"Note {i+1}/{len(note_files)}: {note_path.stem[:50]} (unchanged)",
                        "chunks": 0, "skipped": True,
                    }
                    continue

                try:
                    chunks = self.index_note_file(vault, note_path)
                    total_note_chunks += chunks
                    manifest.mark_indexed(note_id, fp)
                except Exception as exc:
                    logger.warning("Failed to index note %s: %s", note_path.name, exc)
                    chunks = 0
                done += 1
                yield {
                    "phase": "notes", "done": done, "total_files": total_files,
                    "progress": done / total_files,
                    "current_file": note_path.stem[:60],
                    "detail": f"Note {i+1}/{len(note_files)}: {note_path.stem[:50]}",
                    "chunks": chunks,
                }

        # ── Zotero notes ──
        yield {"phase": "zotero_notes", "done": done, "total_files": total_files,
               "progress": done / total_files, "detail": "Indexing Zotero notes & annotations..."}
        try:
            zn_report = self.index_zotero_notes(config)
        except Exception as exc:
            logger.warning("Zotero notes indexing failed: %s", exc)
            zn_report = {"notes_indexed": 0, "annotations_indexed": 0}
        done += 1

        # Save manifest so next run skips unchanged files
        manifest.save()

        indexed_count = total_files - 1 - skipped  # -1 for zotero notes step
        yield {"phase": "done", "done": done, "total_files": total_files, "progress": 1.0,
               "skipped": skipped, "indexed": indexed_count,
               "detail": f"Complete — {indexed_count} indexed, {skipped} unchanged, "
                         f"{zn_report.get('notes_indexed', 0)} Zotero notes"}

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
            from roxanne_backend.zotero_db import ZoteroDB
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
            from roxanne_backend.zotero_db import ZoteroDB

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
