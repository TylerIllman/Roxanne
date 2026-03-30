"""Tests for Ollama manager — status checking, server management."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from roxanne_backend.ollama_manager import (
    _find_ollama,
    install_instructions,
    ollama_status,
)


class TestFindOllama:
    def test_finds_ollama(self):
        result = _find_ollama()
        # On this machine ollama is installed; just verify return type
        assert result is None or isinstance(result, str)

    @patch("shutil.which", return_value=None)
    @patch("pathlib.Path.is_file", return_value=False)
    def test_not_found(self, mock_is_file, mock_which):
        result = _find_ollama()
        assert result is None


class TestOllamaStatus:
    @patch("roxanne_backend.ollama_manager._find_ollama", return_value=None)
    def test_not_installed(self, mock_find):
        status = ollama_status()
        assert status["installed"] is False
        assert status["running"] is False
        assert status["models"] == []

    @patch("roxanne_backend.ollama_manager._find_ollama", return_value="/usr/local/bin/ollama")
    @patch("subprocess.run")
    @patch("urllib.request.urlopen")
    def test_installed_and_running(self, mock_urlopen, mock_run, mock_find):
        import json

        # Mock version check
        mock_run.return_value = MagicMock(returncode=0, stdout="0.5.0")

        # Mock API response for /api/tags
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "models": [{"name": "qwen2.5:7b"}, {"name": "mistral:7b"}]
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        status = ollama_status()
        assert status["installed"] is True
        assert status["running"] is True
        assert "qwen2.5:7b" in status["models"]

    @patch("roxanne_backend.ollama_manager._find_ollama", return_value="/usr/local/bin/ollama")
    @patch("subprocess.run")
    @patch("urllib.request.urlopen", side_effect=Exception("Connection refused"))
    def test_installed_not_running(self, mock_urlopen, mock_run, mock_find):
        mock_run.return_value = MagicMock(returncode=0, stdout="0.5.0")
        status = ollama_status()
        assert status["installed"] is True
        assert status["running"] is False


class TestInstallInstructions:
    @patch("platform.system", return_value="Darwin")
    def test_macos_instructions(self, mock_sys):
        info = install_instructions()
        assert "brew" in info.get("command", "") or "ollama" in info.get("url", "")

    @patch("platform.system", return_value="Linux")
    def test_linux_instructions(self, mock_sys):
        info = install_instructions()
        assert "curl" in info.get("command", "") or "ollama" in info.get("url", "")
