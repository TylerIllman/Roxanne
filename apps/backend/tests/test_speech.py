"""Tests for SpeechService — status, model listing, voice management.

All tests use Python interfaces only (no binaries).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from roxanne_backend.speech import SpeechService, _VOSK_MODELS, _VOICE_MODELS
from roxanne_backend.storage import AppPaths


@pytest.fixture
def speech_service(app_paths: AppPaths) -> SpeechService:
    return SpeechService(app_paths)


class TestSpeechStatus:
    def test_status_structure(self, speech_service: SpeechService):
        status = speech_service.speech_status()
        assert "vosk_ready" in status
        assert "piper_installed" in status
        assert "voice_installed" in status
        assert "ready" in status
        assert isinstance(status["ready"], bool)

    def test_status_backward_compat(self, speech_service: SpeechService):
        """whisper_ready key maintained for frontend compat."""
        status = speech_service.speech_status()
        assert "whisper_ready" in status
        assert status["whisper_ready"] == status["vosk_ready"]


class TestSTTModels:
    def test_list_stt_models(self, speech_service: SpeechService):
        result = speech_service.list_stt_models()
        assert "models" in result
        models = result["models"]
        assert len(models) == len(_VOSK_MODELS)

    def test_stt_model_structure(self, speech_service: SpeechService):
        result = speech_service.list_stt_models()
        for model in result["models"]:
            assert "id" in model
            assert "label" in model
            assert "size_mb" in model
            assert "lang" in model
            assert "installed" in model
            assert isinstance(model["installed"], bool)

    def test_stt_model_ids_match_registry(self, speech_service: SpeechService):
        result = speech_service.list_stt_models()
        ids = {m["id"] for m in result["models"]}
        assert ids == set(_VOSK_MODELS.keys())

    def test_download_unknown_model(self, speech_service: SpeechService):
        events = list(speech_service.download_stt_model("nonexistent-model"))
        assert len(events) == 1
        assert events[0]["status"] == "error"


class TestVoiceModels:
    def test_list_voices(self, speech_service: SpeechService):
        result = speech_service.list_voices()
        assert "voices" in result
        voices = result["voices"]
        assert len(voices) == len(_VOICE_MODELS)

    def test_voice_structure(self, speech_service: SpeechService):
        result = speech_service.list_voices()
        for voice in result["voices"]:
            assert "id" in voice
            assert "label" in voice
            assert "installed" in voice


class TestVoskModelDir:
    def test_vosk_model_dir_for_default(self, speech_service: SpeechService):
        path = speech_service._vosk_model_dir_for("vosk-model-small-en-us-0.15")
        assert "vosk-model-small-en-us-0.15" in str(path)

    def test_vosk_model_dir_for_custom(self, speech_service: SpeechService):
        path = speech_service._vosk_model_dir_for("vosk-model-en-us-0.22")
        assert "vosk-model-en-us-0.22" in str(path)

    def test_vosk_not_installed_by_default(self, speech_service: SpeechService):
        assert speech_service._vosk_installed("nonexistent-model") is False


class TestSpeechServiceProperties:
    def test_speech_dir(self, speech_service: SpeechService, app_paths: AppPaths):
        assert speech_service.speech_dir == app_paths.root / "speech"

    def test_voice_model_path(self, speech_service: SpeechService):
        path = speech_service.voice_model_path
        assert path.name == "en_US-amy-medium.onnx"

    def test_voice_config_path(self, speech_service: SpeechService):
        path = speech_service.voice_config_path
        assert path.name == "en_US-amy-medium.onnx.json"
