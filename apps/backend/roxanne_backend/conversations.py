"""SQL-backed local conversation storage.

Uses SQLite locally today, with a schema that can move cleanly to a hosted SQL
database later.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from roxanne_backend.storage import restrict_permissions

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStore:
    """Manages conversations stored in a local SQLite database."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
        ON conversations(updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
        ON messages(conversation_id, id);
    """

    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        restrict_permissions(self.root, directory=True)
        self.db_path = self.root / "conversations.sqlite3"
        self.legacy_dir = self.root / "conversations"
        self._initialize()
        self._migrate_legacy_json_files()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        restrict_permissions(self.db_path.parent, directory=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(self._SCHEMA)
        restrict_permissions(self.db_path, directory=False)

    def _migrate_legacy_json_files(self) -> None:
        if not self.legacy_dir.exists():
            return

        legacy_files = sorted(self.legacy_dir.glob("*.json"))
        if not legacy_files:
            return

        with self._connect() as conn:
            for path in legacy_files:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.warning("Skipping legacy conversation %s: %s", path, exc)
                    continue

                conv_id = str(data.get("id") or uuid4().hex[:12])
                created_at = str(data.get("created_at") or _utc_now())
                updated_at = str(data.get("updated_at") or created_at)
                title = str(data.get("title") or "Untitled")

                conn.execute(
                    """
                    INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (conv_id, title, created_at, updated_at),
                )

                existing = conn.execute(
                    "SELECT COUNT(1) AS count FROM messages WHERE conversation_id = ?",
                    (conv_id,),
                ).fetchone()
                if existing and int(existing["count"]) > 0:
                    continue

                for message in data.get("messages", []):
                    conn.execute(
                        """
                        INSERT INTO messages (conversation_id, role, content, timestamp)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            conv_id,
                            str(message.get("role") or "user"),
                            str(message.get("content") or ""),
                            str(message.get("timestamp") or updated_at),
                        ),
                    )

            conn.commit()

    def create(self, title: str = "New conversation") -> Dict[str, Any]:
        conv_id = uuid4().hex[:12]
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (conv_id, title, now, now),
            )
            conn.commit()
        return {
            "id": conv_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }

    def get(self, conv_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conversation = conn.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                WHERE id = ?
                """,
                (conv_id,),
            ).fetchone()
            if conversation is None:
                return None

            messages = conn.execute(
                """
                SELECT role, content, timestamp
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id ASC
                """,
                (conv_id,),
            ).fetchall()

        return {
            "id": conversation["id"],
            "title": conversation["title"],
            "created_at": conversation["created_at"],
            "updated_at": conversation["updated_at"],
            "messages": [
                {
                    "role": row["role"],
                    "content": row["content"],
                    "timestamp": row["timestamp"],
                }
                for row in messages
            ],
        }

    def list_all(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    COUNT(m.id) AS message_count,
                    COALESCE(
                        (
                            SELECT m2.content
                            FROM messages m2
                            WHERE m2.conversation_id = c.id
                              AND m2.role = 'user'
                            ORDER BY m2.id DESC
                            LIMIT 1
                        ),
                        ''
                    ) AS preview
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                GROUP BY c.id, c.title, c.created_at, c.updated_at
                ORDER BY c.updated_at DESC, c.created_at DESC
                """
            ).fetchall()

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "message_count": int(row["message_count"]),
                "preview": row["preview"],
            }
            for row in rows
        ]

    def append_message(self, conv_id: str, role: str, content: str) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conversation = conn.execute(
                "SELECT title FROM conversations WHERE id = ?",
                (conv_id,),
            ).fetchone()
            if conversation is None:
                return

            conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (conv_id, role, content, now),
            )

            title = conversation["title"]
            if title == "New conversation" and role == "user" and content.strip():
                title = content[:80].strip()

            conn.execute(
                """
                UPDATE conversations
                SET title = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, now, conv_id),
            )
            conn.commit()

    def prompt_history(self, conv_id: str) -> List[Dict[str, str]]:
        conversation = self.get(conv_id)
        if not conversation:
            return []
        return [
            {"role": str(message["role"]), "content": str(message["content"])}
            for message in conversation["messages"]
            if message.get("role") in {"user", "assistant"} and str(message.get("content", "")).strip()
        ]

    def update_title(self, conv_id: str, title: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE conversations
                SET title = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, _utc_now(), conv_id),
            )
            conn.commit()

    def delete(self, conv_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            conn.commit()
        return cursor.rowcount > 0
