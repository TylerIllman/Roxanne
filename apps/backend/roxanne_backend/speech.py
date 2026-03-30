from __future__ import annotations

import io
import json
import logging
import platform
import ssl
import subprocess
import tempfile
import urllib.request
import wave
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

import certifi

from roxanne_backend.models import AppConfig
from roxanne_backend.storage import AppPaths, restrict_permissions

logger = logging.getLogger(__name__)

# ── Vosk STT model config ─────────────────────────────────────────
_VOSK_MODELS = {
    "vosk-model-small-en-us-0.15": {
        "label": "English Small (40 MB)",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "size_mb": 40,
        "lang": "en",
    },
    "vosk-model-en-us-0.22": {
        "label": "English Large (1.8 GB) — best accuracy",
        "url": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip",
        "size_mb": 1800,
        "lang": "en",
    },
    "vosk-model-en-us-0.22-lgraph": {
        "label": "English Medium (128 MB) — good balance",
        "url": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip",
        "size_mb": 128,
        "lang": "en",
    },
    "vosk-model-small-en-us-0.15-phone": {
        "label": "English Small Optimized (40 MB) — phone/mic",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "size_mb": 40,
        "lang": "en",
    },
    "vosk-model-en-us-0.42-gigaspeech": {
        "label": "English GigaSpeech (2.3 GB) — highest accuracy",
        "url": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.42-gigaspeech.zip",
        "size_mb": 2300,
        "lang": "en",
    },
}

# Default model
_VOSK_DEFAULT_MODEL = "vosk-model-small-en-us-0.15"
_VOSK_MODEL_NAME = _VOSK_DEFAULT_MODEL
_VOSK_MODEL_URL = _VOSK_MODELS[_VOSK_DEFAULT_MODEL]["url"]


_VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx"
_VOICE_CONFIG_URL = f"{_VOICE_URL}.json"


def _ssl_context() -> ssl.SSLContext:
    """Build an SSL context using certifi's CA bundle (fixes macOS Python)."""
    return ssl.create_default_context(cafile=certifi.where())


def _download(url: str, dest: Path, on_progress=None) -> None:
    """Download a URL to a local path using certifi SSL with optional progress callback.

    on_progress(downloaded_bytes, total_bytes) is called periodically.
    total_bytes may be 0 if Content-Length is not available.
    Writes directly to disk to avoid holding everything in memory.
    """
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, context=_ssl_context()) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 128 * 1024  # 128KB chunks for faster throughput
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)


def _platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        machine = "arm64"
    elif machine in ("x86_64", "amd64"):
        machine = "x86_64"
    return f"{system}_{machine}"


_VOICE_MODELS = {
    "en_US-amy-medium": {
        "label": "Amy (US, medium)",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json",
    },
    "en_US-lessac-high": {
        "label": "Lessac (US, high quality)",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/high/en_US-lessac-high.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/high/en_US-lessac-high.onnx.json",
    },
    "en_US-lessac-medium": {
        "label": "Lessac (US, medium)",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    },
    "en_GB-alba-medium": {
        "label": "Alba (UK, medium)",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx.json",
    },
    "en_US-ryan-high": {
        "label": "Ryan (US, high quality, male)",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json",
    },
    "en_US-libritts_r-medium": {
        "label": "LibriTTS-R (US, medium, multi-speaker)",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/libritts_r/medium/en_US-libritts_r-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/libritts_r/medium/en_US-libritts_r-medium.onnx.json",
    },
}


