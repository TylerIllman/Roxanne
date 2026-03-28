import type {
  ChatRequest,
  ConfigForm,
  IndexBrowseResult,
  IndexStats,
  NoteTreeResult,
  PaperTreeResult,
  PublicConfig,
  SpeechSetupResult,
  SpeechStatus,
  StreamEvent,
  ZoteroDetectResult,
  ZoteroNoteTreeResult,
} from "./types";

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as T;
}

export async function waitForBackend(baseUrl: string, retries = 30): Promise<void> {
  for (let attempt = 0; attempt < retries; attempt += 1) {
    try {
      const response = await fetch(`${baseUrl}/health`);
      if (response.ok) {
        return;
      }
    } catch {
      // The backend may still be starting up.
    }
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }

  throw new Error("The local backend did not become ready in time.");
}

export async function getConfig(baseUrl: string): Promise<PublicConfig> {
  const response = await fetch(`${baseUrl}/api/config`);
  return parseJson<PublicConfig>(response);
}

export async function saveConfig(baseUrl: string, config: ConfigForm): Promise<PublicConfig> {
  const response = await fetch(`${baseUrl}/api/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  return parseJson<PublicConfig>(response);
}

export async function runIndex(baseUrl: string, scope: "all" | "papers" | "notes") {
  const response = await fetch(`${baseUrl}/api/index`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scope }),
  });
  return parseJson<{ scope: string; report: unknown }>(response);
}

export async function streamChat(
  baseUrl: string,
  request: ChatRequest,
  onEvent: (event: StreamEvent) => void | Promise<void>
) {
  const response = await fetch(`${baseUrl}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok || !response.body) {
    throw new Error(await response.text());
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) {
        continue;
      }
      const event = JSON.parse(line) as StreamEvent;
      await onEvent(event);
      // Yield to the event loop so React can render each delta
      if (event.type === "assistant_delta") {
        await new Promise((r) => setTimeout(r, 0));
      }
    }
  }

  if (buffer.trim()) {
    await onEvent(JSON.parse(buffer) as StreamEvent);
  }
}

// ── Conversations ──

export type ConversationSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  preview: string;
};

export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: { role: string; content: string; timestamp: string }[];
};

export async function listConversations(baseUrl: string): Promise<ConversationSummary[]> {
  const response = await fetch(`${baseUrl}/api/conversations`);
  return parseJson<ConversationSummary[]>(response);
}

export async function createConversation(baseUrl: string, title?: string): Promise<Conversation> {
  const response = await fetch(`${baseUrl}/api/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title || "New conversation" }),
  });
  return parseJson<Conversation>(response);
}

export async function getConversation(baseUrl: string, convId: string): Promise<Conversation> {
  const response = await fetch(`${baseUrl}/api/conversations/${convId}`);
  return parseJson<Conversation>(response);
}

export async function appendMessage(baseUrl: string, convId: string, role: string, content: string): Promise<void> {
  await fetch(`${baseUrl}/api/conversations/${convId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, content }),
  });
}

export async function updateConversation(baseUrl: string, convId: string, updates: { title?: string }): Promise<void> {
  await fetch(`${baseUrl}/api/conversations/${convId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
}

export async function deleteConversation(baseUrl: string, convId: string): Promise<void> {
  await fetch(`${baseUrl}/api/conversations/${convId}`, { method: "DELETE" });
}

// ── Audio ──

export async function uploadAudio(baseUrl: string, blob: Blob): Promise<string> {
  const formData = new FormData();
  formData.append("file", new File([blob], "recording.webm", { type: blob.type || "audio/webm" }));

  const response = await fetch(`${baseUrl}/api/audio/transcribe-upload`, {
    method: "POST",
    body: formData,
  });

  const payload = await parseJson<{ text: string }>(response);
  return payload.text;
}

export async function synthesizeSpeech(baseUrl: string, text: string): Promise<string> {
  const response = await fetch(`${baseUrl}/api/audio/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });

  const payload = await parseJson<{ audio_path: string; audio_url: string }>(response);
  // Return the full HTTP URL so the renderer can play it
  return `${baseUrl}${payload.audio_url}`;
}

