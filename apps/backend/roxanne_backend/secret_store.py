from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import SecretStr

from roxanne_backend.storage import AppPaths, restrict_permissions

try:
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError
except ImportError:  # pragma: no cover - handled at runtime if deps are stale
    keyring = None
    KeyringError = Exception
    PasswordDeleteError = Exception


logger = logging.getLogger(__name__)

SERVICE_NAME = "RoxanneAssistant"
ANTHROPIC_API_KEY = "anthropic_api_key"
OPENAI_EMBEDDING_API_KEY = "openai_embedding_api_key"
_SECRET_FILE_VERSION = 1
SECRET_STORE_MODE_ENV = "ROXANNE_SECRET_STORE"
KEYRING_TIMEOUT_ENV = "ROXANNE_KEYRING_TIMEOUT_SECONDS"
DEFAULT_SECRET_STORE_MODE = "auto"
DEFAULT_KEYRING_TIMEOUT_SECONDS = 0.75


def unwrap_secret(value: Optional[SecretStr]) -> Optional[str]:
    if value is None:
        return None
    secret = value.get_secret_value().strip()
    return secret or None


class LocalSecretFileStore:
    def __init__(self, secrets_path: Path, key_path: Path) -> None:
        self.secrets_path = secrets_path
        self.key_path = key_path

    def get(self, key: str) -> Optional[SecretStr]:
        payload = self._read_payload()
        raw_entry = payload.get(key)
        if not isinstance(raw_entry, dict):
            return None
        try:
            value = self._decrypt_entry(raw_entry)
        except Exception:
            logger.warning("Failed to decrypt local secret for %s.", key)
            return None
        return SecretStr(value) if value else None

    def set(self, key: str, value: str) -> None:
        payload = self._read_payload()
        payload[key] = self._encrypt_entry(value)
        self._write_payload(payload)

    def delete(self, key: str) -> None:
        payload = self._read_payload()
        if key in payload:
            payload.pop(key, None)
            self._write_payload(payload)

    def _read_payload(self) -> Dict[str, Any]:
        if not self.secrets_path.exists():
            return {}
        try:
            return json.loads(self.secrets_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Secret store file is unreadable, treating it as empty.")
            return {}

    def _write_payload(self, payload: Dict[str, Any]) -> None:
        self.secrets_path.parent.mkdir(parents=True, exist_ok=True)
        restrict_permissions(self.secrets_path.parent, directory=True)
        temp_path = self.secrets_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        restrict_permissions(temp_path, directory=False)
        temp_path.replace(self.secrets_path)
        restrict_permissions(self.secrets_path, directory=False)

    def _load_master_key(self) -> bytes:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        restrict_permissions(self.key_path.parent, directory=True)
        if self.key_path.exists():
            raw = self.key_path.read_bytes()
            if raw:
                return raw
        key_bytes = secrets.token_bytes(32)
        self.key_path.write_bytes(key_bytes)
        restrict_permissions(self.key_path, directory=False)
        return key_bytes

    def _keystream(self, key_bytes: bytes, nonce: bytes, length: int) -> bytes:
        stream = bytearray()
        counter = 0
        while len(stream) < length:
            block = hashlib.sha256(key_bytes + nonce + counter.to_bytes(4, "big")).digest()
            stream.extend(block)
            counter += 1
        return bytes(stream[:length])

    def _encrypt_entry(self, plaintext: str) -> Dict[str, str | int]:
        key_bytes = self._load_master_key()
        nonce = secrets.token_bytes(16)
        plain_bytes = plaintext.encode("utf-8")
        keystream = self._keystream(key_bytes, nonce, len(plain_bytes))
        cipher_bytes = bytes(a ^ b for a, b in zip(plain_bytes, keystream))
        mac = hmac.new(key_bytes, nonce + cipher_bytes, hashlib.sha256).digest()
        return {
            "version": _SECRET_FILE_VERSION,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(cipher_bytes).decode("ascii"),
            "mac": base64.b64encode(mac).decode("ascii"),
        }

    def _decrypt_entry(self, entry: Dict[str, Any]) -> str:
        version = int(entry.get("version", 0))
        if version != _SECRET_FILE_VERSION:
            raise ValueError(f"Unsupported secret version: {version}")
        nonce = base64.b64decode(str(entry["nonce"]))
        cipher_bytes = base64.b64decode(str(entry["ciphertext"]))
        stored_mac = base64.b64decode(str(entry["mac"]))
        key_bytes = self._load_master_key()
        expected_mac = hmac.new(key_bytes, nonce + cipher_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(stored_mac, expected_mac):
            raise ValueError("Secret MAC mismatch")
        keystream = self._keystream(key_bytes, nonce, len(cipher_bytes))
        plain_bytes = bytes(a ^ b for a, b in zip(cipher_bytes, keystream))
        return plain_bytes.decode("utf-8")


class SecretStore:
    def __init__(self, paths: Optional[AppPaths] = None, service_name: str = SERVICE_NAME) -> None:
        self.service_name = service_name
        self.paths = paths or AppPaths()
        self.fallback_store = LocalSecretFileStore(self.paths.secrets_path, self.paths.secrets_key_path)
        self.mode = self._resolve_mode(os.getenv(SECRET_STORE_MODE_ENV))
        self.keyring_timeout_seconds = self._resolve_timeout(os.getenv(KEYRING_TIMEOUT_ENV))

    def is_available(self) -> bool:
        return True

    def get(self, key: str) -> Optional[SecretStr]:
        if self.mode != "local":
            value = self._get_from_keyring(key)
            if value is not None:
                return value
            return self.fallback_store.get(key)

        local_value = self.fallback_store.get(key)
        if local_value is not None:
            return local_value

        if not self._should_use_keyring():
            return None

        value = self._get_from_keyring(key)
        if value is not None and self.mode == "local":
            self.fallback_store.set(key, value.get_secret_value())
        return value

    def set(self, key: str, value: str) -> None:
        if self.mode == "local":
            self.fallback_store.set(key, value)
            return

        if self._set_in_keyring(key, value):
            self.fallback_store.delete(key)
            return

        self.fallback_store.set(key, value)

    def delete(self, key: str) -> None:
        if self.mode != "local":
            self._delete_from_keyring(key)
        self.fallback_store.delete(key)

    def _resolve_mode(self, raw_mode: Optional[str]) -> str:
        normalized = (raw_mode or DEFAULT_SECRET_STORE_MODE).strip().lower()
        if normalized in {"auto", "keyring", "local"}:
            return normalized
        logger.warning("Unknown secret store mode '%s', falling back to %s.", raw_mode, DEFAULT_SECRET_STORE_MODE)
        return DEFAULT_SECRET_STORE_MODE

    def _resolve_timeout(self, raw_timeout: Optional[str]) -> float:
        if raw_timeout is None:
            return DEFAULT_KEYRING_TIMEOUT_SECONDS
        try:
            return max(float(raw_timeout), 0.05)
        except ValueError:
            logger.warning(
                "Invalid %s value '%s', using %.2f seconds.",
                KEYRING_TIMEOUT_ENV,
                raw_timeout,
                DEFAULT_KEYRING_TIMEOUT_SECONDS,
            )
            return DEFAULT_KEYRING_TIMEOUT_SECONDS

    def _should_use_keyring(self) -> bool:
        return keyring is not None and self.mode in {"auto", "keyring", "local"}

    def _get_from_keyring(self, key: str) -> Optional[SecretStr]:
        if keyring is None:
            return None
        try:
            value = self._run_keyring_operation(
                lambda: keyring.get_password(self.service_name, key),
                action="read",
                key=key,
            )
            if value:
                return SecretStr(value)
        except KeyringError as exc:  # pragma: no cover - backend specific
            logger.warning("Keyring read failed for %s, falling back to local secret store: %s", key, exc)
        return None

    def _set_in_keyring(self, key: str, value: str) -> bool:
        if keyring is None:
            return False
        try:
            self._run_keyring_operation(
                lambda: keyring.set_password(self.service_name, key, value),
                action="write",
                key=key,
            )
            return True
        except KeyringError as exc:  # pragma: no cover - backend specific
            logger.warning("Keyring write failed for %s, falling back to local secret store: %s", key, exc)
            return False

    def _delete_from_keyring(self, key: str) -> None:
        if keyring is None:
            return
        try:
            self._run_keyring_operation(
                lambda: keyring.delete_password(self.service_name, key),
                action="delete",
                key=key,
            )
        except PasswordDeleteError:
            pass
        except KeyringError as exc:  # pragma: no cover - backend specific
            logger.warning("Keyring delete failed for %s, falling back to local secret store cleanup: %s", key, exc)

    def _run_keyring_operation(self, operation, *, action: str, key: str):
        result: Dict[str, Any] = {"done": False, "value": None, "error": None}

        def target() -> None:
            try:
                result["value"] = operation()
            except Exception as exc:  # pragma: no cover - backend specific
                result["error"] = exc
            finally:
                result["done"] = True

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(self.keyring_timeout_seconds)

        if not result["done"]:
            logger.warning(
                "Keyring %s timed out for %s after %.2fs; using local secret store instead.",
                action,
                key,
                self.keyring_timeout_seconds,
            )
            return None

        if result["error"] is not None:
            raise result["error"]

        return result["value"]
