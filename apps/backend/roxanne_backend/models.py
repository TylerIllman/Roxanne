from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class VaultConfig(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str = Field(min_length=1)
    path: str = Field(min_length=1)


class LLMConfig(BaseModel):
    """Unified LLM config supporting Anthropic, OpenAI-compatible, and Ollama."""
    provider: Literal["anthropic", "openai", "ollama"] = "anthropic"
    api_key: Optional[SecretStr] = None
    model: str = ""
    max_tokens: int = 1400
    max_tool_loops: int = Field(default=12, ge=1, le=30)
    # OpenAI-compatible endpoint (also used for Ollama)
    base_url: Optional[str] = None


# Keep backwards compat alias
AnthropicConfig = LLMConfig


class ZoteroConfig(BaseModel):
    database_path: Optional[str] = None
    storage_path: Optional[str] = None


class EmbeddingConfig(BaseModel):
    provider: Literal["fastembed", "openai"] = "fastembed"
    model: str = "BAAI/bge-base-en-v1.5"
    openai_api_key: Optional[SecretStr] = None
    openai_base_url: Optional[str] = None


class SpeechConfig(BaseModel):
    stt_model: str = "small"
    piper_executable_path: Optional[str] = None
    piper_voice_model_path: Optional[str] = None
    voice_id: str = "en_US-amy-medium"
    speed: float = 1.15  # 1.0=normal, >1=faster


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    zotero: ZoteroConfig = Field(default_factory=ZoteroConfig)
    embeddings: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    speech: SpeechConfig = Field(default_factory=SpeechConfig)
    obsidian_vaults: List[VaultConfig] = Field(default_factory=list)

    def is_complete(self) -> bool:
        llm = self.anthropic
        has_llm = bool(llm.model.strip())
        if llm.provider in ("anthropic", "openai"):
            has_llm = has_llm and bool(llm.api_key)
        # Ollama doesn't need an API key
        return bool(
            has_llm
            and self.zotero.storage_path
            and self.obsidian_vaults
        )

    def public_dump(self) -> Dict[str, Any]:
        payload = self.model_dump(mode="json")
        if payload["anthropic"].get("api_key"):
            payload["anthropic"]["api_key"] = "***"
        if payload["embeddings"].get("openai_api_key"):
            payload["embeddings"]["openai_api_key"] = "***"
        payload["is_complete"] = self.is_complete()
        return payload

    def persistence_dump(self) -> Dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["anthropic"]["api_key"] = None
        payload["embeddings"]["openai_api_key"] = None
        return payload


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: List[ConversationTurn] = Field(default_factory=list)
    session_id: str = Field(default_factory=lambda: uuid4().hex)
    voice_mode: bool = False
    conversation_id: Optional[str] = None


class IndexRequest(BaseModel):
    scope: Literal["all", "papers", "notes"] = "all"


class AudioTranscriptionRequest(BaseModel):
    path: str = Field(min_length=1)


class SpeechSynthesisRequest(BaseModel):
    text: str = Field(min_length=1)


class IndexedDocument(BaseModel):
    id: str
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolEvent(BaseModel):
    type: str
    message: Optional[str] = None
    tool: Optional[str] = None
    delta: Optional[str] = None
    payload: Optional[Any] = None
