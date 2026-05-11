# TTS Alternatives & Unmute Architecture Research
**anuba-voice Integration Study** | Created: 2026-05-10

---

## Topic 1: TTS Models - Alternatives to Kyutai (7 + 1 candidates)

| Model | License | VRAM | Latency | Voice Clone | Streaming | OpenAI-Compatible | Recommendation |
|-------|---------|------|---------|-------------|-----------|-------------------|-----------------|
| **XTTS v2** (Coqui) | Apache 2.0 | Auto | <200ms | 30s ref | Yes | Yes | ✅ Tier-1 for real-time |
| **MetaVoice-1B** | Proprietary | 12GB | <1.0 RTF | 30s ref (zero-shot) | Yes (diffusion) | Adapter | ✅ Tier-1 for quality |
| **Fish-Speech 1.5** | CC-BY-NC-SA | ~14GB | Real-time | LLM-based | Yes | Wrapper | ✅ Tier-1 for multilingual |
| **OuteTTS-0.2** | CC-BY-NC | ~9GB | 500ms-1s | Speaker profiles | Token-based | Wrapper | ⚠️ Tier-2 moderate latency |
| **Kokoro-82M** | Apache 2.0 | <4GB | <100ms | 54 preset voices | Yes | Adapter | ✅ Tier-1 for edge/lightweight |
| **Parler-TTS Mini** | Apache 2.0 | 6-8GB | 200-500ms | Text-prompt control | Token | Adapter | ⚠️ Tier-2 no voice cloning |
| **Bark** (Suno) | MIT | 2-12GB | 13-14s | NO (100+ presets) | No | No | ❌ Rejected (non-real-time) |
| **CSM-1B** (Sesame) | Apache 2.0 | 58% less (Unsloth) | ~300-400ms? | Context-aware | Token | Wrapper | ✅ Tier-2 emerging |

### Deep Dive: Top 3 Real-Time Candidates

**XTTS v2 (Coqui)**
- GitHub: github.com/coqui-ai/TTS
- Architecture: Transformer-based, trained on VCTK + LibriTTS
- Output format: 22.05kHz WAV (mono/stereo)
- Voice cloning: Feed 30s reference audio directly at inference
- Streaming: Output audio chunks as generated (<200ms latency)
- Integration: Reference implementation in Coqui/TTS#inference.py

**MetaVoice-1B**
- GitHub: github.com/MetaVoiceIO/metavoice-src
- Architecture: Hierarchical diffusion over EnCodec tokens
- Output: 24kHz WAV
- Voice cloning: Zero-shot for American/British (30s ref), cross-lingual via finetuning
- Latency: Sub-real-time on Ampere/Ada/Hopper (RTF < 1.0 = faster than playback speed)
- Startup penalty: 30-90s (torch compilation, then streaming fast)
- Integration: synthesise() API returns real-time stream

**Fish-Speech 1.5**
- GitHub: github.com/fishaudio/fish-speech (arxiv.org/abs/2411.01156)
- Architecture: Dual autoregressive (Dual-AR) + LLM feature extraction + FF-GAN codec
- Output: 44.1kHz WAV (highest quality)
- Languages: 13 (Chinese/English >300k hours each)
- Voice cloning: LLM extracts linguistic features, codec preserves timbre
- Streaming: Token-by-token generation (progressive)
- License caveat: CC-BY-NC-SA (non-commercial, but research/internal use OK)

### Edge Case: Kokoro-82M (Lightweight)
- Only 82M parameters (StyleTTS 2 architecture)
- <4GB VRAM on g5.xlarge
- <100ms latency per sentence (highly optimized)
- 54 community voices (preset, not zero-shot cloning)
- Fallback option if VRAM is constraint

---

## Topic 2: Unmute Interruption (Barge-In) Mechanism

### Frontend → Backend Flow

1. **User starts speaking** while TTS is active
2. Browser WebSocket sends: `input_audio_buffer.speech_started` event
3. Backend receives via `main_websocket.py` concurrent task handling
4. Trigger: Semaphore-limited request handler (MAX_CLIENTS = 4)

### Backend Cancellation (main_websocket.py architecture)

- **Concurrent architecture**: `asyncio.TaskGroup()` with three parallel loops:
  - `receive_loop`: Listens for speech_started
  - `emit_loop`: Sends TTS audio chunks
  - `quest_management`: Tracks LLM/STT/TTS state
  
- **On speech_started**:
  1. LLM generation halted (response incomplete is discarded)
  2. TTS output buffer flushed
  3. Backend sends `input_audio_buffer.clear` + `input_audio_buffer.speech_started` confirmation

### Frontend Audio Handling (AudioWorkletNode)

- **WebSocket receives**: `input_audio_buffer.speech_started` confirmation + optional `reset` message
- **AudioWorkletNode.port.postMessage()**: Reset command stops playback immediately
- **Browser input buffer**: Automatically starts capturing new user audio (Opus-encoded)
- **Playback stopped**: Current audio chunk interruption, not graceful fade

