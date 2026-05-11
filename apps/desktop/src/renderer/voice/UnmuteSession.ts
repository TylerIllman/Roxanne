// WebSocket + audio client for Kyutai Unmute realtime sessions.
//
// Speaks the OpenAI Realtime-style protocol that Unmute uses
// (see: kyutai-labs/unmute docs/browser_backend_communication.md).
//
// Two modes:
//   - { enableAudio: false } — protocol-only. Used by the "Test Unmute
//     connection" button to verify reachability without touching the mic.
//   - { enableAudio: true }  — full voice agent. Captures mic at 24 kHz mono
//     via opus-recorder, streams Opus packets as input_audio_buffer.append,
//     decodes incoming response.audio.delta packets in a Web Worker, and
//     plays the resulting PCM through an AudioWorkletNode.
//
// The audio pipeline mirrors the upstream Unmute frontend so we behave
// exactly like their reference client. Required static assets (must be
// served from the renderer root):
//
//   /encoderWorker.min.js          (from opus-recorder package)
//   /decoderWorker.min.js          (from opus-recorder package)
//   /decoderWorker.min.wasm        (from opus-recorder package)
//   /audio-output-processor.js     (custom AudioWorkletProcessor — verbatim from Unmute)

import OpusRecorder from "opus-recorder";

export type UnmuteServerEvent =
  | { type: "session.updated"; session?: unknown }
  | { type: "conversation.item.input_audio_transcription.delta"; delta?: string }
  | { type: "response.audio.delta"; delta?: string }
  | { type: "response.text.delta"; delta?: string }
  | { type: "response.created" }
  | { type: "input_audio_buffer.speech_started" }
  | { type: "input_audio_buffer.speech_stopped" }
  | { type: "error"; error?: { type: string; code?: string; message: string } }
  | { type: string; [k: string]: unknown };

export type UnmuteSessionOptions = {
  baseUrl: string;
  instructions: unknown;
  voice: string;
  allowRecording?: boolean;
  /** When true, set up mic capture + playback. Default false. */
  enableAudio?: boolean;
  onEvent?: (ev: UnmuteServerEvent) => void;
  onOpen?: () => void;
  onClose?: (ev: CloseEvent) => void;
  onError?: (ev: Event) => void;
};

type AudioPipeline = {
  audioContext: AudioContext;
  opusRecorder: OpusRecorder;
  decoder: Worker;
  outputWorklet: AudioWorkletNode;
  mediaStream: MediaStream;
};