export async function getIndexStats(baseUrl: string): Promise<IndexStats> {
  const response = await fetch(`${baseUrl}/api/index/stats`);
  return parseJson<IndexStats>(response);
}

export async function browseIndex(
  baseUrl: string,
  collection: "papers" | "notes" | "memories" | "zotero_notes",
  limit = 500,
  offset = 0,
  fullText = false
): Promise<IndexBrowseResult> {
  const response = await fetch(
    `${baseUrl}/api/index/browse/${collection}?limit=${limit}&offset=${offset}&full_text=${fullText}`
  );
  return parseJson<IndexBrowseResult>(response);
}

export async function getIndexTree(
  baseUrl: string,
  collection: "papers" | "notes" | "zotero_notes"
): Promise<PaperTreeResult | NoteTreeResult | ZoteroNoteTreeResult> {
  const response = await fetch(`${baseUrl}/api/index/tree/${collection}`);
  return parseJson<PaperTreeResult | NoteTreeResult | ZoteroNoteTreeResult>(response);
}

export async function detectZotero(baseUrl: string): Promise<ZoteroDetectResult> {
  const response = await fetch(`${baseUrl}/api/zotero/detect`);
  return parseJson<ZoteroDetectResult>(response);
}

// ── Ollama management ──

export type OllamaStatus = {
  installed: boolean;
  binary_path: string | null;
  running: boolean;
  version: string;
  models: string[];
};

export type OllamaPullEvent = {
  status: string;
  progress: number;
  detail: string;
};

export async function getOllamaStatus(baseUrl: string): Promise<OllamaStatus> {
  const response = await fetch(`${baseUrl}/api/ollama/status`);
  return parseJson<OllamaStatus>(response);
}

export async function startOllama(baseUrl: string): Promise<{ ok: boolean; error?: string; models?: string[] }> {
  const response = await fetch(`${baseUrl}/api/ollama/start`, { method: "POST" });
  return parseJson<{ ok: boolean; error?: string; models?: string[] }>(response);
}

export async function getOllamaInstallInfo(baseUrl: string): Promise<{ method: string; command: string; alt_url: string; instructions: string }> {
  const response = await fetch(`${baseUrl}/api/ollama/install-info`);
  return parseJson<{ method: string; command: string; alt_url: string; instructions: string }>(response);
}

export async function pullOllamaModel(
  baseUrl: string,
  modelName: string,
  onProgress: (event: OllamaPullEvent) => void,
): Promise<void> {
  const response = await fetch(`${baseUrl}/api/ollama/pull/${encodeURIComponent(modelName)}`, { method: "POST" });
  if (!response.ok || !response.body) {
    throw new Error(await response.text());
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      onProgress(JSON.parse(line) as OllamaPullEvent);
    }
  }
  if (buffer.trim()) {
    onProgress(JSON.parse(buffer) as OllamaPullEvent);
  }
}

// ── Speech ──

export async function getSpeechStatus(baseUrl: string): Promise<SpeechStatus> {
  const response = await fetch(`${baseUrl}/api/speech/status`);
  return parseJson<SpeechStatus>(response);
}

export type SpeechSetupEvent = {
  step: string;
  status: string;
  progress: number;
  detail: string;
};

export async function setupSpeechStreaming(
  baseUrl: string,
  onProgress: (event: SpeechSetupEvent) => void,
): Promise<void> {
  const response = await fetch(`${baseUrl}/api/speech/setup`, { method: "POST" });
  if (!response.ok || !response.body) {
    throw new Error(await response.text());
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      onProgress(JSON.parse(line) as SpeechSetupEvent);
    }
  }
  if (buffer.trim()) {
    onProgress(JSON.parse(buffer) as SpeechSetupEvent);
  }
}

/** Non-streaming fallback */
export async function setupSpeech(baseUrl: string): Promise<SpeechSetupResult> {
  let lastEvent: SpeechSetupEvent | undefined;
  await setupSpeechStreaming(baseUrl, (e) => { lastEvent = e; });
  const last = lastEvent as SpeechSetupEvent | undefined;
  return {
    vosk: last?.step === "done" ? "installed" : "error",
    piper: "installed",
    voice: "installed",
    ready: last != null && last.status === "ready",
  };
}
