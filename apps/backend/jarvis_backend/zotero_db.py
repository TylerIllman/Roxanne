"""Parse a Zotero SQLite database to extract metadata, notes, annotations, and collections."""

from __future__ import annotations

import html
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return text.strip()


class ZoteroDB:
    """Read-only access to a Zotero SQLite database.

    Zotero locks the database while running, so we copy it to a temp file first.
    """

    def __init__(self, database_path: str) -> None:
        self.database_path = Path(database_path).expanduser()
        self._conn: Optional[sqlite3.Connection] = None
        self._tmp_path: Optional[Path] = None

    def open(self) -> None:
        if not self.database_path.is_file():
            raise FileNotFoundError(f"Zotero database not found: {self.database_path}")
        # Copy to temp to avoid Zotero's lock
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        self._tmp_path = Path(tmp.name)
        shutil.copy2(self.database_path, self._tmp_path)
        self._conn = sqlite3.connect(str(self._tmp_path))
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
        if self._tmp_path and self._tmp_path.exists():
            self._tmp_path.unlink(missing_ok=True)

    def __enter__(self) -> "ZoteroDB":
        self.open()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ─── items & metadata ───────────────────────────────────────────

    def get_all_items(self) -> List[Dict[str, Any]]:
        """Return all library items (papers, books, etc.) with basic metadata."""
        rows = self._conn.execute(
            """
            SELECT i.itemID, i.key, it.typeName, i.dateAdded, i.dateModified
            FROM items i
            JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
            WHERE it.typeName NOT IN ('attachment', 'note', 'annotation')
              AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
            ORDER BY i.dateAdded DESC
            """
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["metadata"] = self._get_item_fields(item["itemID"])
            item["creators"] = self._get_item_creators(item["itemID"])
            item["tags"] = self._get_item_tags(item["itemID"])
            item["collections"] = self._get_item_collections(item["itemID"])
            items.append(item)
        return items

    def get_item_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a single item by its Zotero key."""
        row = self._conn.execute(
            """
            SELECT i.itemID, i.key, it.typeName, i.dateAdded, i.dateModified
            FROM items i
            JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
            WHERE i.key = ?
            """,
            (key,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["metadata"] = self._get_item_fields(item["itemID"])
        item["creators"] = self._get_item_creators(item["itemID"])
        item["tags"] = self._get_item_tags(item["itemID"])
        item["collections"] = self._get_item_collections(item["itemID"])
        return item

    def get_item_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Get a single item by its Zotero itemID."""
        row = self._conn.execute(
            """
            SELECT i.itemID, i.key, it.typeName, i.dateAdded, i.dateModified
            FROM items i
            JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
            WHERE i.itemID = ?
            """,
            (item_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["metadata"] = self._get_item_fields(item["itemID"])
        item["creators"] = self._get_item_creators(item["itemID"])
        item["tags"] = self._get_item_tags(item["itemID"])
        item["collections"] = self._get_item_collections(item["itemID"])
        return item

    def search_items(self, query: str) -> List[Dict[str, Any]]:
        """Search items by title, creator name, or tag (SQL LIKE)."""
        like = f"%{query}%"
        item_ids = set()
        # Search in item fields (title, abstract, etc.)
        rows = self._conn.execute(
            """
            SELECT DISTINCT id.itemID
            FROM itemData id
            JOIN itemDataValues idv ON idv.valueID = id.valueID
            WHERE idv.value LIKE ?
            """,
            (like,),
        ).fetchall()
        item_ids.update(r["itemID"] for r in rows)
        # Search in creators
        rows = self._conn.execute(
            """
            SELECT DISTINCT ic.itemID
            FROM itemCreators ic
            JOIN creators c ON c.creatorID = ic.creatorID
            WHERE c.firstName LIKE ? OR c.lastName LIKE ?
            """,
            (like, like),
        ).fetchall()
        item_ids.update(r["itemID"] for r in rows)
        # Search in tags
        rows = self._conn.execute(
            """
            SELECT DISTINCT it.itemID
            FROM itemTags it
            JOIN tags t ON t.tagID = it.tagID
            WHERE t.name LIKE ?
            """,
            (like,),
        ).fetchall()
        item_ids.update(r["itemID"] for r in rows)

        if not item_ids:
            return []
        # Filter to actual library items (not attachments/notes)
        placeholders = ",".join("?" for _ in item_ids)
        rows = self._conn.execute(
            f"""
            SELECT i.itemID, i.key, it.typeName, i.dateAdded, i.dateModified
            FROM items i
            JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
            WHERE i.itemID IN ({placeholders})
              AND it.typeName NOT IN ('attachment', 'note', 'annotation')
              AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
            ORDER BY i.dateModified DESC
            """,
            list(item_ids),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["metadata"] = self._get_item_fields(item["itemID"])
            item["creators"] = self._get_item_creators(item["itemID"])
            item["tags"] = self._get_item_tags(item["itemID"])
            item["collections"] = self._get_item_collections(item["itemID"])
            items.append(item)
        return items

    # ─── attachments (PDF links) ────────────────────────────────────

    def get_item_attachments(self, item_id: int) -> List[Dict[str, Any]]:
        """Get attachments for an item. Returns path relative to storage dir."""
        rows = self._conn.execute(
            """
            SELECT ia.itemID AS attachmentID, ia.parentItemID, ia.contentType, ia.path,
                   i.key AS attachmentKey
            FROM itemAttachments ia
            JOIN items i ON i.itemID = ia.itemID
            WHERE ia.parentItemID = ?
              AND ia.contentType = 'application/pdf'
            """,
            (item_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def resolve_pdf_path(self, item_id: int, storage_dir: str) -> Optional[str]:
        """Resolve the actual PDF path for an item given the Zotero storage directory."""
        attachments = self.get_item_attachments(item_id)
        storage = Path(storage_dir)
        for att in attachments:
            key = att.get("attachmentKey", "")
            path_field = att.get("path", "")
            # Zotero stores paths as "storage:filename.pdf"
            if path_field and path_field.startswith("storage:"):
                filename = path_field[len("storage:"):]
                full_path = storage / key / filename
                if full_path.is_file():
                    return str(full_path)
            # Also check for linked files
            elif path_field and Path(path_field).is_file():
                return path_field
            # Fallback: look for any PDF in the attachment key folder
            folder = storage / key
            if folder.is_dir():
                pdfs = list(folder.glob("*.pdf"))
                if pdfs:
                    return str(pdfs[0])
        return None

    def build_pdf_to_item_map(self, storage_dir: str) -> Dict[str, int]:
        """Build a mapping from absolute PDF path -> parent itemID."""
        mapping: Dict[str, int] = {}
        rows = self._conn.execute(
            """
            SELECT ia.parentItemID, ia.path, i.key AS attachmentKey
            FROM itemAttachments ia
            JOIN items i ON i.itemID = ia.itemID
            WHERE ia.parentItemID IS NOT NULL
              AND ia.contentType = 'application/pdf'
            """
        ).fetchall()
        storage = Path(storage_dir)
        for row in rows:
            parent_id = row["parentItemID"]
            path_field = row["path"] or ""
            key = row["attachmentKey"]
            if path_field.startswith("storage:"):
                filename = path_field[len("storage:"):]
                full_path = storage / key / filename
                if full_path.is_file():
                    mapping[str(full_path.resolve())] = parent_id
            elif path_field and Path(path_field).is_file():
                mapping[str(Path(path_field).resolve())] = parent_id
            else:
                folder = storage / key
                if folder.is_dir():
                    for pdf in folder.glob("*.pdf"):
                        mapping[str(pdf.resolve())] = parent_id
        return mapping

    # ─── notes ──────────────────────────────────────────────────────

    def get_item_notes(self, item_id: int) -> List[Dict[str, Any]]:
        """Get all notes attached to a library item."""
        rows = self._conn.execute(
            """
            SELECT in2.itemID AS noteItemID, in2.parentItemID, in2.note,
                   i.key AS noteKey, i.dateAdded, i.dateModified
            FROM itemNotes in2
            JOIN items i ON i.itemID = in2.itemID
            WHERE in2.parentItemID = ?
              AND in2.itemID NOT IN (SELECT itemID FROM deletedItems)
            ORDER BY i.dateAdded
            """,
            (item_id,),
        ).fetchall()
        notes = []
        for row in rows:
            raw_note = row["note"] or ""
            notes.append({
                "noteItemID": row["noteItemID"],
                "parentItemID": row["parentItemID"],
                "noteKey": row["noteKey"],
                "html": raw_note,
                "text": _strip_html(raw_note),
                "dateAdded": row["dateAdded"],
                "dateModified": row["dateModified"],
            })
        return notes

    def get_all_notes(self) -> List[Dict[str, Any]]:
        """Get all notes in the library (with parent info)."""
        rows = self._conn.execute(
            """
            SELECT in2.itemID AS noteItemID, in2.parentItemID, in2.note,
                   i.key AS noteKey, i.dateAdded, i.dateModified
            FROM itemNotes in2
            JOIN items i ON i.itemID = in2.itemID
            WHERE in2.itemID NOT IN (SELECT itemID FROM deletedItems)
              AND in2.parentItemID IS NOT NULL
            ORDER BY i.dateAdded DESC
            """
        ).fetchall()
        notes = []
        for row in rows:
            raw_note = row["note"] or ""
            notes.append({
                "noteItemID": row["noteItemID"],
                "parentItemID": row["parentItemID"],
                "noteKey": row["noteKey"],
                "html": raw_note,
                "text": _strip_html(raw_note),
                "dateAdded": row["dateAdded"],
                "dateModified": row["dateModified"],
            })
        return notes

    # ─── annotations (Zotero 6+ built-in PDF reader) ───────────────

    def get_item_annotations(self, item_id: int) -> List[Dict[str, Any]]:
        """Get PDF annotations for an item (highlights, notes in margins, etc.).

        Annotations are attached to the *attachment* item, not the parent.
        So we first find the attachment, then query annotations on it.
        """
        # Get attachment IDs for this parent item
        att_rows = self._conn.execute(
            """
            SELECT ia.itemID AS attachmentID
            FROM itemAttachments ia
            WHERE ia.parentItemID = ?
            """,
            (item_id,),
        ).fetchall()
        att_ids = [r["attachmentID"] for r in att_rows]
        if not att_ids:
            return []

        # Check if itemAnnotations table exists (Zotero 6+)
        table_check = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='itemAnnotations'"
        ).fetchone()
        if not table_check:
            return []

        placeholders = ",".join("?" for _ in att_ids)
        rows = self._conn.execute(
            f"""
            SELECT ia.itemID AS annotationID, ia.parentItemID AS attachmentID,
                   ia.type, ia.text, ia.comment, ia.color, ia.pageLabel,
                   i.dateAdded, i.dateModified
            FROM itemAnnotations ia
            JOIN items i ON i.itemID = ia.itemID
            WHERE ia.parentItemID IN ({placeholders})
              AND ia.itemID NOT IN (SELECT itemID FROM deletedItems)
            ORDER BY ia.pageLabel, i.dateAdded
            """,
            att_ids,
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── collections ────────────────────────────────────────────────

    def get_collections(self) -> List[Dict[str, Any]]:
        """Get all collections with item counts."""
        rows = self._conn.execute(
            """
            SELECT c.collectionID, c.collectionName, c.parentCollectionID, c.key,
                   (SELECT COUNT(*) FROM collectionItems ci
                    WHERE ci.collectionID = c.collectionID) AS itemCount
            FROM collections c
            ORDER BY c.collectionName
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def get_collection_items(self, collection_id: int) -> List[Dict[str, Any]]:
        """Get all items in a specific collection."""
        rows = self._conn.execute(
            """
            SELECT i.itemID, i.key, it.typeName, i.dateAdded
            FROM collectionItems ci
            JOIN items i ON i.itemID = ci.itemID
            JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
            WHERE ci.collectionID = ?
              AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
            ORDER BY i.dateAdded DESC
            """,
            (collection_id,),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["metadata"] = self._get_item_fields(item["itemID"])
            item["creators"] = self._get_item_creators(item["itemID"])
            items.append(item)
        return items

    # ─── private helpers ────────────────────────────────────────────

    def _get_item_fields(self, item_id: int) -> Dict[str, str]:
        rows = self._conn.execute(
            """
            SELECT f.fieldName, idv.value
            FROM itemData id
            JOIN fields f ON f.fieldID = id.fieldID
            JOIN itemDataValues idv ON idv.valueID = id.valueID
            WHERE id.itemID = ?
            """,
            (item_id,),
        ).fetchall()
        return {r["fieldName"]: r["value"] for r in rows}

    def _get_item_creators(self, item_id: int) -> List[Dict[str, str]]:
        rows = self._conn.execute(
            """
            SELECT c.firstName, c.lastName, ct.creatorType
            FROM itemCreators ic
            JOIN creators c ON c.creatorID = ic.creatorID
            JOIN creatorTypes ct ON ct.creatorTypeID = ic.creatorTypeID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
            """,
            (item_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _get_item_tags(self, item_id: int) -> List[str]:
        rows = self._conn.execute(
            """
            SELECT t.name
            FROM itemTags it
            JOIN tags t ON t.tagID = it.tagID
            WHERE it.itemID = ?
            ORDER BY t.name
            """,
            (item_id,),
        ).fetchall()
        return [r["name"] for r in rows]

    def _get_item_collections(self, item_id: int) -> List[str]:
        rows = self._conn.execute(
            """
            SELECT c.collectionName
            FROM collectionItems ci
            JOIN collections c ON c.collectionID = ci.collectionID
            WHERE ci.itemID = ?
            """,
            (item_id,),
        ).fetchall()
        return [r["collectionName"] for r in rows]


def format_item_summary(item: Dict[str, Any]) -> str:
    """Format a Zotero item into a readable summary string."""
    meta = item.get("metadata", {})
    title = meta.get("title", "Untitled")
    creators = item.get("creators", [])
    author_str = ""
    if creators:
        names = [f"{c.get('lastName', '')}, {c.get('firstName', '')}" for c in creators]
        author_str = "; ".join(names[:5])
        if len(creators) > 5:
            author_str += " et al."

    year = meta.get("date", "")[:4] if meta.get("date") else ""
    journal = meta.get("publicationTitle", "") or meta.get("proceedingsTitle", "")
    doi = meta.get("DOI", "")
    abstract = meta.get("abstractNote", "")

    parts = [f"Title: {title}"]
    if author_str:
        parts.append(f"Authors: {author_str}")
    if year:
        parts.append(f"Year: {year}")
    if journal:
        parts.append(f"Published in: {journal}")
    if doi:
        parts.append(f"DOI: {doi}")
    if item.get("tags"):
        parts.append(f"Tags: {', '.join(item['tags'])}")
    if item.get("collections"):
        parts.append(f"Collections: {', '.join(item['collections'])}")
    if abstract:
        parts.append(f"Abstract: {abstract[:500]}")
    return "\n".join(parts)
