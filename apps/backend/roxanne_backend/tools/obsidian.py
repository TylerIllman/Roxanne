from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from roxanne_backend.config import ConfigStore
from roxanne_backend.ingestion.indexer import ContentIndexer
from roxanne_backend.models import VaultConfig
from roxanne_backend.retrieval import RetrievalStore
from roxanne_backend.tools.base import BaseTool, ToolExecutionError


class ReadNotesTool(BaseTool):
    name = "read_notes"
    description = "Semantic/vector search across indexed Obsidian note chunks across all configured vaults."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Concept or note to retrieve."}
        },
        "required": ["query"],
    }

    def __init__(self, retrieval: RetrievalStore) -> None:
        self.retrieval = retrieval

    async def invoke(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        query = payload["query"].strip()
        rows = self.retrieval.query(RetrievalStore.NOTE_COLLECTION, query, n_results=6)
        return [
            {
                "note_id": row["metadata"].get("note_id"),
                "title": row["metadata"].get("title"),
                "vault_name": row["metadata"].get("vault_name"),
                "relative_path": row["metadata"].get("relative_path"),
                "absolute_path": row["metadata"].get("absolute_path"),
                "chunk_index": row["metadata"].get("chunk_index"),
                "total_chunks": row["metadata"].get("total_chunks"),
                "citation_path": row["metadata"].get("absolute_path"),
                "citation_page": None,
                "chunk": row["document"],
                "excerpt": row["document"][:600],
                "score": row["distance"],
            }
            for row in rows
        ]


class WriteNoteTool(BaseTool):
    name = "write_note"
    description = "Write a markdown note into a configured Obsidian vault."
    input_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "location": {
                "type": "string",
                "description": "Relative markdown path inside the target vault."
            },
            "vault_id": {
                "type": "string",
                "description": "Optional specific Obsidian vault id."
            },
            "append": {
                "type": "boolean",
                "description": "Append to the note if it already exists."
            },
        },
        "required": ["content", "location"],
    }

    def __init__(self, config_store: ConfigStore, indexer: ContentIndexer) -> None:
        self.config_store = config_store
        self.indexer = indexer

    async def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config_store.load()
        if not config.obsidian_vaults:
            raise ToolExecutionError("No Obsidian vaults are configured.")

        vault = self._resolve_vault(config.obsidian_vaults, payload.get("vault_id"))
        relative_path = payload["location"].strip().lstrip("/")
        content = payload["content"].strip()
        append = bool(payload.get("append"))

        target_path = Path(vault.path).expanduser() / relative_path
        if target_path.suffix.lower() != ".md":
            target_path = target_path.with_suffix(".md")
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.exists() and not append:
            raise ToolExecutionError(
                "The target note already exists. Retry with append=true to extend it."
            )

        mode = "a" if append else "w"
        with target_path.open(mode, encoding="utf-8") as handle:
            if append and target_path.stat().st_size > 0:
                handle.write("\n\n")
            handle.write(content)

        indexed_chunks = self.indexer.index_note_file(vault, target_path)
        return {
            "vault_id": vault.id,
            "vault_name": vault.name,
            "absolute_path": str(target_path),
            "relative_path": str(target_path.relative_to(Path(vault.path).expanduser())),
            "indexed_chunks": indexed_chunks,
        }

    def _resolve_vault(self, vaults: List[VaultConfig], vault_id: Optional[str]) -> VaultConfig:
        if not vault_id:
            return vaults[0]
        for vault in vaults:
            if vault.id == vault_id:
                return vault
        raise ToolExecutionError(f"No Obsidian vault found for vault_id={vault_id}.")
