"""Tests for ConfigStore — load, save, secret management."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from roxanne_backend.config import ConfigStore
from roxanne_backend.models import AppConfig, LLMConfig
from roxanne_backend.storage import AppPaths


@pytest.fixture
def config_store(app_paths: AppPaths) -> ConfigStore:
    """ConfigStore with a mock secret store (no real keyring)."""
    mock_secrets = MagicMock()
    mock_secrets.get.return_value = None
    return ConfigStore(app_paths, secret_store=mock_secrets)


class TestConfigStore:
    def test_load_empty(self, config_store: ConfigStore):
        """Loading when no config file exists returns defaults."""
        config = config_store.load()
        assert isinstance(config, AppConfig)
        assert config.anthropic.provider == "anthropic"
        assert config.anthropic.model == ""

    def test_save_and_reload(self, config_store: ConfigStore):
        """Save a config, then load it back."""
        config = AppConfig(
            anthropic=LLMConfig(provider="ollama", model="qwen2.5:7b"),
        )
        config_store.save(config)
        reloaded = config_store.load()
        assert reloaded.anthropic.provider == "ollama"
        assert reloaded.anthropic.model == "qwen2.5:7b"

    def test_save_strips_api_key_from_disk(self, config_store: ConfigStore, app_paths: AppPaths):
        """API key should be saved to secret store, not the JSON file."""
        config = AppConfig(
            anthropic=LLMConfig(api_key="sk-secret-key", model="test"),
        )
        config_store.save(config)

        # Read the raw JSON file
        config_path = app_paths.root / "config.json"
        raw = json.loads(config_path.read_text())
        # Key should NOT be in the JSON
        assert raw.get("anthropic", {}).get("api_key") is None or raw["anthropic"]["api_key"] == ""

    def test_save_calls_secret_store(self, config_store: ConfigStore):
        """Saving with an API key should call the secret store."""
        config = AppConfig(
            anthropic=LLMConfig(api_key="sk-new-key", model="test"),
        )
        config_store.save(config)
        # The mock secret store's set method should have been called
        config_store.secret_store.set.assert_called()

    def test_load_strips_masked_key(self, config_store: ConfigStore, app_paths: AppPaths):
        """Loading a config with masked '***' key should treat it as absent."""
        import json
        config_path = app_paths.config_path
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({
            "anthropic": {"api_key": "***", "model": "m"},
        }))
        config = config_store.load()
        # Masked key should be stripped — falls back to secret store or None
        assert config.anthropic.api_key is None or (
            hasattr(config.anthropic.api_key, "get_secret_value")
            and config.anthropic.api_key.get_secret_value() != "***"
        )


class TestConfigStoreEdgeCases:
    def test_corrupted_config_file(self, config_store: ConfigStore, app_paths: AppPaths):
        """A corrupted config file raises JSONDecodeError."""
        import json as _json
        config_path = app_paths.config_path
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("{invalid json!!")
        with pytest.raises(_json.JSONDecodeError):
            config_store.load()

    def test_extra_fields_in_config(self, config_store: ConfigStore, app_paths: AppPaths):
        """Unknown fields in config file should be ignored."""
        config_path = app_paths.config_path
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({
            "anthropic": {"provider": "anthropic", "model": "test"},
            "future_field": "some_value",
        }))
        config = config_store.load()
        assert config.anthropic.model == "test"
