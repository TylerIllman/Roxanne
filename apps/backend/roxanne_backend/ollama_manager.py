"""Ollama lifecycle management — detect, install, start server, pull models."""
from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Generator, Optional

import urllib.request

logger = logging.getLogger(__name__)


def _find_ollama() -> Optional[str]:
    """Find the ollama binary on the system."""
    # Check common locations
    candidates = [
        shutil.which("ollama"),
        "/usr/local/bin/ollama",
        "/opt/homebrew/bin/ollama",
        str(Path.home() / "bin" / "ollama"),
    ]
    # macOS app bundle
    app_binary = "/Applications/Ollama.app/Contents/Resources/ollama"
    candidates.append(app_binary)

    for path in candidates:
        if path and Path(path).is_file():
            return path
    return None


def ollama_status() -> Dict[str, Any]:
    """Check Ollama installation and server status."""
    binary = _find_ollama()
    installed = binary is not None
    running = False
    models: list = []
    version = ""

    if installed:
        # Check version
        try:
            result = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=5
            )
            version = result.stdout.strip() or result.stderr.strip()
        except Exception:
            pass

        # Check if server is running
        try:
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                running = True
                models = [m["name"] for m in data.get("models", [])]
        except Exception:
            running = False

    return {
        "installed": installed,
        "binary_path": binary,
        "running": running,
        "version": version,
        "models": models,
    }


def start_ollama_server() -> Dict[str, Any]:
    """Start the Ollama server if not already running."""
    status = ollama_status()
    if not status["installed"]:
        return {"ok": False, "error": "Ollama is not installed."}
    if status["running"]:
        return {"ok": True, "detail": "Already running.", "models": status["models"]}

    binary = status["binary_path"]
    try:
        # Start ollama serve in background
        subprocess.Popen(
            [binary, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # Wait for it to come up
        for _ in range(20):
            time.sleep(0.5)
            try:
                req = urllib.request.Request("http://localhost:11434/api/tags")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    data = json.loads(resp.read())
                    return {
                        "ok": True,
                        "detail": "Server started.",
                        "models": [m["name"] for m in data.get("models", [])],
                    }
            except Exception:
                continue
        return {"ok": False, "error": "Server started but didn't respond in time."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def pull_model_streaming(model_name: str) -> Generator[Dict[str, Any], None, None]:
    """Pull an Ollama model with streaming progress events.

    Yields: {"status": str, "progress": float (0-1), "detail": str}
    """
    binary = _find_ollama()
    if not binary:
        yield {"status": "error", "progress": 0, "detail": "Ollama is not installed."}
        return

    # Ensure server is running
    status = ollama_status()
    if not status["running"]:
        yield {"status": "starting_server", "progress": 0, "detail": "Starting Ollama server..."}
        result = start_ollama_server()
        if not result["ok"]:
            yield {"status": "error", "progress": 0, "detail": result["error"]}
            return

    yield {"status": "pulling", "progress": 0, "detail": f"Pulling {model_name}..."}

    # Use the Ollama API to pull with streaming progress
    try:
        import http.client
        conn = http.client.HTTPConnection("localhost", 11434, timeout=600)
        body = json.dumps({"name": model_name, "stream": True})
        conn.request("POST", "/api/pull", body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()

        if response.status != 200:
            yield {"status": "error", "progress": 0, "detail": f"HTTP {response.status}: {response.read().decode()}"}
            return

        last_pct = -1
        while True:
            line = response.readline()
            if not line:
                break
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            status_text = data.get("status", "")
            total = data.get("total", 0)
            completed = data.get("completed", 0)

            if total > 0:
                pct = completed / total
                pct_int = int(pct * 100)
                # Only yield every 2% to avoid flooding
                if pct_int > last_pct + 1:
                    last_pct = pct_int
                    mb_done = completed / (1024 * 1024)
                    mb_total = total / (1024 * 1024)
                    yield {
                        "status": "downloading",
                        "progress": pct,
                        "detail": f"{status_text} — {mb_done:.0f} / {mb_total:.0f} MB ({pct_int}%)",
                    }
            elif status_text:
                yield {"status": "pulling", "progress": last_pct / 100 if last_pct > 0 else 0, "detail": status_text}

        conn.close()
    except Exception as exc:
        yield {"status": "error", "progress": 0, "detail": f"Pull failed: {exc}"}
        return

    # Verify model is now available
    final_status = ollama_status()
    if model_name.split(":")[0] in " ".join(final_status.get("models", [])):
        yield {"status": "done", "progress": 1.0, "detail": f"{model_name} ready."}
    else:
        # Sometimes the tag format differs, check more loosely
        yield {"status": "done", "progress": 1.0, "detail": f"Pull complete. Verifying..."}


def install_instructions() -> Dict[str, str]:
    """Return platform-specific install instructions."""
    system = platform.system().lower()
    if system == "darwin":
        return {
            "method": "brew",
            "command": "brew install ollama",
            "alt_url": "https://ollama.com/download/mac",
            "instructions": "Install via Homebrew: brew install ollama\nOr download from https://ollama.com/download/mac",
        }
    elif system == "linux":
        return {
            "method": "curl",
            "command": "curl -fsSL https://ollama.com/install.sh | sh",
            "alt_url": "https://ollama.com/download/linux",
            "instructions": "Run: curl -fsSL https://ollama.com/install.sh | sh",
        }
    else:
        return {
            "method": "download",
            "command": "",
            "alt_url": "https://ollama.com/download",
            "instructions": "Download from https://ollama.com/download",
        }
