from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import chromadb
from fastembed import TextEmbedding
from openai import OpenAI

from jarvis_backend.models import EmbeddingConfig, IndexedDocument
from jarvis_backend.storage import AppPaths


class EmbeddingManager:
    def __init__(self, settings: EmbeddingConfig) -> None:
        self.settings = settings
        self._fastembed: Optional[TextEmbedding] = None
        self._openai: Optional[OpenAI] = None

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if self.settings.provider == "openai":
            if not self.settings.openai_api_key:
                raise ValueError("OpenAI embeddings are selected, but no API key is configured.")
            if self._openai is None:
                self._openai = OpenAI(
                    api_key=self.settings.openai_api_key.get_secret_value(),
                    base_url=self.settings.openai_base_url,
                )
            response = self._openai.embeddings.create(model=self.settings.model, input=texts)
            return [item.embedding for item in response.data]

        if self._fastembed is None:
            self._fastembed = TextEmbedding(model_name=self.settings.model)
        return [[float(x) for x in vector] for vector in self._fastembed.embed(texts)]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


class RetrievalStore:
    PAPER_COLLECTION = "papers"
    NOTE_COLLECTION = "notes"
    MEMORY_COLLECTION = "memories"

    def __init__(self, paths: AppPaths, embedding_settings: EmbeddingConfig) -> None:
        paths.ensure()
        self.client = chromadb.PersistentClient(path=str(paths.index_path))
        self.embeddings = EmbeddingManager(embedding_settings)

    def _collection(self, name: str):
        return self.client.get_or_create_collection(name)

    def upsert(self, collection_name: str, documents: Iterable[IndexedDocument]) -> int:
        batch = list(documents)
        if not batch:
            return 0
        collection = self._collection(collection_name)
        embeddings = self.embeddings.embed_documents([item.text for item in batch])
        collection.upsert(
            ids=[item.id for item in batch],
            documents=[item.text for item in batch],
            metadatas=[item.metadata for item in batch],
            embeddings=embeddings,
        )
        return len(batch)

    def delete_where(self, collection_name: str, where: Dict[str, Any]) -> None:
        self._collection(collection_name).delete(where=where)

    def query(
        self,
        collection_name: str,
        query: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        collection = self._collection(collection_name)
        response = collection.query(
            query_embeddings=[self.embeddings.embed_query(query)],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        documents = response.get("documents", [[]])[0]
        metadatas = response.get("metadatas", [[]])[0]
        distances = response.get("distances", [[]])[0]

        rows: List[Dict[str, Any]] = []
        for document, metadata, distance in zip(documents, metadatas, distances):
            rows.append(
                {
                    "document": document,
                    "metadata": metadata or {},
                    "distance": distance,
                }
            )
        return rows

    def list_collection(
        self, collection_name: str, limit: int = 2000, offset: int = 0,
        full_text: bool = False,
    ) -> Dict[str, Any]:
        """Return all documents in a collection with metadata (no embeddings)."""
        collection = self._collection(collection_name)
        total = collection.count()
        response = collection.get(
            limit=limit,
            offset=offset,
            include=["documents", "metadatas"],
        )
        ids = response.get("ids", [])
        documents = response.get("documents", [])
        metadatas = response.get("metadatas", [])

        items: List[Dict[str, Any]] = []
        for item_id, document, metadata in zip(ids, documents, metadatas):
            text = document or ""
            items.append({
                "id": item_id,
                "text": text if full_text else text[:300],
                "metadata": metadata or {},
            })
        return {"total": total, "items": items}

    def get_by_metadata(
        self, collection_name: str, where: Dict[str, Any], limit: int = 10
    ) -> List[Dict[str, Any]]:
        collection = self._collection(collection_name)
        response = collection.get(where=where, limit=limit, include=["documents", "metadatas"])
        documents = response.get("documents", [])
        metadatas = response.get("metadatas", [])
        ids = response.get("ids", [])

        rows: List[Dict[str, Any]] = []
        for item_id, document, metadata in zip(ids, documents, metadatas):
            rows.append(
                {
                    "id": item_id,
                    "document": document,
                    "metadata": metadata or {},
                }
            )
        return rows


class SessionMemoryStore:
    def __init__(self, retrieval: RetrievalStore) -> None:
        self.retrieval = retrieval

    def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        return self.retrieval.query(RetrievalStore.MEMORY_COLLECTION, query, n_results=limit)

    def remember(self, session_id: str, user_message: str, assistant_reply: str) -> None:
        summary = (
            "Session summary:\n"
            f"User asked: {user_message.strip()}\n"
            f"Assistant answered: {assistant_reply.strip()[:1600]}"
        )
        digest = hashlib.sha1(
            f"{session_id}:{user_message}:{assistant_reply}".encode("utf-8")
        ).hexdigest()
        document = IndexedDocument(
            id=digest,
            text=summary,
            metadata={
                "session_id": session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.retrieval.upsert(RetrievalStore.MEMORY_COLLECTION, [document])