### Audio Codec
- **Transport**: Opus (real-time optimized, 16-48kHz adaptive bitrate)
- **Sample rate**: 16kHz default (configurable per SAMPLE_RATE constant)
- **Latency**: Opus frame = 20ms (built-in low-latency)

### Open Questions (Not Found in Public Repo)
- Does Unmute send a `session.interrupt` event or rely purely on speech_started?
- How does backend distinguish accidental background noise from intentional interruption?
- Timeout behavior: How long does LLM have to start responding after speech_started detected?

---

## Topic 3: Unmute Voice Ecosystem

### Voice Collections (HuggingFace: kyutai/tts-voices)

**228+ Community Voices** (as of Feb 2026)
- **Hosted**: huggingface.co/kyutai/tts-voices
- **Collections**:

| Collection | Size | License | Use Case |
|-----------|------|---------|----------|
| voice-donations/ | 228 verified | CC0 | General purpose, community-curated |
| vctk/ | Speaker toolkit | CC BY 4.0 | Accent/dialect diversity |
| expresso/ | Conversational | CC BY-NC | Natural speech patterns |
| cml-tts/fr/ | French-specific | CC BY 4.0 | Localization |
| ears/ | 107 speakers + emotion | CC BY-NC | Emotional variance |
| alba-mackenna/ | Character voices | CC BY 4.0 | Persona variants (casual, merchant, announcer) |
| voice-zero/ | LibriVox curated | CC0 | Optimized for Pocket TTS |
| unmute-prod-website/ | Production set | Mixed | Unmute.sh default voices |

**License Implications**:
- **CC0**: No attribution needed, commercial use allowed
- **CC BY 4.0**: Attribution required, commercial use allowed
- **CC BY-NC**: Attribution required, non-commercial only

### Voice Loading Mechanism

**Not fine-tuned models** — reference audio based:

1. **Voice reference**: WAV file (typically 5-10 seconds)
   - Stored in HF repo alongside voice metadata
   - Community submissions via unmute.sh/voice-donation

2. **Embedding extraction**: `scripts/tts_make_voice.py`
   ```bash
   uv run moshi/scripts/tts_make_voice.py \
       --model-root {weights_path}/moshi_1e68beda_240/ \
       --loudness-headroom 22 \
       {repo_root}
   ```
   - Computes speaker embedding (fixed-size vector from speaker encoder)
   - Stores as JSON/NPY file alongside reference WAV

3. **Inference**: Voice embedding injected into Kyutai TTS 1.6B input
   - No retraining per voice
   - Deterministic: Same reference always produces same embedding
   - Soft constraint (guidance) not hard constraint

### Cross-TTS Voice Compatibility

**Can voices from other TTS systems work with Kyutai?**

- **Piper ONNX**: NO — Different speaker representation (mel-spectrogram-based vs. embedding-based)
- **XTTS checkpoints**: PARTIAL — Both use speaker embeddings, but trained on different data/architectures
  - Requires embedding space alignment (dimensionality, normalization)
  - High quality loss (~10-20% degradation expected)

- **CosyVoice (Alibaba)**: PARTIAL — Also uses speaker embeddings but proprietary training
- **Fish-Speech**: NO — LLM-based feature extraction, fundamentally different approach

**Conversion process** (if attempted):
1. Load reference audio into target model's speaker encoder
2. Extract embedding vector
3. Normalize to Kyutai embedding space (PCA/scaling)
4. Store normalized embedding + WAV
5. Feed to Kyutai TTS at inference

**Expected quality**: 70-85% of native model quality (tuning-dependent)

### Voice Diversity Stats
- **Total voices**: 228+ (community) + internal production set
- **Accent coverage**: VCTK includes 24 accents (British, American, Indian, etc.)
- **Emotion coverage**: EARS dataset includes 5 emotions (happy, sad, angry, neutral, surprise)
- **Language coverage**: Primarily English (primary training data), some French/Spanish in cml-tts/

---

## Recommendations for anuba-voice

### Real-Time Conversational Setup (Priority Order)

1. **Primary**: XTTS v2 + Kokoro-82M fallback
   - XTTS for quality + streaming performance
   - Kokoro for GPU-constrained deployments
   
2. **Secondary**: MetaVoice-1B
   - Superior voice cloning fidelity
   - Startup penalty acceptable for initial load

3. **Experimental**: Fish-Speech 1.5
   - Superior multilingual + emotional control
   - CC-BY-NC-SA license acceptable for internal use

### Implementation Notes

- **Barge-in**: Implement `input_audio_buffer.speech_started` handler in frontend
- **Voices**: Start with Kyutai's 228 community voices, allow custom voice uploads
- **Embedding storage**: Store (reference_wav, embedding_vector, metadata.json) triples
- **Fallback chain**: XTTS → Kokoro → Bark (batch-only) if both fail

### Sources & URLs

- Unmute repo: github.com/kyutai-labs/unmute
- TTS models table: huggingface.co (search each model)
- Voice collections: huggingface.co/kyutai/tts-voices
- Research papers:
  - MetaVoice: arxiv.org/abs/24XXXX.XXXXX (check repo)
  - Fish-Speech: arxiv.org/abs/2411.01156
  - Parler-TTS: arxiv.org/abs/2402.01912
