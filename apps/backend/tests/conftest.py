"""Shared fixtures for the Roxanne backend test suite."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest

from roxanne_backend.models import AppConfig, LLMConfig, SpeechConfig, VaultConfig, ZoteroConfig
from roxanne_backend.storage import AppPaths


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a clean temporary directory."""
    return tmp_path


@pytest.fixture
def app_paths(tmp_dir: Path) -> AppPaths:
    """AppPaths rooted in a temp directory."""
    return AppPaths(root=tmp_dir / "roxanne_data")


@pytest.fixture
def sample_config(tmp_dir: Path) -> AppConfig:
    """A minimal valid config for testing."""
    vault_path = tmp_dir / "test_vault"
    vault_path.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        anthropic=LLMConfig(
            provider="anthropic",
            api_key="sk-ant-test-key-12345",
            model="claude-sonnet-4-20250514",
            max_tokens=1400,
        ),
        zotero=ZoteroConfig(
            database_path=str(tmp_dir / "zotero.sqlite"),
            storage_path=str(tmp_dir / "zotero_storage"),
        ),
        speech=SpeechConfig(
            stt_model="vosk-model-small-en-us-0.15",
            voice_id="en_US-amy-medium",
            speed=1.15,
        ),
        obsidian_vaults=[
            VaultConfig(name="Test Vault", path=str(vault_path)),
        ],
    )


@pytest.fixture
def ollama_config() -> AppConfig:
    """Config for Ollama provider testing."""
    return AppConfig(
        anthropic=LLMConfig(
            provider="ollama",
            model="qwen2.5:7b",
            base_url="http://localhost:11434/v1",
        ),
    )


@pytest.fixture
def zotero_storage(tmp_dir: Path) -> Path:
    """Create a fake Zotero storage directory with sample PDFs."""
    storage = tmp_dir / "zotero_storage"
    storage.mkdir(parents=True, exist_ok=True)

    # Create a few fake PDF "directories" mimicking Zotero layout
    for key in ["ABCD1234", "EFGH5678"]:
        item_dir = storage / key
        item_dir.mkdir()
        # Create a minimal PDF (just the header — enough for fitz to open)
        pdf_path = item_dir / f"test_paper_{key}.pdf"
        pdf_path.write_bytes(
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R"
            b"/Contents 4 0 R>>endobj\n"
            b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 100 700 Td "
            b"(Hello World) Tj ET\nendstream\nendobj\n"
            b"xref\n0 5\n0000000000 65535 f \n"
            b"0000000009 00000 n \n0000000058 00000 n \n"
            b"0000000115 00000 n \n0000000206 00000 n \n"
            b"trailer<</Size 5/Root 1 0 R>>\nstartxref\n302\n%%EOF"
        )
    return storage


@pytest.fixture
def obsidian_vault(tmp_dir: Path) -> Path:
    """Create a fake Obsidian vault with sample notes."""
    vault = tmp_dir / "test_vault"
    vault.mkdir(parents=True, exist_ok=True)

    (vault / "Note One.md").write_text("# Note One\n\nThis is the first test note about machine learning.\n")
    (vault / "Note Two.md").write_text("# Note Two\n\nThis note discusses transformer architectures and attention mechanisms.\n")

    sub = vault / "Research"
    sub.mkdir()
    (sub / "Deep Learning.md").write_text("# Deep Learning\n\nNeural networks with many layers can learn hierarchical representations.\n")

    return vault
