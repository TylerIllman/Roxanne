from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path
from typing import Any, Dict, Optional


def default_app_home() -> Path:
    configured = os.getenv("ROXANNE_HOME")
    if configured:
        return Path(configured).expanduser()

    home = Path.home()
    system = platform.system().lower()
    if system == "darwin":
        return home / "Library" / "Application Support" / "RoxanneAssistant"
    if system == "windows":
        return home / "AppData" / "Roaming" / "RoxanneAssistant"
    return home / ".roxanne-assistant"


class AppPaths:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or default_app_home()
        self.config_path = self.root / "config.json"
        self.index_path = self.root / "indexes"
        self.audio_path = self.root / "audio"
        self.logs_path = self.root / "logs"

    def ensure(self) -> None:
        for path in [self.root, self.index_path, self.audio_path, self.logs_path]:
            path.mkdir(parents=True, exist_ok=True)
            restrict_permissions(path, directory=True)

    def prune_audio_files(self, max_age_seconds: int = 60 * 60 * 24) -> int:
        if not self.audio_path.exists():
            return 0

        removed = 0
        cutoff = time.time() - max_age_seconds
        for file_path in self.audio_path.iterdir():
            if not file_path.is_file():
                continue
            try:
                if file_path.stat().st_mtime < cutoff:
                    file_path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    restrict_permissions(path.parent, directory=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    restrict_permissions(temp_path, directory=False)
    temp_path.replace(path)
    restrict_permissions(path, directory=False)


def restrict_permissions(path: Path, directory: bool) -> None:
    if os.name == "nt":
        return
    mode = 0o700 if directory else 0o600
    try:
        os.chmod(path, mode)
    except OSError:
        pass
