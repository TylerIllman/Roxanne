"""Tests for cross-platform secret storage fallback behavior."""
from __future__ import annotations

import pytest

import roxanne_backend.secret_store as secret_store_module
from roxanne_backend.secret_store import ANTHROPIC_API_KEY, SecretStore
from roxanne_backend.storage import AppPaths


class TestSecretStore:
    def test_falls_back_to_local_store_when_keyring_missing(self, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(secret_store_module, "keyring", None)

        store = SecretStore(app_paths)
        store.set(ANTHROPIC_API_KEY, "sk-local-secret")

        loaded = store.get(ANTHROPIC_API_KEY)

        assert loaded is not None
        assert loaded.get_secret_value() == "sk-local-secret"
        assert app_paths.secrets_path.exists()
        assert app_paths.secrets_key_path.exists()

    def test_falls_back_to_local_store_when_keyring_backend_errors(self, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch):
        class BrokenKeyring:
            def get_password(self, _service: str, _username: str):
                raise RuntimeError("backend broken")

            def set_password(self, _service: str, _username: str, _value: str):
                raise RuntimeError("backend broken")

            def delete_password(self, _service: str, _username: str):
                raise RuntimeError("backend broken")

        monkeypatch.setattr(secret_store_module, "keyring", BrokenKeyring())
        monkeypatch.setattr(secret_store_module, "KeyringError", RuntimeError)
        monkeypatch.setattr(secret_store_module, "PasswordDeleteError", RuntimeError)

        store = SecretStore(app_paths)
        store.set(ANTHROPIC_API_KEY, "sk-fallback-secret")

        loaded = store.get(ANTHROPIC_API_KEY)

        assert loaded is not None
        assert loaded.get_secret_value() == "sk-fallback-secret"

    def test_clears_fallback_copy_after_successful_keyring_write(self, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch):
        stored: dict[tuple[str, str], str] = {}

        class WorkingKeyring:
            def get_password(self, service: str, username: str):
                return stored.get((service, username))

            def set_password(self, service: str, username: str, value: str):
                stored[(service, username)] = value

            def delete_password(self, service: str, username: str):
                stored.pop((service, username), None)

        monkeypatch.setattr(secret_store_module, "keyring", WorkingKeyring())
        monkeypatch.setattr(secret_store_module, "KeyringError", RuntimeError)
        monkeypatch.setattr(secret_store_module, "PasswordDeleteError", RuntimeError)

        store = SecretStore(app_paths)
        store.fallback_store.set(ANTHROPIC_API_KEY, "stale-local-secret")

        store.set(ANTHROPIC_API_KEY, "sk-keyring-secret")

        loaded = store.get(ANTHROPIC_API_KEY)

        assert loaded is not None
        assert loaded.get_secret_value() == "sk-keyring-secret"
        assert store.fallback_store.get(ANTHROPIC_API_KEY) is None
