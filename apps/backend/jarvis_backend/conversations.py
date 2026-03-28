"""Local conversation storage — saves chat history as JSON files."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class ConversationStore:
    """Manages conversations stored as individual JSON files."""

    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir / "conversations"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, conv_id: str) -> Path:
        return self.dir / f"{conv_id}.json"

    def create(self, title: str = "New conversation") -> Dict[str, Any]:
        conv_id = uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "id": conv_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        self._path(conv_id).write_text(json.dumps(data, indent=2))
        return data

    def get(self, conv_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(conv_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def list_all(self) -> List[Dict[str, Any]]:
        """List all conversations (metadata only, no messages)."""
        convos = []
        for path in sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text())
                convos.append({
                    "id": data["id"],
                    "title": data.get("title", "Untitled"),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "message_count": len(data.get("messages", [])),
                    "preview": self._preview(data.get("messages", [])),
                })
            except Exception:
                continue
        return convos

    def append_message(self, conv_id: str, role: str, content: str) -> None:
        data = self.get(conv_id)
        if not data:
            return
        data["messages"].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        # Auto-title from first user message
        if data["title"] == "New conversation":
            first_user = next((m for m in data["messages"] if m["role"] == "user"), None)
            if first_user:
                data["title"] = first_user["content"][:80].strip()
        self._path(conv_id).write_text(json.dumps(data, indent=2))

    def update_title(self, conv_id: str, title: str) -> None:
        data = self.get(conv_id)
        if not data:
            return
        data["title"] = title
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._path(conv_id).write_text(json.dumps(data, indent=2))

    def delete(self, conv_id: str) -> bool:
        path = self._path(conv_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def _preview(self, messages: List[Dict[str, Any]]) -> str:
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("content", "")[:100]
                break
        return last_user
