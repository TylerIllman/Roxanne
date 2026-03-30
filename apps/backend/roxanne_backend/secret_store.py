from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
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

    def is_available(self) -> bool:
        return True

    def get(self, key: str) -> Optional[SecretStr]:
        if keyring is not None:
            try:
                value = keyring.get_password(self.service_name, key)
                if value:
                    return SecretStr(value)
            except KeyringError as exc:  # pragma: no cover - backend specific
                logger.warning("Keyring read failed for %s, falling back to local secret store: %s", key, exc)
        return self.fallback_store.get(key)

    def set(self, key: str, value: str) -> None:
        if keyring is not None:
            try:
                keyring.set_password(self.service_name, key, value)
                self.fallback_store.delete(key)
                return
            except KeyringError as exc:  # pragma: no cover - backend specific
                logger.warning("Keyring write failed for %s, falling back to local secret store: %s", key, exc)
        self.fallback_store.set(key, value)

    def delete(self, key: str) -> None:
        if keyring is not None:
            try:
                keyring.delete_password(self.service_name, key)
            except PasswordDeleteError:
                pass
            except KeyringError as exc:  # pragma: no cover - backend specific
                logger.warning("Keyring delete failed for %s, falling back to local secret store cleanup: %s", key, exc)
        self.fallback_store.delete(key)
