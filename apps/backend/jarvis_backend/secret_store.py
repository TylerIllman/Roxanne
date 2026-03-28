from __future__ import annotations

from typing import Optional

from pydantic import SecretStr

try:
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError
except ImportError:  # pragma: no cover - handled at runtime if deps are stale
    keyring = None
    KeyringError = Exception
    PasswordDeleteError = Exception


SERVICE_NAME = "JarvisAssistant"
ANTHROPIC_API_KEY = "anthropic_api_key"
OPENAI_EMBEDDING_API_KEY = "openai_embedding_api_key"


def unwrap_secret(value: Optional[SecretStr]) -> Optional[str]:
    if value is None:
        return None
    secret = value.get_secret_value().strip()
    return secret or None


class SecretStore:
    def __init__(self, service_name: str = SERVICE_NAME) -> None:
        self.service_name = service_name

    def is_available(self) -> bool:
        return keyring is not None

    def get(self, key: str) -> Optional[SecretStr]:
        if keyring is None:
            return None
        try:
            value = keyring.get_password(self.service_name, key)
        except KeyringError as exc:  # pragma: no cover - backend specific
            raise RuntimeError(f"Secure secret storage failed while reading {key}.") from exc
        return SecretStr(value) if value else None

    def set(self, key: str, value: str) -> None:
        if keyring is None:
            raise RuntimeError(
                "Secure secret storage is unavailable. Reinstall backend dependencies to enable keychain support."
            )
        try:
            keyring.set_password(self.service_name, key, value)
        except KeyringError as exc:  # pragma: no cover - backend specific
            raise RuntimeError(f"Secure secret storage failed while writing {key}.") from exc

    def delete(self, key: str) -> None:
        if keyring is None:
            return
        try:
            keyring.delete_password(self.service_name, key)
        except PasswordDeleteError:
            return
        except KeyringError as exc:  # pragma: no cover - backend specific
            raise RuntimeError(f"Secure secret storage failed while deleting {key}.") from exc