class SpeechService:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self._vosk_model = None
        self._vosk_model_name: Optional[str] = None  # track which model is loaded
        self._piper_voice = None  # cached PiperVoice instance
        self._piper_voice_model = None  # path of currently loaded model

    @property
    def speech_dir(self) -> Path:
        return self.paths.root / "speech"

    @property
    def voice_model_path(self) -> Path:
        return self.speech_dir / "voices" / "en_US-amy-medium.onnx"

    @property
    def voice_config_path(self) -> Path:
        return self.speech_dir / "voices" / "en_US-amy-medium.onnx.json"

    def _vosk_model_dir_for(self, model_name: str) -> Path:
        """Return the directory for a specific Vosk model, checking standard cache dirs."""
        try:
            from vosk import MODEL_DIRS
            for d in MODEL_DIRS:
                if d is not None:
                    p = Path(d) / model_name
                    if p.exists():
                        return p
        except ImportError:
            pass
        return Path.home() / ".cache" / "vosk" / model_name

    @property
    def vosk_model_dir(self) -> Path:
        """Check standard vosk cache dirs for the default model."""
        return self._vosk_model_dir_for(_VOSK_MODEL_NAME)

    def _vosk_installed(self, model_name: Optional[str] = None) -> bool:
        name = model_name or _VOSK_MODEL_NAME
        return self._vosk_model_dir_for(name).exists()

    # ── Status / setup ──────────────────────────────────────────

    def speech_status(self) -> Dict[str, Any]:
        """Check what speech components are installed locally."""
        vosk_ready = self._vosk_installed()

        # Check for piper-tts Python package (no binary needed)
        try:
            import piper  # noqa: F401
            piper_installed = True
        except ImportError:
            piper_installed = False

        # Check if any voice model is installed
        voices_dir = self.speech_dir / "voices"
        voice_installed = any(voices_dir.glob("*.onnx")) if voices_dir.exists() else False

        return {
            "whisper_ready": vosk_ready,  # Keep key name for frontend compat
            "vosk_ready": vosk_ready,
            "piper_installed": piper_installed,
            "voice_installed": voice_installed,
            "piper_supported": True,  # Python package works on all platforms
            "ready": vosk_ready and piper_installed and voice_installed,
        }

    def list_stt_models(self) -> Dict[str, Any]:
        """List available STT models with install status."""
        models = []
        for model_id, info in _VOSK_MODELS.items():
            models.append({
                "id": model_id,
                "label": info["label"],
                "size_mb": info["size_mb"],
                "lang": info["lang"],
                "installed": self._vosk_installed(model_id),
            })
        return {"models": models}

    def download_stt_model(self, model_id: str):
        """Download a Vosk STT model. Generator yielding progress events."""
        if model_id not in _VOSK_MODELS:
            yield {"status": "error", "progress": 0, "detail": f"Unknown model: {model_id}"}
            return

        info = _VOSK_MODELS[model_id]
        cache_dir = Path.home() / ".cache" / "vosk"
        cache_dir.mkdir(parents=True, exist_ok=True)
        model_dir = cache_dir / model_id
        zip_path = cache_dir / f"{model_id}.zip"

        if model_dir.exists():
            yield {"status": "done", "progress": 1.0, "detail": f"{model_id} already installed."}
            return

        yield {"status": "downloading", "progress": 0, "detail": f"Downloading {info['label']}…"}
        try:
            for ev in self._download_with_events(info["url"], zip_path, "stt", 0.0, 0.85):
                yield ev

            yield {"status": "extracting", "progress": 0.9, "detail": "Extracting model…"}
            import zipfile
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                zf.extractall(str(cache_dir))
            zip_path.unlink(missing_ok=True)

            if model_dir.exists():
                yield {"status": "done", "progress": 1.0, "detail": f"{model_id} installed."}
            else:
                yield {"status": "done", "progress": 1.0, "detail": "Extracted — model ready."}
        except Exception as exc:
            zip_path.unlink(missing_ok=True)
            yield {"status": "error", "progress": 0, "detail": f"Download failed: {exc}"}

    def _download_with_events(self, url: str, dest: Path, step_name: str, step_base: float, step_weight: float):
        """Download a file and yield progress events during the download."""
        req = urllib.request.Request(url)
        ctx = _ssl_context()
        with urllib.request.urlopen(req, context=ctx) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 128 * 1024
            last_report_mb = -1
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    mb_done = downloaded / (1024 * 1024)
                    mb_total = total / (1024 * 1024) if total else 0
                    if int(mb_done * 2) > last_report_mb:
                        last_report_mb = int(mb_done * 2)
                        pct = downloaded / total if total else 0
                        detail = f"{mb_done:.1f} / {mb_total:.1f} MB" if mb_total else f"{mb_done:.1f} MB"
                        print(f"[speech-setup]   {step_name}: {detail} ({pct*100:.0f}%)", flush=True)
                        yield {
                            "step": step_name,
                            "status": "downloading",
                            "progress": step_base + step_weight * pct,
                            "detail": detail,
                        }

    def _piper_package_installed(self) -> bool:
        """Check if piper-tts Python package is installed."""
        try:
            import piper  # noqa: F401
            return True
        except ImportError:
            return False

    def setup_speech_streaming(self):
        """Generator that yields NDJSON progress events while installing speech components."""
        def log(msg: str):
            print(f"[speech-setup] {msg}", flush=True)

        steps = []
        if not self._vosk_installed():
            steps.append("vosk")
        if not self._piper_package_installed():
            steps.append("piper")
        voices_dir = self.speech_dir / "voices"
        has_voice = voices_dir.exists() and any(voices_dir.glob("*.onnx"))
        if not has_voice:
            steps.append("voice")

        log(f"Steps needed: {steps or 'none (all installed)'}")

        if not steps:
            yield {"step": "done", "status": "ready", "progress": 1.0, "detail": "All components already installed."}
            return

        total_steps = len(steps)
        completed = 0

        # ── Vosk (manual download with progress) ──
        if "vosk" in steps:
            base = completed / total_steps
            weight = 1.0 / total_steps
            log(f"Downloading Vosk model from {_VOSK_MODEL_URL}")
            yield {"step": "vosk", "status": "starting", "progress": base, "detail": "Downloading Vosk STT model (~40 MB)..."}
            cache_dir = Path.home() / ".cache" / "vosk"
            cache_dir.mkdir(parents=True, exist_ok=True)
            model_dir = cache_dir / _VOSK_MODEL_NAME
            zip_path = cache_dir / f"{_VOSK_MODEL_NAME}.zip"
            try:
                yield from self._download_with_events(_VOSK_MODEL_URL, zip_path, "vosk", base, weight * 0.85)
                log("Vosk download complete. Extracting...")
                yield {"step": "vosk", "status": "extracting", "progress": base + weight * 0.9, "detail": "Extracting model..."}
                import zipfile
                with zipfile.ZipFile(str(zip_path), "r") as zf:
                    zf.extractall(str(cache_dir))
                zip_path.unlink(missing_ok=True)
                from vosk import Model, SetLogLevel
                SetLogLevel(-1)
                self._vosk_model = Model(str(model_dir))
                completed += 1
                log("Vosk model ready.")
                yield {"step": "vosk", "status": "done", "progress": completed / total_steps, "detail": "Vosk STT installed."}
            except Exception as exc:
                log(f"ERROR installing Vosk: {exc}")
                zip_path.unlink(missing_ok=True)
                yield {"step": "vosk", "status": "error", "progress": base, "detail": f"Error: {exc}"}

        # ── Piper (Python package — no binary needed) ──
        if "piper" in steps:
            base = completed / total_steps
            weight = 1.0 / total_steps
            log("piper-tts Python package not found — attempting pip install")
            yield {"step": "piper", "status": "starting", "progress": base, "detail": "Installing piper-tts Python package..."}
            try:
                import subprocess as _sp
                import sys
                result = _sp.run(
                    [sys.executable, "-m", "pip", "install", "piper-tts"],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0:
                    completed += 1
                    log("piper-tts installed.")
                    yield {"step": "piper", "status": "done", "progress": completed / total_steps, "detail": "piper-tts Python package installed."}
                else:
                    log(f"pip install piper-tts failed: {result.stderr}")
                    yield {"step": "piper", "status": "error", "progress": base, "detail": f"pip install failed: {result.stderr[:200]}"}
            except Exception as exc:
                log(f"ERROR installing piper-tts: {exc}")
                yield {"step": "piper", "status": "error", "progress": base, "detail": f"Error: {exc}"}

        # ── Voice model ──
        if "voice" in steps:
            base = completed / total_steps
            weight = 1.0 / total_steps
            log("Downloading default voice model...")
            yield {"step": "voice", "status": "starting", "progress": base, "detail": "Downloading voice model (~16 MB)..."}
            voices_dir = self.speech_dir / "voices"
            voices_dir.mkdir(parents=True, exist_ok=True)
            try:
                yield from self._download_with_events(_VOICE_URL, self.voice_model_path, "voice", base, weight * 0.9)
                _download(_VOICE_CONFIG_URL, self.voice_config_path)
                completed += 1
                log("Voice model installed.")
                yield {"step": "voice", "status": "done", "progress": completed / total_steps, "detail": "Voice model installed."}
            except Exception as exc:
                log(f"ERROR installing voice: {exc}")
                yield {"step": "voice", "status": "error", "progress": base, "detail": f"Error: {exc}"}

        piper_ok = self._piper_package_installed()
        voices_dir = self.speech_dir / "voices"
        voice_ok = voices_dir.exists() and any(voices_dir.glob("*.onnx"))
        is_ready = self._vosk_installed() and piper_ok and voice_ok
        log(f"Setup complete. Ready={is_ready}")
        yield {"step": "done", "status": "ready" if is_ready else "incomplete", "progress": 1.0, "detail": "All speech components ready!" if is_ready else "Some components failed."}

    def setup_speech(self) -> Dict[str, Any]:
        """Non-streaming fallback — runs all steps and returns final result."""
        last = None
        for event in self.setup_speech_streaming():
            last = event
        voices_dir = self.speech_dir / "voices"
        voice_ok = voices_dir.exists() and any(voices_dir.glob("*.onnx"))
        return {
            "vosk": "installed" if self.vosk_model_dir.exists() else "error",
            "piper": "installed" if self._piper_package_installed() else "error",
            "voice": "installed" if voice_ok else "error",
            "ready": last and last.get("status") == "ready",
        }

    # ── Vosk real-time STT ──────────────────────────────────────

    def get_vosk_model(self, config: Optional[AppConfig] = None):
        """Lazy-load the Vosk model. Uses stt_model from config if set."""
        model_name = _VOSK_DEFAULT_MODEL
        if config and config.speech.stt_model and config.speech.stt_model in _VOSK_MODELS:
            model_name = config.speech.stt_model

        # Reload if model changed
        if self._vosk_model is not None and self._vosk_model_name == model_name:
            return self._vosk_model

        import ssl as _ssl
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)

        model_dir = self._vosk_model_dir_for(model_name)
        if model_dir.exists():
            self._vosk_model = Model(str(model_dir))
            self._vosk_model_name = model_name
        elif self._vosk_installed():
            # Fallback to default if requested model not downloaded yet
            self._vosk_model = Model(str(self.vosk_model_dir))
            self._vosk_model_name = _VOSK_DEFAULT_MODEL
        else:
            # Auto-download default model
            _orig = _ssl._create_default_https_context
            _ssl._create_default_https_context = lambda: _ssl_context()
            try:
                self._vosk_model = Model(model_name=_VOSK_DEFAULT_MODEL)
                self._vosk_model_name = _VOSK_DEFAULT_MODEL
            finally:
                _ssl._create_default_https_context = _orig
        return self._vosk_model

    def create_recognizer(self, sample_rate: int = 16000, config: Optional[AppConfig] = None):
        """Create a new Vosk KaldiRecognizer for streaming audio."""
        from vosk import KaldiRecognizer
        model = self.get_vosk_model(config)
        rec = KaldiRecognizer(model, sample_rate)
        rec.SetWords(True)
        return rec

    def _convert_to_wav(self, audio_data: bytes) -> bytes:
        """Convert any audio format to 16kHz mono WAV using ffmpeg."""
        with tempfile.NamedTemporaryFile(suffix=".in", delete=False) as inf:
            inf.write(audio_data)
            in_path = inf.name
        out_path = in_path + ".wav"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", in_path, "-ar", "16000", "-ac", "1", "-f", "wav", out_path],
                capture_output=True,
                check=True,
                timeout=30,
            )
            return Path(out_path).read_bytes()
        finally:
            Path(in_path).unlink(missing_ok=True)
            Path(out_path).unlink(missing_ok=True)

    def transcribe_bytes(self, audio_data: bytes, config: AppConfig) -> str:
        """Transcribe audio bytes (any format) using Vosk.

        Handles WAV, webm, ogg, mp3, etc. by converting to WAV via ffmpeg if needed.
        """
        rec = self.create_recognizer(16000)

        # Try to parse as WAV first (fast path)
        try:
            with io.BytesIO(audio_data) as buf:
                with wave.open(buf, "rb") as wf:
                    sample_rate = wf.getframerate()
                    rec = self.create_recognizer(sample_rate)
                    while True:
                        data = wf.readframes(4000)
                        if len(data) == 0:
                            break
                        rec.AcceptWaveform(data)
                    result = json.loads(rec.FinalResult())
                    return result.get("text", "").strip()
        except Exception:
            pass

        # Not a WAV — convert using ffmpeg
        try:
            wav_data = self._convert_to_wav(audio_data)
            rec = self.create_recognizer(16000)
            with io.BytesIO(wav_data) as buf:
                with wave.open(buf, "rb") as wf:
                    while True:
                        data = wf.readframes(4000)
                        if len(data) == 0:
                            break
                        rec.AcceptWaveform(data)
            result = json.loads(rec.FinalResult())
            return result.get("text", "").strip()
        except FileNotFoundError:
            raise RuntimeError(
                "ffmpeg is required for non-WAV audio transcription. "
                "Install it with: brew install ffmpeg"
            )
        except Exception as exc:
            raise RuntimeError(f"Audio conversion failed: {exc}")

    # ── Piper TTS ───────────────────────────────────────────────

    def _get_piper_voice(self, voice_model: str):
        """Get or cache the PiperVoice instance.

        If the model file is corrupted (e.g. incomplete download), deletes it
        and falls back to any other installed voice.
        """
        from piper import PiperVoice
        if self._piper_voice is None or self._piper_voice_model != voice_model:
            try:
                self._piper_voice = PiperVoice.load(voice_model)
                self._piper_voice_model = voice_model
            except Exception as exc:
                logger.warning(f"Failed to load voice model {voice_model}: {exc}")
                # Delete corrupted model so it can be re-downloaded
                model_path = Path(voice_model)
                if model_path.exists():
                    logger.info(f"Deleting corrupted voice model: {model_path}")
                    model_path.unlink(missing_ok=True)
                    # Also delete config
                    config_path = model_path.with_suffix(model_path.suffix + ".json")
                    config_path.unlink(missing_ok=True)
                # Try to fall back to any other installed voice
                voices_dir = self.speech_dir / "voices"
                if voices_dir.exists():
                    for onnx in voices_dir.glob("*.onnx"):
                        if str(onnx) != voice_model:
                            try:
                                self._piper_voice = PiperVoice.load(str(onnx))
                                self._piper_voice_model = str(onnx)
                                logger.info(f"Fell back to voice model: {onnx.stem}")
                                return self._piper_voice
                            except Exception:
                                continue
                raise RuntimeError(
                    f"Voice model is corrupted and no fallback available. "
                    f"Please re-download the voice from Settings. Error: {exc}"
                )
        return self._piper_voice

    def _resolve_voice_model(self, config: AppConfig) -> str:
        """Resolve the voice model path from config or defaults."""
        if config.speech.piper_voice_model_path:
            return config.speech.piper_voice_model_path
        # Try voice_id from config
        voice_id = getattr(config.speech, "voice_id", "en_US-amy-medium") or "en_US-amy-medium"
        voices_dir = self.speech_dir / "voices"
        candidate = voices_dir / f"{voice_id}.onnx"
        if candidate.exists():
            return str(candidate)
        # Fallback: any installed voice model
        if voices_dir.exists():
            for onnx in voices_dir.glob("*.onnx"):
                return str(onnx)
        raise ValueError(
            "No voice model found. Run speech setup from settings."
        )

    def synthesize(self, text: str, config: AppConfig) -> str:
        voice_model = self._resolve_voice_model(config)

        self.paths.ensure()
        output_path = self.paths.audio_path / f"{uuid4().hex}.wav"

        try:
            from piper.config import SynthesisConfig
            import wave

            voice = self._get_piper_voice(voice_model)

            # Speed: length_scale < 1.0 = faster. Default 1.0.
            speed = getattr(config.speech, "speed", 1.0) or 1.0
            length_scale = 1.0 / speed  # speed=1.2 → length_scale=0.83 (faster)
            syn_config = SynthesisConfig(length_scale=length_scale)

            chunks = list(voice.synthesize(text, syn_config=syn_config))
            if not chunks:
                raise RuntimeError("Piper produced no audio output.")

            sample_rate = chunks[0].sample_rate
            with wave.open(str(output_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                for chunk in chunks:
                    wav_file.writeframes(chunk.audio_int16_bytes)
        except ImportError:
            raise RuntimeError(
                "piper-tts Python package is not installed. "
                "Run: pip install piper-tts"
            )

        restrict_permissions(output_path, directory=False)
        self.paths.prune_audio_files()
        return str(output_path)

    def list_voices(self) -> Dict[str, Any]:
        """List available and installed voice models."""
        voices_dir = self.speech_dir / "voices"
        installed = set()
        if voices_dir.exists():
            for onnx in voices_dir.glob("*.onnx"):
                installed.add(onnx.stem)

        result = []
        for key, info in _VOICE_MODELS.items():
            result.append({
                "id": key,
                "label": info["label"],
                "installed": key in installed,
            })
        return {"voices": result, "installed": sorted(installed)}

    def download_voice(self, voice_id: str) -> str:
        """Download a voice model by its ID."""
        if voice_id not in _VOICE_MODELS:
            raise ValueError(f"Unknown voice model: {voice_id}")

        info = _VOICE_MODELS[voice_id]
        voices_dir = self.speech_dir / "voices"
        voices_dir.mkdir(parents=True, exist_ok=True)

        model_path = voices_dir / f"{voice_id}.onnx"
        config_path = voices_dir / f"{voice_id}.onnx.json"

        # Always re-download if model exists but is potentially corrupted (< 1MB)
        if model_path.exists() and model_path.stat().st_size < 1_000_000:
            logger.warning(f"Voice model {voice_id} seems too small ({model_path.stat().st_size} bytes), re-downloading")
            model_path.unlink(missing_ok=True)
            config_path.unlink(missing_ok=True)

        if not model_path.exists():
            logger.info(f"Downloading voice model: {voice_id}")
            _download(info["url"], model_path)
        if not config_path.exists():
            logger.info(f"Downloading voice config: {voice_id}")
            _download(info["config_url"], config_path)

        # Invalidate cached voice so next synthesize loads the new one
        self._piper_voice = None
        self._piper_voice_model = None

        return str(model_path)
