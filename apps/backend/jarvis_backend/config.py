from __future__ import annotations

from typing import Any, Dict, Optional

from jarvis_backend.models import AppConfig
from jarvis_backend.secret_store import (
    ANTHROPIC_API_KEY,
    OPENAI_EMBEDDING_API_KEY,
    SecretStore,
    unwrap_secret,
)
from jarvis_backend.storage import AppPaths, read_json, write_json


class ConfigStore:
    def __init__(self, paths: AppPaths, secret_store: Optional[SecretStore] = None) -> None:
        self.paths = paths
        self.secret_store = secret_store or SecretStore()

    def load(self) -> AppConfig:
        raw = read_json(self.paths.config_path)
        config = AppConfig.model_validate(self._strip_masked_secrets(raw or {}))
        config.anthropic.api_key = self.secret_store.get(ANTHROPIC_API_KEY) or config.anthropic.api_key
        config.embeddings.openai_api_key = (
            self.secret_store.get(OPENAI_EMBEDDING_API_KEY) or config.embeddings.openai_api_key
        )
        return config

    def save(self, config: AppConfig) -> AppConfig:
        self.paths.ensure()
        current = self.load()

        anthropic_secret = unwrap_secret(config.anthropic.api_key) or unwrap_secret(current.anthropic.api_key)
        openai_secret = unwrap_secret(config.embeddings.openai_api_key) or unwrap_secret(
            current.embeddings.openai_api_key
        )

        persisted = config.model_copy(deep=True)
        persisted.anthropic.api_key = self.secret_store.get(ANTHROPIC_API_KEY)
        persisted.embeddings.openai_api_key = self.secret_store.get(OPENAI_EMBEDDING_API_KEY)

        if anthropic_secret:
            self.secret_store.set(ANTHROPIC_API_KEY, anthropic_secret)
            persisted.anthropic.api_key = self.secret_store.get(ANTHROPIC_API_KEY)
        else:
            self.secret_store.delete(ANTHROPIC_API_KEY)
            persisted.anthropic.api_key = None

        if openai_secret:
            self.secret_store.set(OPENAI_EMBEDDING_API_KEY, openai_secret)
            persisted.embeddings.openai_api_key = self.secret_store.get(OPENAI_EMBEDDING_API_KEY)
        else:
            self.secret_store.delete(OPENAI_EMBEDDING_API_KEY)
            persisted.embeddings.openai_api_key = None

        write_json(self.paths.config_path, persisted.persistence_dump())
        return persisted

    def _strip_masked_secrets(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not payload:
            return {}

        cleaned = dict(payload)
        anthropic = dict(cleaned.get("anthropic") or {})
        embeddings = dict(cleaned.get("embeddings") or {})

        if self._is_masked_placeholder(anthropic.get("api_key")):
            anthropic["api_key"] = None
        if self._is_masked_placeholder(embeddings.get("openai_api_key")):
            embeddings["openai_api_key"] = None

        if anthropic:
            cleaned["anthropic"] = anthropic
        if embeddings:
            cleaned["embeddings"] = embeddings
        return cleaned

    def _is_masked_placeholder(self, value: object) -> bool:
        return isinstance(value, str) and value and set(value) == {"*"}