function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function bytesToBase64(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

export class UnmuteSession {
  private ws: WebSocket | null = null;
  private audio: AudioPipeline | null = null;
  private opts: UnmuteSessionOptions;
  private closed = false;

  constructor(opts: UnmuteSessionOptions) {
    this.opts = opts;
  }

  static realtimeUrl(baseUrl: string): string {
    const trimmed = baseUrl.trim().replace(/\/+$/, "");
    if (!trimmed) throw new Error("Unmute baseUrl is empty");
    const url = new URL(trimmed);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = "/v1/realtime";
    return url.toString();
  }

  async start(): Promise<void> {
    if (this.ws) throw new Error("UnmuteSession already started");
    const wsUrl = UnmuteSession.realtimeUrl(this.opts.baseUrl);
    const ws = new WebSocket(wsUrl, "realtime");
    this.ws = ws;

    ws.addEventListener("message", (event) => {
      if (typeof event.data !== "string") return;
      let parsed: UnmuteServerEvent;
      try {
        parsed = JSON.parse(event.data) as UnmuteServerEvent;
      } catch {
        return;
      }
      // Hand audio deltas to the decoder before notifying caller — gives
      // the playback worklet a head start over any UI updates.
      if (parsed.type === "response.audio.delta" && this.audio) {
        const delta = (parsed as { delta?: string }).delta;
        if (delta) {
          try {
            this.audio.decoder.postMessage(base64ToBytes(delta));
          } catch (err) {
            console.warn("[UnmuteSession] decoder post failed", err);
          }
        }
      }
      this.opts.onEvent?.(parsed);
    });
    ws.addEventListener("close", (ev) => {
      this.ws = null;
      this.opts.onClose?.(ev);
    });
    ws.addEventListener("error", (ev) => {
      this.opts.onError?.(ev);
    });

    await new Promise<void>((resolve, reject) => {
      const onOpen = () => {
        ws.removeEventListener("error", onErr);
        this.opts.onOpen?.();
        resolve();
      };
      const onErr = (ev: Event) => {
        ws.removeEventListener("open", onOpen);
        reject(ev);
      };
      ws.addEventListener("open", onOpen, { once: true });
      ws.addEventListener("error", onErr, { once: true });
    });

    this.send({
      type: "session.update",
      session: {
        instructions: this.opts.instructions ?? null,
        voice: this.opts.voice,
        allow_recording: this.opts.allowRecording ?? false,
      },
    });

    if (this.opts.enableAudio) {
      try {
        await this.setupAudio();
      } catch (err) {
        // Tear down WS if audio setup fails — caller should close anyway.
        this.opts.onError?.(err as Event);
        throw err;
      }
    }
  }

  private async setupAudio(): Promise<void> {
    if (this.audio || this.closed) return;

    // Resolve worker / worklet asset URLs against document.baseURI so the
    // same code works whether the renderer is loaded from http://localhost
    // (dev) or file:// inside the packaged Electron app.
    const assetUrl = (rel: string) => new URL(rel, document.baseURI).href;
    const ENCODER_URL = assetUrl("encoderWorker.min.js");
    const DECODER_URL = assetUrl("decoderWorker.min.js");
    const WORKLET_URL = assetUrl("audio-output-processor.js");

    // Mic capture
    const mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: false,
        autoGainControl: true,
        channelCount: 1,
      },
    });

    const audioContext = new AudioContext();
    await audioContext.audioWorklet.addModule(WORKLET_URL);
    const outputWorklet = new AudioWorkletNode(audioContext, "audio-output-processor");
    outputWorklet.connect(audioContext.destination);

    // Opus decoder for response.audio.delta — output goes to the worklet.
    const decoder = new Worker(DECODER_URL);
    let micDuration = 0;
    decoder.onmessage = (event: MessageEvent) => {
      if (!event.data) return;
      const frame = (event.data as Float32Array[])[0];
      if (!frame) return;
      outputWorklet.port.postMessage({ frame, type: "audio", micDuration });
    };
    decoder.postMessage({
      command: "init",
      bufferLength: (960 * audioContext.sampleRate) / 24000,
      decoderSampleRate: 24000,
      outputBufferSampleRate: audioContext.sampleRate,
      resampleQuality: 0,
    });

    // Opus encoder for the mic. Same params Unmute's reference frontend uses.
    const recorderOptions = {
      mediaTrackConstraints: {
        audio: {
          echoCancellation: true,
          noiseSuppression: false,
          autoGainControl: true,
          channelCount: 1,
        },
        video: false,
      },
      encoderPath: ENCODER_URL,
      bufferLength: Math.round((960 * audioContext.sampleRate) / 24000),
      encoderFrameSize: 20,
      encoderSampleRate: 24000,
      maxFramesPerPage: 2,
      numberOfChannels: 1,
      recordingGain: 1,
      resampleQuality: 3,
      encoderComplexity: 0,
      encoderApplication: 2049,
      streamPages: true,
    };
    const opusRecorder = new OpusRecorder(recorderOptions);
    opusRecorder.ondataavailable = (data: Uint8Array) => {
      micDuration = opusRecorder.encodedSamplePosition / 48000;
      this.appendAudio(bytesToBase64(data));
    };

    await audioContext.resume();
    opusRecorder.start();

    this.audio = { audioContext, opusRecorder, decoder, outputWorklet, mediaStream };
  }

  send(payload: unknown): void {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      throw new Error("UnmuteSession not open");
    }
    ws.send(JSON.stringify(payload));
  }

  appendAudio(base64Opus: string): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.send({ type: "input_audio_buffer.append", audio: base64Opus });
  }

  /** Reset the playback worklet's buffered audio (e.g. on barge-in). */
  resetPlayback(): void {
    this.audio?.outputWorklet.port.postMessage({ type: "reset" });
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    // Tear down audio first so we stop emitting input_audio_buffer.append
    if (this.audio) {
      try { this.audio.opusRecorder.stop(); } catch {}
      try { this.audio.outputWorklet.disconnect(); } catch {}
      try { this.audio.decoder.terminate(); } catch {}
      try { void this.audio.audioContext.close(); } catch {}
      try { this.audio.mediaStream.getTracks().forEach((t) => t.stop()); } catch {}
      this.audio = null;
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try { this.ws.close(); } catch {}
    }
    this.ws = null;
  }

  get readyState(): number {
    return this.ws?.readyState ?? WebSocket.CLOSED;
  }

  get audioActive(): boolean {
    return !!this.audio;
  }
}
