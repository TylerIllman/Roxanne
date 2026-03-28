import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import {
  appendMessage,
  browseIndex,
  createConversation,
  deleteConversation,
  detectZotero,
  getConfig,
  getConversation,
  getIndexStats,
  getIndexTree,
  getOllamaStatus,
  getSpeechStatus,
  listConversations,
  pullOllamaModel,
  runIndex,
  saveConfig,
  setupSpeech,
  setupSpeechStreaming,
  startOllama,
  streamChat,
  synthesizeSpeech,
  uploadAudio,
  waitForBackend,
} from "./api";
import type { ConversationSummary, OllamaPullEvent, OllamaStatus, SpeechSetupEvent } from "./api";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { Label } from "./components/ui/label";
import { Select } from "./components/ui/select";
import { Separator } from "./components/ui/separator";
import { Switch } from "./components/ui/switch";
import { Textarea } from "./components/ui/textarea";
import { cn } from "./lib/cn";
import type {
  ChatMessage,
  ConfigForm,
  IndexBrowseItem,
  IndexStats,
  LLMProvider,
  NoteHit,
  NoteTreeResult,
  NoteVaultGroup,
  PaperCollectionGroup,
  PaperHit,
  PaperTreeItem,
  PaperTreeResult,
  PublicConfig,
  RuntimeInfo,
  SpeechStatus,
  StreamEvent,
  ToolResultCard,
  VaultConfig,
  ZoteroNoteGroup,
  ZoteroNoteTreeResult,
} from "./types";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const EMPTY_CONFIG: ConfigForm = {
  anthropic: { provider: "anthropic", api_key: "", model: "claude-sonnet-4-20250514", max_tokens: 1400, base_url: "" },
  zotero: { database_path: "", storage_path: "" },
  embeddings: { provider: "fastembed", model: "BAAI/bge-base-en-v1.5", openai_api_key: "", openai_base_url: "" },
  speech: { stt_model: "small", piper_executable_path: "", piper_voice_model_path: "", voice_id: "en_US-amy-medium", speed: 1.15 },
  obsidian_vaults: [],
};

type WizardStep = 0 | 1 | 2 | 3 | 4 | 5;
const TOTAL_STEPS = 6;

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function makeId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
}

function blankVault(): VaultConfig {
  return { id: makeId(), name: "", path: "" };
}

function publicToForm(config: PublicConfig): ConfigForm {
  return {
    anthropic: {
      provider: config.anthropic.provider || "anthropic",
      api_key: "",
      model: config.anthropic.model || EMPTY_CONFIG.anthropic.model,
      max_tokens: config.anthropic.max_tokens || EMPTY_CONFIG.anthropic.max_tokens,
      base_url: config.anthropic.base_url || "",
    },
    zotero: {
      database_path: config.zotero.database_path || "",
      storage_path: config.zotero.storage_path || "",
    },
    embeddings: {
      provider: config.embeddings.provider || "fastembed",
      model: config.embeddings.model || EMPTY_CONFIG.embeddings.model,
      openai_api_key: "",
      openai_base_url: config.embeddings.openai_base_url || "",
    },
    speech: {
      stt_model: config.speech.stt_model || "small",
      piper_executable_path: config.speech.piper_executable_path || "",
      piper_voice_model_path: config.speech.piper_voice_model_path || "",
      voice_id: config.speech.voice_id || "en_US-amy-medium",
      speed: config.speech.speed ?? 1.15,
    },
    obsidian_vaults: config.obsidian_vaults.length ? config.obsidian_vaults : [blankVault()],
  };
}

function sanitizeConfig(config: ConfigForm): ConfigForm {
  return {
    anthropic: {
      provider: config.anthropic.provider,
      api_key: config.anthropic.api_key.trim(),
      model: config.anthropic.model.trim(),
      max_tokens: config.anthropic.max_tokens,
      base_url: config.anthropic.base_url.trim(),
    },
    zotero: {
      database_path: config.zotero.database_path.trim(),
      storage_path: config.zotero.storage_path.trim(),
    },
    embeddings: {
      provider: config.embeddings.provider,
      model: config.embeddings.model.trim(),
      openai_api_key: config.embeddings.openai_api_key.trim(),
      openai_base_url: config.embeddings.openai_base_url.trim(),
    },
    speech: {
      stt_model: config.speech.stt_model.trim(),
      piper_executable_path: config.speech.piper_executable_path.trim(),
      piper_voice_model_path: config.speech.piper_voice_model_path.trim(),
      voice_id: config.speech.voice_id || "en_US-amy-medium",
      speed: config.speech.speed ?? 1.15,
    },
    obsidian_vaults: config.obsidian_vaults
      .filter((v) => v.name.trim() || v.path.trim())
      .map((v) => ({ id: v.id, name: v.name.trim(), path: v.path.trim() })),
  };
}

function appendStatusMessage(setter: Dispatch<SetStateAction<ChatMessage[]>>, content: string) {
  setter((c) => [...c, { id: makeId(), role: "status", content }]);
}

function mergePapers(current: PaperHit[], incoming: PaperHit[]) {
  const index = new Map<string, PaperHit>();
  for (const item of current) index.set(item.paper_id, item);
  for (const item of incoming) {
    if (!item.paper_id) continue;
    index.set(item.paper_id, { ...index.get(item.paper_id), ...item });
  }
  return Array.from(index.values());
}

function hasVaults(vaults: VaultConfig[]) {
  return vaults.some((v) => v.name.trim() && v.path.trim());
}

/* ------------------------------------------------------------------ */
/*  Icons (inline SVG components)                                      */
/* ------------------------------------------------------------------ */

function IconMic({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="5" y="1" width="6" height="9" rx="3" />
      <path d="M3 7a5 5 0 0010 0" />
      <path d="M8 12v3" />
    </svg>
  );
}

function IconSpeaker({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 2L4 5.5H1.5v5H4L8 14V2z" />
      <path d="M11 5.5a3.5 3.5 0 010 5" />
      <path d="M13 3.5a6.5 6.5 0 010 9" />
    </svg>
  );
}

function IconSend({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.5 1.5l-13 5 5 2.5 2.5 5z" />
      <path d="M14.5 1.5l-6.5 8.5" />
    </svg>
  );
}

function IconFolder({ className }: { className?: string }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 5a1.5 1.5 0 011.5-1.5h3l1.5 1.5h6A1.5 1.5 0 0115.5 6.5v7a1.5 1.5 0 01-1.5 1.5H4a1.5 1.5 0 01-1.5-1.5V5z" />
    </svg>
  );
}

function IconCheck({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 8l3 3 5-5" />
    </svg>
  );
}

function IconX({ className }: { className?: string }) {
  return (
    <svg className={className} width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M3 3l8 8M11 3l-8 8" />
    </svg>
  );
}

function IconSettings({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="8" r="2.5" />
      <path d="M13.5 8a5.5 5.5 0 01-.3 1.8l1.3.8-1 1.7-1.3-.7a5.5 5.5 0 01-1.5 1l.1 1.5h-2l.1-1.5a5.5 5.5 0 01-1.5-1l-1.3.7-1-1.7 1.3-.8A5.5 5.5 0 012.5 8a5.5 5.5 0 01.3-1.8l-1.3-.8 1-1.7 1.3.7a5.5 5.5 0 011.5-1L5.2.9h2l-.1 1.5a5.5 5.5 0 011.5 1l1.3-.7 1 1.7-1.3.8a5.5 5.5 0 01.3 1.8z" />
    </svg>
  );
}

function IconRefresh({ className }: { className?: string }) {
  return (
    <svg className={className} width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 2v4h4" />
      <path d="M2.5 9A5 5 0 1013 7" />
      <path d="M1 6a5 5 0 018.5-3.5L1 6z" />
    </svg>
  );
}

function IconChevron({ className }: { className?: string }) {
  return (
    <svg className={className} width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 10l3-3-3-3" />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Toast notifications                                                */
/* ------------------------------------------------------------------ */

type Toast = { id: string; type: "error" | "success" | "info"; title: string; message: string; exiting?: boolean };

function ToastContainer({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: string) => void }) {
  if (!toasts.length) return null;
  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 max-w-[420px]">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={cn(
            "flex items-start gap-3 px-4 py-3 rounded-xl shadow-lg border backdrop-blur-sm",
            toast.exiting ? "animate-[toast-out_200ms_ease-in_forwards]" : "animate-[toast-in_300ms_ease-out_both]",
            toast.type === "error" && "bg-red-50 border-red-200 text-red-900",
            toast.type === "success" && "bg-emerald-50 border-emerald-200 text-emerald-900",
            toast.type === "info" && "bg-white border-zinc-200 text-zinc-900",
          )}
        >
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold">{toast.title}</p>
            <p className="text-xs mt-0.5 opacity-80 break-words">{toast.message}</p>
          </div>
          <button type="button" className="shrink-0 text-current opacity-40 hover:opacity-100 transition-opacity" onClick={() => onDismiss(toast.id)}>
            <IconX />
          </button>
        </div>
      ))}
    </div>
  );
}

function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const addToast = useCallback((type: Toast["type"], title: string, message: string) => {
    const id = makeId();
    setToasts((prev) => [...prev, { id, type, title, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, exiting: true } : t)));
      setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 200);
    }, 8000);
  }, []);
  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, exiting: true } : t)));
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 200);
  }, []);
  return { toasts, addToast, dismissToast };
}

/* ------------------------------------------------------------------ */
/*  Setup Modal — pops up when a dependency is missing                 */
/* ------------------------------------------------------------------ */

type SetupNeed = "ollama" | "vosk" | "piper" | null;

function SetupModal({ need, baseUrl, configForm, setConfigForm, onClose }: {
  need: SetupNeed;
  baseUrl: string;
  configForm: ConfigForm;
  setConfigForm: Dispatch<SetStateAction<ConfigForm>>;
  onClose: () => void;
}) {
  if (!need) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm animate-[fade-in_150ms_ease-out]" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="bg-white rounded-2xl shadow-2xl border border-zinc-200 w-full max-w-lg mx-4 max-h-[80vh] overflow-y-auto animate-[scale-in_200ms_ease-out]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-3">
          <div>
            <h2 className="text-lg font-bold text-zinc-900">
              {need === "ollama" && "Ollama Setup Required"}
              {need === "vosk" && "Speech-to-Text Setup"}
              {need === "piper" && "Text-to-Speech Setup"}
            </h2>
            <p className="text-xs text-zinc-500 mt-0.5">
              {need === "ollama" && "Ollama is needed to run your local LLM."}
              {need === "vosk" && "Vosk is needed for voice transcription."}
              {need === "piper" && "Piper is needed for text-to-speech."}
            </p>
          </div>
          <button type="button" onClick={onClose} className="shrink-0 w-8 h-8 grid place-items-center rounded-lg text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 transition-colors">
            <IconX />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 pb-6 pt-2">
          {need === "ollama" && (
            <OllamaSetupPanel baseUrl={baseUrl} configForm={configForm} setConfigForm={setConfigForm} />
          )}
          {need === "vosk" && (
            <VoskSetupPanel baseUrl={baseUrl} onDone={onClose} />
          )}
          {need === "piper" && (
            <PiperSetupPanel baseUrl={baseUrl} onDone={onClose} />
          )}
        </div>
      </div>
    </div>
  );
}

function VoskSetupPanel({ baseUrl, onDone }: { baseUrl: string; onDone: () => void }) {
  const [status, setStatus] = useState<SpeechStatus | null>(null);
  const [installing, setInstalling] = useState(false);
  const [setupEvents, setSetupEvents] = useState<SpeechSetupEvent[]>([]);

  useEffect(() => {
    void (async () => {
      try { setStatus(await getSpeechStatus(baseUrl)); } catch {}
    })();
  }, [baseUrl]);

  async function handleInstall() {
    setInstalling(true);
    try {
      await setupSpeechStreaming(baseUrl, (ev) => setSetupEvents((p) => [...p.slice(-5), ev]));
      const s = await getSpeechStatus(baseUrl);
      setStatus(s);
      if (s.vosk_ready) onDone();
    } catch {} finally {
      setInstalling(false);
    }
  }

  const lastEvent = setupEvents[setupEvents.length - 1];

  return (
    <div className="flex flex-col gap-3">
      <div className={cn("flex items-center gap-2.5 px-3 py-2.5 border rounded-xl text-xs", status?.vosk_ready ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-zinc-200 bg-zinc-50 text-zinc-500")}>
        <span className={cn("shrink-0 w-5 h-5 grid place-items-center rounded-full", status?.vosk_ready ? "bg-emerald-100" : "bg-zinc-200")}>
          {status?.vosk_ready ? <IconCheck className="w-3 h-3" /> : <span className="w-1.5 h-1.5 rounded-full bg-zinc-400" />}
        </span>
        <span className="font-medium">Vosk STT model</span>
        <span className="ml-auto font-medium">{status?.vosk_ready ? "Installed" : "Not installed"}</span>
      </div>

      {!status?.vosk_ready && !installing && (
        <div>
          <p className="text-xs text-zinc-500 mb-3">This will download a ~50 MB speech recognition model. It may take a few minutes.</p>
          <Button size="sm" onClick={handleInstall}>Download &amp; install Vosk</Button>
        </div>
      )}

      {installing && lastEvent && (
        <div className="px-4 py-3 rounded-xl border border-amber-200 bg-amber-50">
          <div className="flex items-center gap-2 mb-2">
            <svg className="w-4 h-4 text-amber-500 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" strokeLinecap="round" /></svg>
            <span className="text-xs font-semibold text-amber-800">Installing...</span>
          </div>
          <p className="text-[0.65rem] text-amber-600">{lastEvent.detail || lastEvent.step}</p>
        </div>
      )}
    </div>
  );
}

function PiperSetupPanel({ baseUrl, onDone }: { baseUrl: string; onDone: () => void }) {
  const [status, setStatus] = useState<SpeechStatus | null>(null);
  const [installing, setInstalling] = useState(false);
  const [setupEvents, setSetupEvents] = useState<SpeechSetupEvent[]>([]);

  useEffect(() => {
    void (async () => {
      try { setStatus(await getSpeechStatus(baseUrl)); } catch {}
    })();
  }, [baseUrl]);

  async function handleInstall() {
    setInstalling(true);
    try {
      await setupSpeechStreaming(baseUrl, (ev) => setSetupEvents((p) => [...p.slice(-5), ev]));
      const s = await getSpeechStatus(baseUrl);
      setStatus(s);
      if (s.piper_installed && s.voice_installed) onDone();
    } catch {} finally {
      setInstalling(false);
    }
  }

  const lastEvent = setupEvents[setupEvents.length - 1];

  return (
    <div className="flex flex-col gap-3">
      {[
        { label: "Piper TTS", ok: status?.piper_installed },
        { label: "Voice model", ok: status?.voice_installed },
      ].map((item) => (
        <div key={item.label} className={cn("flex items-center gap-2.5 px-3 py-2.5 border rounded-xl text-xs", item.ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-zinc-200 bg-zinc-50 text-zinc-500")}>
          <span className={cn("shrink-0 w-5 h-5 grid place-items-center rounded-full", item.ok ? "bg-emerald-100" : "bg-zinc-200")}>
            {item.ok ? <IconCheck className="w-3 h-3" /> : <span className="w-1.5 h-1.5 rounded-full bg-zinc-400" />}
          </span>
          <span className="font-medium">{item.label}</span>
          <span className="ml-auto font-medium">{item.ok ? "Installed" : "Not installed"}</span>
        </div>
      ))}

      {(!status?.piper_installed || !status?.voice_installed) && !installing && (
        <div>
          <p className="text-xs text-zinc-500 mb-3">This will download the Piper TTS engine and a voice model. May take a few minutes.</p>
          <Button size="sm" onClick={handleInstall}>Download &amp; install</Button>
        </div>
      )}

      {installing && lastEvent && (
        <div className="px-4 py-3 rounded-xl border border-amber-200 bg-amber-50">
          <div className="flex items-center gap-2 mb-2">
            <svg className="w-4 h-4 text-amber-500 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" strokeLinecap="round" /></svg>
            <span className="text-xs font-semibold text-amber-800">Installing...</span>
          </div>
          <p className="text-[0.65rem] text-amber-600">{lastEvent.detail || lastEvent.step}</p>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Small UI primitives                                                */
/* ------------------------------------------------------------------ */

function Field({ label, hint, htmlFor, children }: { label: string; hint?: string; htmlFor?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {hint && <p className="text-zinc-400 text-[0.82rem] leading-snug">{hint}</p>}
      {children}
    </div>
  );
}

function PathPicker({ value, onPick, placeholder, label }: { value: string; onPick: () => void; placeholder?: string; label?: string }) {
  return (
    <button
      type="button"
      className="flex items-center gap-3 w-full px-3.5 py-3 border border-zinc-200 rounded-xl bg-white text-left cursor-pointer transition-all duration-150 hover:border-zinc-300 hover:shadow-sm"
      onClick={onPick}
    >
      <div className="shrink-0 w-9 h-9 grid place-items-center rounded-lg bg-zinc-100 text-zinc-500">
        <IconFolder />
      </div>
      <div className="flex-1 min-w-0 flex flex-col gap-0.5">
        <span className="text-xs font-semibold text-zinc-900 uppercase tracking-wide">{label || "Choose folder"}</span>
        <span className="text-sm text-zinc-500 truncate">{value || placeholder || "Click to browse..."}</span>
      </div>
      <IconChevron className="shrink-0 text-zinc-400" />
    </button>
  );
}

function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center justify-center gap-2">
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          className={cn(
            "h-2 rounded-full transition-all duration-200",
            i === current ? "w-6 bg-zinc-900" : i < current ? "w-2 bg-emerald-500" : "w-2 bg-zinc-200"
          )}
        />
      ))}
    </div>
  );
}

/** Pulsing recording indicator */
function RecordingPill() {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-red-50 border border-red-200">
      <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse" />
      <span className="text-xs font-semibold text-red-700">Recording</span>
    </div>
  );
}

/** Speaking indicator */
function SpeakingPill() {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-blue-50 border border-blue-200">
      <IconSpeaker className="w-3.5 h-3.5 text-blue-600" />
      <span className="text-xs font-semibold text-blue-700">Speaking</span>
    </div>
  );
}

/** Transcribing indicator */
function TranscribingPill() {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-50 border border-amber-200">
      <IconMic className="w-3.5 h-3.5 text-amber-600 animate-pulse" />
      <span className="text-xs font-semibold text-amber-700">Transcribing...</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Markdown chat bubble                                               */
/* ------------------------------------------------------------------ */

function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        p: ({ children }) => <p className="text-sm leading-relaxed mb-2 last:mb-0">{children}</p>,
        h1: ({ children }) => <h1 className="text-lg font-bold mb-2 mt-3">{children}</h1>,
        h2: ({ children }) => <h2 className="text-base font-bold mb-1.5 mt-2.5">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-bold mb-1 mt-2">{children}</h3>,
        ul: ({ children }) => <ul className="list-disc pl-5 mb-2 text-sm leading-relaxed">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 text-sm leading-relaxed">{children}</ol>,
        li: ({ children }) => <li className="mb-0.5">{children}</li>,
        code: ({ className, children, ...props }) => {
          const isBlock = className?.includes("language-");
          if (isBlock) {
            return (
              <pre className="bg-zinc-900 text-zinc-100 rounded-lg p-3 mb-2 overflow-x-auto text-xs leading-relaxed">
                <code className={className} {...props}>{children}</code>
              </pre>
            );
          }
          return <code className="bg-zinc-100 text-zinc-800 px-1.5 py-0.5 rounded text-xs font-mono" {...props}>{children}</code>;
        },
        blockquote: ({ children }) => (
          <blockquote className="border-l-3 border-zinc-300 pl-3 italic text-zinc-500 mb-2 text-sm">{children}</blockquote>
        ),
        table: ({ children }) => (
          <div className="overflow-x-auto mb-2">
            <table className="min-w-full text-sm border-collapse border border-zinc-200 rounded">{children}</table>
          </div>
        ),
        th: ({ children }) => <th className="border border-zinc-200 px-3 py-1.5 bg-zinc-50 text-left font-semibold text-xs">{children}</th>,
        td: ({ children }) => <td className="border border-zinc-200 px-3 py-1.5 text-xs">{children}</td>,
        a: ({ href, children }) => <a href={href} className="text-blue-600 underline hover:text-blue-800" target="_blank" rel="noopener noreferrer">{children}</a>,
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        hr: () => <hr className="border-zinc-200 my-3" />,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

/* ------------------------------------------------------------------ */
/*  Citation-aware content & Tool result cards                         */
/* ------------------------------------------------------------------ */

/**
 * Parse and render citations in format [CITE:file_path|page|quoted_text]
 * Renders as clickable inline pill buttons that open the PDF at the specific page.
 * Shows quoted text on hover.
 */
function CitationContent({ content }: { content: string }) {
  // Convert [CITE:path|page|text] → special markdown links
  const processed = content.replace(
    /\[CITE:([^|\]]+)(?:\|([^|\]]*))?(?:\|([^\]]*))?\]/g,
    (_match, filePath: string, page?: string, text?: string) => {
      const p = (page || "").trim();
      const t = (text || "").trim();
      const params = new URLSearchParams();
      params.set("path", filePath.trim());
      if (p) params.set("page", p);
      if (t) params.set("text", t);
      const label = p ? `p.${p}` : "source";
      return `[📄 ${label}](cite://?${params.toString()})`;
    }
  );

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        p: ({ children }) => <p className="text-sm leading-relaxed mb-2 last:mb-0">{children}</p>,
        h1: ({ children }) => <h1 className="text-lg font-bold mb-2 mt-3">{children}</h1>,
        h2: ({ children }) => <h2 className="text-base font-bold mb-1.5 mt-2.5">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-bold mb-1 mt-2">{children}</h3>,
        ul: ({ children }) => <ul className="list-disc pl-5 mb-2 text-sm leading-relaxed">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 text-sm leading-relaxed">{children}</ol>,
        li: ({ children }) => <li className="mb-0.5">{children}</li>,
        code: ({ className, children, ...props }) => {
          const isBlock = className?.includes("language-");
          if (isBlock) {
            return <pre className="bg-zinc-900 text-zinc-100 rounded-lg p-3 text-xs overflow-x-auto mb-2"><code {...props} className={className}>{children}</code></pre>;
          }
          return <code {...props} className="bg-zinc-100 px-1.5 py-0.5 rounded text-[0.8rem] font-mono text-zinc-800">{children}</code>;
        },
        blockquote: ({ children }) => <blockquote className="border-l-2 border-zinc-300 pl-3 italic text-zinc-600 my-2">{children}</blockquote>,
        table: ({ children }) => (
          <div className="overflow-x-auto mb-2">
            <table className="min-w-full border-collapse text-xs">{children}</table>
          </div>
        ),
        th: ({ children }) => <th className="border border-zinc-200 px-3 py-1.5 bg-zinc-50 text-left font-semibold text-xs">{children}</th>,
        td: ({ children }) => <td className="border border-zinc-200 px-3 py-1.5 text-xs">{children}</td>,
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        hr: () => <hr className="border-zinc-200 my-3" />,
        a: ({ href, children }) => {
          if (href?.startsWith("cite://")) {
            try {
              const params = new URLSearchParams(href.replace("cite://", "").replace("?", ""));
              const filePath = params.get("path") || "";
              const page = params.get("page") || "";
              const quotedText = params.get("text") || "";
              return <CiteButton filePath={filePath} page={page} quotedText={quotedText}>{children}</CiteButton>;
            } catch {
              return <span className="text-blue-600">{children}</span>;
            }
          }
          return <a href={href} className="text-blue-600 underline hover:text-blue-800" target="_blank" rel="noopener noreferrer">{children}</a>;
        },
      }}
    >
      {processed}
    </ReactMarkdown>
  );
}

/** Inline citation button — opens PDF at page via Zotero, shows quoted text on hover */
function CiteButton({ filePath, page, quotedText, children }: { filePath: string; page: string; quotedText: string; children: ReactNode }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const pageNum = parseInt(page, 10);

  function handleClick() {
    if (!filePath) return;
    if (pageNum > 0) {
      void window.jarvis.openPdfAtPage(filePath, pageNum);
    } else {
      void window.jarvis.openPath(filePath);
    }
  }

  return (
    <span className="relative inline-flex align-baseline">
      <button
        type="button"
        onClick={handleClick}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md bg-blue-50 border border-blue-200 text-blue-700 text-[0.7rem] font-medium hover:bg-blue-100 hover:border-blue-300 transition-colors cursor-pointer"
        title={quotedText ? `"${quotedText}"` : `Open ${filePath}${pageNum > 0 ? ` at page ${pageNum}` : ""}`}
      >
        {children}
      </button>
      {showTooltip && quotedText && (
        <div className="absolute bottom-full left-0 mb-1.5 z-50 max-w-xs w-max pointer-events-none">
          <div className="bg-zinc-900 text-white text-[0.65rem] leading-snug px-3 py-2 rounded-lg shadow-lg">
            <p className="italic">"{quotedText.slice(0, 200)}{quotedText.length > 200 ? "..." : ""}"</p>
            {pageNum > 0 && <p className="mt-1 text-zinc-400 not-italic">Page {pageNum}</p>}
          </div>
        </div>
      )}
    </span>
  );
}

/** Card for search_zotero results */
function SearchResultsCard({ payload }: { payload: unknown }) {
  const results = (payload as Array<Record<string, unknown>>) || [];
  if (!results.length) return null;
  return (
    <div className="flex flex-col gap-1 my-2">
      <span className="text-[0.65rem] font-bold text-zinc-400 uppercase tracking-wider mb-1">Papers Found</span>
      {results.slice(0, 6).map((r, i) => (
        <button
          key={i}
          type="button"
          className="flex items-center gap-2.5 px-3 py-2 rounded-lg border border-zinc-100 bg-zinc-50 hover:bg-zinc-100 transition-colors text-left"
          onClick={() => {
            const fp = r.file_path as string;
            if (fp) void window.jarvis.openPath(fp);
          }}
        >
          <IconDocument className="shrink-0 text-blue-500" />
          <div className="flex-1 min-w-0">
            <span className="text-xs font-semibold text-zinc-800 truncate block">{String(r.title || "Untitled")}</span>
            <span className="text-[0.65rem] text-zinc-400">
              {r.authors ? String(r.authors).split(";")[0].trim() : ""}
              {r.year ? ` · ${r.year}` : ""}
              {r.collections ? ` · ${String(r.collections).split(";")[0].trim()}` : ""}
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}

/** Card for retrieve_paper_chunks results */
function ChunkResultsCard({ payload }: { payload: unknown }) {
  const chunks = (payload as Array<Record<string, unknown>>) || [];
  if (!chunks.length) return null;
  return (
    <div className="flex flex-col gap-1.5 my-2">
      <span className="text-[0.65rem] font-bold text-zinc-400 uppercase tracking-wider mb-0.5">Retrieved Chunks</span>
      {chunks.slice(0, 3).map((c, i) => (
        <div key={i} className="px-3 py-2.5 rounded-lg border border-blue-100 bg-blue-50/50">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-[0.6rem] font-bold text-blue-600">
              {String(c.title || "").slice(0, 60)}
            </span>
            {c.page_start != null && (
              <span className="text-[0.6rem] font-medium text-blue-500 bg-blue-100 px-1.5 py-0.5 rounded">
                {String(c.page_start) === String(c.page_end) ? `p.${String(c.page_start)}` : `pp.${String(c.page_start)}-${String(c.page_end)}`}
              </span>
            )}
          </div>
          <p className="text-xs text-zinc-600 leading-relaxed line-clamp-3">{String(c.chunk || "").slice(0, 300)}</p>
        </div>
      ))}
    </div>
  );
}

/** Card for paper notes */
function NotesResultCard({ payload }: { payload: unknown }) {
  const data = payload as Record<string, unknown>;
  const notes = (data?.notes as Array<Record<string, unknown>>) || [];
  if (!notes.length) return null;
  return (
    <div className="flex flex-col gap-1.5 my-2">
      <span className="text-[0.65rem] font-bold text-zinc-400 uppercase tracking-wider mb-0.5">Zotero Notes ({notes.length})</span>
      {notes.slice(0, 5).map((n, i) => (
        <div key={i} className="px-3 py-2.5 rounded-lg border border-amber-100 bg-amber-50/50">
          <p className="text-xs text-zinc-700 leading-relaxed">{String(n.text || "").slice(0, 400)}</p>
          <span className="text-[0.6rem] text-zinc-400 mt-1 block">
            {n.date_modified ? `Modified: ${String(n.date_modified).slice(0, 10)}` : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Card for annotations */
function AnnotationsResultCard({ payload }: { payload: unknown }) {
  const data = payload as Record<string, unknown>;
  const annotations = (data?.annotations as Array<Record<string, unknown>>) || [];
  if (!annotations.length) return null;
  return (
    <div className="flex flex-col gap-1 my-2">
      <span className="text-[0.65rem] font-bold text-zinc-400 uppercase tracking-wider mb-0.5">Annotations ({annotations.length})</span>
      {annotations.slice(0, 8).map((a, i) => (
        <div key={i} className="flex gap-2 px-3 py-2 rounded-lg border border-zinc-100 bg-zinc-50">
          <div
            className="shrink-0 w-1 rounded-full"
            style={{ backgroundColor: (a.color as string) || "#ffd400" }}
          />
          <div className="flex-1 min-w-0">
            {a.highlighted_text ? (
              <p className="text-xs text-zinc-700 italic leading-relaxed">&quot;{String(a.highlighted_text)}&quot;</p>
            ) : null}
            {a.comment ? (
              <p className="text-xs text-zinc-500 mt-0.5">{String(a.comment)}</p>
            ) : null}
            <span className="text-[0.6rem] text-zinc-400">{a.page ? `p.${String(a.page)}` : ""} · {String(a.type || "highlight")}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

/** Render tool result cards based on tool name */
function ToolCard({ card }: { card: ToolResultCard }) {
  switch (card.tool) {
    case "search_zotero":
    case "search_zotero_metadata":
      return <SearchResultsCard payload={card.payload} />;
    case "retrieve_paper_chunks":
      return <ChunkResultsCard payload={card.payload} />;
    case "get_paper_notes":
      return <NotesResultCard payload={card.payload} />;
    case "get_paper_annotations":
      return <AnnotationsResultCard payload={card.payload} />;
    default:
      return null;
  }
}

/* ------------------------------------------------------------------ */
/*  Collapsible tool steps group (ChatGPT / Claude style)              */
/* ------------------------------------------------------------------ */

type MessageGroup =
  | { kind: "user" | "assistant"; msg: ChatMessage }
  | { kind: "tool_steps"; steps: ChatMessage[] };

/** Group consecutive status + tool_card messages into collapsible step blocks */
function groupMessages(messages: ChatMessage[]): MessageGroup[] {
  const groups: MessageGroup[] = [];
  let pendingSteps: ChatMessage[] = [];

  function flushSteps() {
    if (pendingSteps.length > 0) {
      groups.push({ kind: "tool_steps", steps: [...pendingSteps] });
      pendingSteps = [];
    }
  }

  for (const msg of messages) {
    if (msg.role === "status" || msg.role === "tool_card") {
      pendingSteps.push(msg);
    } else {
      flushSteps();
      groups.push({ kind: msg.role as "user" | "assistant", msg });
    }
  }
  flushSteps();
  return groups;
}

/** Pretty label for a tool name */
function toolLabel(name: string): string {
  const labels: Record<string, string> = {
    search_zotero: "Searching papers",
    search_zotero_metadata: "Searching metadata",
    retrieve_paper_chunks: "Reading paper chunks",
    get_paper_metadata: "Getting paper info",
    get_paper_notes: "Fetching notes",
    get_paper_annotations: "Fetching annotations",
    search_zotero_notes: "Searching notes",
    list_zotero_collections: "Listing collections",
    get_collection_papers: "Browsing collection",
    read_notes: "Reading Obsidian notes",
    write_note: "Writing note",
    open_pdf: "Opening PDF",
  };
  return labels[name] || name.replace(/_/g, " ");
}

/** A collapsible group of tool calls, like ChatGPT's "Searched 3 sources" */
function ToolStepsGroup({ steps, isLatest }: { steps: ChatMessage[]; isLatest: boolean }) {
  const [expanded, setExpanded] = useState(false);

  // Extract status labels — backend now sends snappy labels directly
  const toolNames = steps
    .filter((s) => s.role === "status")
    .map((s) => s.content);

  const toolCards = steps.filter((s) => s.role === "tool_card" && s.toolCard);

  // While actively running (latest group), show spinner + current step
  if (isLatest) {
    const lastTool = toolNames[toolNames.length - 1] || "";
    return (
      <div className="self-start max-w-[min(85%,720px)] animate-[fade-in_200ms_ease-out_both]">
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-zinc-50 border border-zinc-200">
          <svg className="w-3.5 h-3.5 text-zinc-400 animate-spin shrink-0" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" opacity="0.25" />
            <path d="M8 2a6 6 0 014.9 9.46" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <span className="text-xs text-zinc-500 font-medium">{lastTool}</span>
          {toolNames.length > 1 && (
            <span className="text-[0.65rem] text-zinc-400 ml-1">({toolNames.length} steps)</span>
          )}
        </div>
      </div>
    );
  }

  // Completed group — show collapsed summary, expandable
  const summary = toolNames.length === 1
    ? toolNames[0]
    : `Used ${toolNames.length} tools`;

  return (
    <div className="self-start max-w-[min(85%,720px)] animate-[fade-in_200ms_ease-out_both]">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-zinc-50 border border-zinc-100 hover:bg-zinc-100 transition-colors group cursor-pointer"
      >
        <svg className="w-3.5 h-3.5 text-emerald-500 shrink-0" viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 1a7 7 0 110 14A7 7 0 018 1zm3.35 4.65a.5.5 0 00-.7 0L7 9.29 5.35 7.65a.5.5 0 10-.7.7l2 2a.5.5 0 00.7 0l4-4a.5.5 0 000-.7z" />
        </svg>
        <span className="text-xs text-zinc-500 font-medium">{summary}</span>
        <svg
          className={cn(
            "w-3 h-3 text-zinc-400 transition-transform ml-1",
            expanded && "rotate-180"
          )}
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M3 5l3 3 3-3" />
        </svg>
      </button>

      {expanded && (
        <div className="mt-2 flex flex-col gap-2 pl-2 border-l-2 border-zinc-100 ml-4 animate-[fade-in_150ms_ease-out_both]">
          {steps.map((step) =>
            step.role === "status" ? (
              <div key={step.id} className="flex items-center gap-2 text-[0.7rem] text-zinc-400">
                <svg className="w-3 h-3 text-emerald-400 shrink-0" viewBox="0 0 12 12" fill="currentColor">
                  <circle cx="6" cy="6" r="5" />
                </svg>
                {step.content}
              </div>
            ) : step.role === "tool_card" && step.toolCard ? (
              <div key={step.id} className="ml-1">
                <ToolCard card={step.toolCard} />
              </div>
            ) : null
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Wizard step views                                                  */
/* ------------------------------------------------------------------ */

function WelcomeStep({ onNext }: { onNext: () => void }) {
  return (
    <div className="flex flex-col gap-6 flex-1 items-center text-center justify-center">
      <div className="w-16 h-16 grid place-items-center rounded-full bg-zinc-100 text-zinc-900">
        <svg width="36" height="36" viewBox="0 0 36 36" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="18" cy="18" r="15" />
          <path d="M13 18l3.5 3.5 6.5-6.5" />
        </svg>
      </div>
      <h1 className="text-2xl font-bold tracking-tight text-zinc-900">Welcome to Jarvis</h1>
      <p className="text-sm leading-relaxed text-zinc-500 max-w-[420px]">
        Your local-first research copilot. Let's connect your tools and get everything set up in a few quick steps.
      </p>
      <div className="flex flex-col gap-3 mt-1 w-full max-w-[340px] text-left">
        {[
          ["Search & retrieve from your Zotero library", "M3 3h14v14H3zM7 7h6M7 10h6M7 13h3"],
          ["Read & write notes in your Obsidian vaults", "M4 4h5l1 2h6v10H4z"],
          ["Voice input & spoken replies, all local", "M10 7v3l2 2"],
        ].map(([text, path], i) => (
          <div key={i} className="flex items-center gap-3 text-sm text-zinc-500">
            <span className="shrink-0 w-8 h-8 grid place-items-center rounded-lg bg-zinc-100 text-zinc-900">
              <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d={path} />
              </svg>
            </span>
            <span>{text}</span>
          </div>
        ))}
      </div>
      <Button className="mt-3 min-w-[200px]" onClick={onNext}>Get started</Button>
    </div>
  );
}

const MODEL_PRESETS: Record<LLMProvider, { label: string; value: string }[]> = {
  anthropic: [
    { label: "Claude Sonnet 4", value: "claude-sonnet-4-20250514" },
    { label: "Claude Opus 4", value: "claude-opus-4-20250514" },
    { label: "Claude Haiku 4.5", value: "claude-haiku-4-5-20251001" },
  ],
  openai: [
    { label: "GPT-4o", value: "gpt-4o" },
    { label: "GPT-4o mini", value: "gpt-4o-mini" },
    { label: "GPT-4.1", value: "gpt-4.1" },
    { label: "GPT-4.1 mini", value: "gpt-4.1-mini" },
    { label: "GPT-4.1 nano", value: "gpt-4.1-nano" },
  ],
  ollama: [
    { label: "Qwen 2.5 7B (recommended)", value: "qwen2.5:7b" },
    { label: "Qwen 2.5 14B (better)", value: "qwen2.5:14b" },
    { label: "Mistral 7B", value: "mistral:7b" },
    { label: "Llama 3.1 8B", value: "llama3.1:8b" },
    { label: "Llama 3.3 70B", value: "llama3.3:70b" },
    { label: "DeepSeek R1 8B", value: "deepseek-r1:8b" },
    { label: "Phi-4 14B", value: "phi4:14b" },
    { label: "Custom (type below)", value: "" },
  ],
};

function OllamaSetupPanel({ baseUrl, configForm, setConfigForm }: { baseUrl: string; configForm: ConfigForm; setConfigForm: Dispatch<SetStateAction<ConfigForm>> }) {
  const [ollamaStatus, setOllamaStatus] = useState<OllamaStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [pulling, setPulling] = useState(false);
  const [pullEvent, setPullEvent] = useState<OllamaPullEvent | null>(null);
  const [error, setError] = useState("");
  const hasChecked = useRef(false);

  const checkStatus = useCallback(async () => {
    try {
      const s = await getOllamaStatus(baseUrl);
      setOllamaStatus(s);
      return s;
    } catch { return null; }
  }, [baseUrl]);

  useEffect(() => {
    if (!hasChecked.current && baseUrl) {
      hasChecked.current = true;
      void checkStatus();
    }
  }, [baseUrl, checkStatus]);

  // Re-check when selected model changes
  const selectedModel = configForm.anthropic.model || "qwen2.5:7b";
  useEffect(() => {
    if (baseUrl && ollamaStatus?.running) void checkStatus();
  }, [selectedModel]);

  async function handleStart() {
    setStarting(true);
    setError("");
    try {
      const result = await startOllama(baseUrl);
      if (!result.ok) {
        setError(result.error || "Failed to start Ollama.");
      }
      await checkStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  }

  async function handlePull(model?: string) {
    const modelToPull = model || selectedModel;
    setPulling(true);
    setPullEvent(null);
    setError("");
    try {
      await pullOllamaModel(baseUrl, modelToPull, (ev) => {
        setPullEvent(ev);
        if (ev.status === "error") setError(ev.detail);
      });
      await checkStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPulling(false);
    }
  }

  // Exact model matching — "qwen2.5:14b" must NOT match "qwen2.5:7b"
  const normalizeModelName = (m: string) => m.includes(":") ? m : `${m}:latest`;
  const isModelInstalled = (model: string) => ollamaStatus?.models.some((m) => {
    return normalizeModelName(m) === normalizeModelName(model);
  }) ?? false;
  const modelInstalled = isModelInstalled(selectedModel);

  if (!ollamaStatus) {
    return <div className="text-xs text-zinc-400 text-center py-4">Checking Ollama status...</div>;
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Status indicators */}
      {[
        { label: "Ollama installed", ok: ollamaStatus.installed },
        { label: "Server running", ok: ollamaStatus.running },
        { label: `Model: ${selectedModel}`, ok: modelInstalled },
      ].map((item) => (
        <div key={item.label} className={cn("flex items-center gap-2.5 px-3 py-2.5 border rounded-xl text-xs transition-all", item.ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-zinc-200 bg-zinc-50 text-zinc-500")}>
          <span className={cn("shrink-0 w-5 h-5 grid place-items-center rounded-full", item.ok ? "bg-emerald-100" : "bg-zinc-200")}>
            {item.ok ? <IconCheck className="w-3 h-3" /> : <span className="w-1.5 h-1.5 rounded-full bg-zinc-400" />}
          </span>
          <span className="font-medium">{item.label}</span>
          <span className="ml-auto font-medium">{item.ok ? "Ready" : "Needed"}</span>
        </div>
      ))}

      {/* Not installed */}
      {!ollamaStatus.installed && (
        <div className="px-4 py-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-800 leading-relaxed">
          <p className="font-semibold mb-1">Ollama not found</p>
          <p>Install Ollama to run models locally. Open your terminal and run:</p>
          <code className="block mt-2 px-3 py-2 bg-amber-100 rounded-lg font-mono text-[0.7rem]">brew install ollama</code>
          <p className="mt-2 text-amber-600">Or download from <span className="underline">ollama.com/download</span></p>
          <Button size="sm" className="mt-3" onClick={() => void checkStatus()}>Check again</Button>
        </div>
      )}

      {/* Installed but not running */}
      {ollamaStatus.installed && !ollamaStatus.running && (
        <Button size="sm" onClick={handleStart} disabled={starting}>
          {starting ? "Starting server..." : "Start Ollama server"}
        </Button>
      )}

      {/* Model selector with download buttons */}
      {ollamaStatus.running && (
        <div className="flex flex-col gap-2">
          <label className="text-xs font-semibold text-zinc-600">Select model</label>
          <Select value={selectedModel} onChange={(e) => setConfigForm((c) => ({ ...c, anthropic: { ...c.anthropic, model: e.target.value } }))}>
            {(MODEL_PRESETS.ollama || []).map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}{p.value && isModelInstalled(p.value) ? " (installed)" : p.value ? " (needs download)" : ""}
              </option>
            ))}
          </Select>
          {/* Custom model input */}
          <Input
            placeholder="Or type a custom model name (e.g. codellama:7b)"
            value={MODEL_PRESETS.ollama.some((p) => p.value === selectedModel) ? "" : selectedModel}
            onChange={(e) => {
              if (e.target.value) setConfigForm((c) => ({ ...c, anthropic: { ...c.anthropic, model: e.target.value } }));
            }}
          />
        </div>
      )}

      {/* Running but model not pulled */}
      {ollamaStatus.running && !modelInstalled && !pulling && selectedModel && (
        <Button size="sm" onClick={() => handlePull()}>
          Download {selectedModel}
        </Button>
      )}

      {/* Pull progress */}
      {pulling && pullEvent && (
        <div className="flex flex-col gap-3 px-4 py-3 rounded-xl border border-amber-200 bg-amber-50">
          <div className="flex items-start gap-2.5">
            <svg className="w-4 h-4 text-amber-500 shrink-0 mt-0.5 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" strokeLinecap="round" /></svg>
            <div>
              <p className="text-xs font-semibold text-amber-800">Downloading {selectedModel}...</p>
              <p className="text-[0.65rem] text-amber-600 mt-0.5">This may take several minutes for larger models.</p>
            </div>
          </div>
          <div className="flex items-center justify-between text-xs text-amber-700">
            <span className="truncate max-w-[80%]">{pullEvent.detail}</span>
            <span className="font-semibold">{Math.round(pullEvent.progress * 100)}%</span>
          </div>
          <div className="w-full h-2 bg-amber-100 rounded-full overflow-hidden">
            <div className="h-full bg-amber-500 rounded-full transition-all duration-300" style={{ width: `${Math.round(pullEvent.progress * 100)}%` }} />
          </div>
        </div>
      )}

      {/* All ready */}
      {ollamaStatus.running && modelInstalled && (
        <div className="px-3 py-2.5 rounded-xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-700 font-medium text-center">
          Ready — {selectedModel} is installed and Ollama is running.
        </div>
      )}

      {/* Available models */}
      {ollamaStatus.running && ollamaStatus.models.length > 0 && (
        <div className="text-[0.65rem] text-zinc-400">
          Installed: {ollamaStatus.models.join(", ")}
        </div>
      )}

      {error && <p className="text-xs text-red-500 bg-red-50 px-3 py-2 rounded-xl">{error}</p>}
    </div>
  );
}

function AnthropicStep({ configForm, setConfigForm, savedConfig, baseUrl }: {
  configForm: ConfigForm;
  setConfigForm: Dispatch<SetStateAction<ConfigForm>>;
  savedConfig: PublicConfig | null;
  baseUrl: string;
}) {
  const provider = configForm.anthropic.provider;
  const keyPresent = Boolean(savedConfig?.anthropic.api_key || configForm.anthropic.api_key.trim());
  const needsKey = provider !== "ollama";
  const presets = MODEL_PRESETS[provider] || [];

  return (
    <div className="flex flex-col gap-6 flex-1">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-zinc-900">Connect your LLM</h2>
        <p className="text-sm text-zinc-500 mt-1">Choose a provider. Ollama runs entirely on your machine.</p>
      </div>
      <div className="flex flex-col gap-5">
        {/* Provider toggle */}
        <Field label="Provider">
          <div className="grid grid-cols-3 gap-2">
            {(["anthropic", "openai", "ollama"] as const).map((p) => (
              <button
                key={p}
                type="button"
                className={cn(
                  "flex flex-col items-center gap-1 px-3 py-3 rounded-xl border text-xs font-semibold transition-all",
                  provider === p
                    ? "border-zinc-900 bg-zinc-900 text-white shadow-sm"
                    : "border-zinc-200 text-zinc-600 hover:border-zinc-300 hover:bg-zinc-50"
                )}
                onClick={() => {
                  const defaultModel = MODEL_PRESETS[p]?.[0]?.value || "";
                  setConfigForm((c) => ({
                    ...c,
                    anthropic: {
                      ...c.anthropic,
                      provider: p,
                      model: defaultModel,
                      base_url: p === "ollama" ? "http://localhost:11434/v1" : "",
                    },
                  }));
                }}
              >
                {p === "anthropic" ? "Anthropic" : p === "openai" ? "OpenAI" : "Ollama (local)"}
              </button>
            ))}
          </div>
        </Field>

        {needsKey && (
          <Field label="API key" htmlFor="api-key" hint={keyPresent ? "Key is saved. Leave blank to keep it." : `Paste your ${provider === "anthropic" ? "Anthropic" : "OpenAI"} API key.`}>
            <Input id="api-key" type="password" placeholder={keyPresent ? "••••••••" : provider === "anthropic" ? "sk-ant-..." : "sk-..."} value={configForm.anthropic.api_key} onChange={(e) => setConfigForm((c) => ({ ...c, anthropic: { ...c.anthropic, api_key: e.target.value } }))} />
          </Field>
        )}

        {provider === "ollama" && (
          <OllamaSetupPanel baseUrl={baseUrl} configForm={configForm} setConfigForm={setConfigForm} />
        )}

        <Field label="Model" htmlFor="model">
          <Select id="model" value={presets.some((p) => p.value === configForm.anthropic.model) ? configForm.anthropic.model : ""} onChange={(e) => setConfigForm((c) => ({ ...c, anthropic: { ...c.anthropic, model: e.target.value } }))}>
            {presets.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </Select>
          {provider === "ollama" && (
            <Input
              className="mt-2"
              placeholder="Or type a custom model name..."
              value={configForm.anthropic.model}
              onChange={(e) => setConfigForm((c) => ({ ...c, anthropic: { ...c.anthropic, model: e.target.value } }))}
            />
          )}
        </Field>

        {provider === "openai" && (
          <Field label="API base URL" hint="Leave blank for default OpenAI endpoint.">
            <Input value={configForm.anthropic.base_url} placeholder="https://api.openai.com/v1" onChange={(e) => setConfigForm((c) => ({ ...c, anthropic: { ...c.anthropic, base_url: e.target.value } }))} />
          </Field>
        )}

        <Field label="Max tokens" htmlFor="max-tokens" hint="Upper limit per response (512–4096).">
          <Input id="max-tokens" type="number" min={512} max={4096} value={configForm.anthropic.max_tokens} onChange={(e) => setConfigForm((c) => ({ ...c, anthropic: { ...c.anthropic, max_tokens: Number(e.target.value) || 1400 } }))} />
        </Field>
      </div>
    </div>
  );
}

function ZoteroStep({ configForm, setConfigForm, baseUrl }: { configForm: ConfigForm; setConfigForm: Dispatch<SetStateAction<ConfigForm>>; baseUrl: string }) {
  const [detecting, setDetecting] = useState(false);
  const [detected, setDetected] = useState(false);
  const hasAttemptedDetect = useRef(false);

  useEffect(() => {
    if (!baseUrl || hasAttemptedDetect.current || configForm.zotero.storage_path) return;
    hasAttemptedDetect.current = true;
    setDetecting(true);
    detectZotero(baseUrl)
      .then((result) => {
        if (result.found) {
          setDetected(true);
          setConfigForm((c) => ({
            ...c,
            zotero: {
              storage_path: result.storage_path || c.zotero.storage_path,
              database_path: result.database_path || c.zotero.database_path,
            },
          }));
        }
      })
      .catch(() => {})
      .finally(() => setDetecting(false));
  }, [baseUrl]);

  return (
    <div className="flex flex-col gap-6 flex-1">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-zinc-900">Point to Zotero</h2>
        <p className="text-sm text-zinc-500 mt-1">Jarvis indexes PDFs in your Zotero storage folder.</p>
      </div>
      <div className="flex flex-col gap-5">
        {detecting && <div className="px-4 py-2.5 rounded-xl bg-zinc-100 text-zinc-500 text-sm text-center">Looking for Zotero...</div>}
        {detected && configForm.zotero.storage_path && (
          <div className="px-4 py-2.5 rounded-xl bg-emerald-50 text-emerald-600 text-sm text-center flex items-center justify-center gap-2">
            <IconCheck className="w-4 h-4" /> Found Zotero at the default location
          </div>
        )}
        <Field label="Storage folder" hint="Contains your PDF attachments. Usually ~/Zotero/storage.">
          <PathPicker label="Storage folder" value={configForm.zotero.storage_path} placeholder="Select your Zotero storage directory..." onPick={async () => { const p = await window.jarvis.pickDirectory(); if (p) setConfigForm((c) => ({ ...c, zotero: { ...c.zotero, storage_path: p } })); }} />
        </Field>
        <Field label="Database (optional)" hint="Enables rich metadata: authors, collections, annotations.">
          <PathPicker label="Database file" value={configForm.zotero.database_path} placeholder="Select zotero.sqlite..." onPick={async () => { const p = await window.jarvis.pickFile([{ name: "SQLite", extensions: ["sqlite", "sqlite3", "db"] }]); if (p) setConfigForm((c) => ({ ...c, zotero: { ...c.zotero, database_path: p } })); }} />
        </Field>
      </div>
    </div>
  );
}

function VaultsStep({ configForm, setConfigForm }: { configForm: ConfigForm; setConfigForm: Dispatch<SetStateAction<ConfigForm>> }) {
  return (
    <div className="flex flex-col gap-6 flex-1">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-zinc-900">Obsidian Vaults</h2>
        <p className="text-sm text-zinc-500 mt-1">Connect vaults so Jarvis can search and write notes.</p>
      </div>
      <div className="flex flex-col gap-4">
        {configForm.obsidian_vaults.map((vault, i) => (
          <div key={vault.id} className="flex flex-col gap-3 p-4 border border-zinc-200 rounded-xl bg-zinc-50/50">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">Vault {i + 1}</span>
              {configForm.obsidian_vaults.length > 1 && (
                <button type="button" className="text-zinc-400 text-xs font-medium px-2 py-0.5 rounded-lg hover:text-red-600 hover:bg-red-50 transition-colors" onClick={() => setConfigForm((c) => ({ ...c, obsidian_vaults: c.obsidian_vaults.filter((v) => v.id !== vault.id) }))}>
                  Remove
                </button>
              )}
            </div>
            <PathPicker label="Vault folder" value={vault.path} placeholder="Click to select vault..." onPick={async () => {
              const p = await window.jarvis.pickDirectory();
              if (p) {
                const name = p.split("/").pop() || "";
                setConfigForm((c) => ({ ...c, obsidian_vaults: c.obsidian_vaults.map((v) => v.id === vault.id ? { ...v, path: p, name: v.name || name } : v) }));
              }
            }} />
            <Field label="Display name">
              <Input value={vault.name} placeholder="e.g. Research Notes" onChange={(e) => setConfigForm((c) => ({ ...c, obsidian_vaults: c.obsidian_vaults.map((v) => v.id === vault.id ? { ...v, name: e.target.value } : v) }))} />
            </Field>
          </div>
        ))}
        <Button variant="outline" className="self-start" onClick={() => setConfigForm((c) => ({ ...c, obsidian_vaults: [...c.obsidian_vaults, blankVault()] }))}>
          + Add another vault
        </Button>
      </div>
    </div>
  );
}

function SpeechSetupProgress({ progress, detail, currentStep }: { progress: number; detail: string; currentStep: string }) {
  const pct = Math.round(progress * 100);
  const stepLabels: Record<string, string> = { vosk: "Vosk STT", piper: "Piper TTS", voice: "Voice model", done: "Complete" };
  return (
    <div className="flex flex-col gap-4 px-4 py-4 rounded-xl border border-amber-200 bg-amber-50">
      <div className="flex items-start gap-2.5">
        <svg className="w-5 h-5 text-amber-500 shrink-0 mt-0.5 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" strokeLinecap="round" /></svg>
        <div>
          <p className="text-sm font-semibold text-amber-800">Downloading {stepLabels[currentStep] || currentStep}...</p>
          <p className="text-xs text-amber-600 mt-0.5">This may take a few minutes depending on your connection. Please don't close the app.</p>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between text-xs text-amber-700">
          <span className="font-medium">{detail}</span>
          <span className="font-semibold">{pct}%</span>
        </div>
        <div className="w-full h-2.5 bg-amber-100 rounded-full overflow-hidden">
          <div className="h-full bg-amber-500 rounded-full transition-all duration-300 ease-out" style={{ width: `${pct}%` }} />
        </div>
      </div>
    </div>
  );
}

function SpeechStep({ baseUrl }: { baseUrl: string }) {
  const [status, setStatus] = useState<SpeechStatus | null>(null);
  const [installing, setInstalling] = useState(false);
  const [progressEvent, setProgressEvent] = useState<SpeechSetupEvent | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (baseUrl) getSpeechStatus(baseUrl).then(setStatus).catch(() => {});
  }, [baseUrl]);

  async function handleInstall() {
    if (!baseUrl) return;
    setInstalling(true);
    setError("");
    setProgressEvent(null);
    try {
      await setupSpeechStreaming(baseUrl, (event) => {
        setProgressEvent(event);
        // Update status items live as each step completes
        if (event.status === "done" || event.step === "done") {
          getSpeechStatus(baseUrl).then(setStatus).catch(() => {});
        }
      });
      setStatus(await getSpeechStatus(baseUrl));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setInstalling(false);
    }
  }

  const items = [
    { label: "Vosk STT", desc: "Real-time local speech recognition (~50 MB)", ready: status?.vosk_ready },
    { label: "Piper TTS", desc: "Local text-to-speech engine (~20 MB)", ready: status?.piper_installed },
    { label: "Voice model", desc: "Amy (en-US) voice (~40 MB)", ready: status?.voice_installed },
  ];

  return (
    <div className="flex flex-col gap-6 flex-1">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-zinc-900">Local Speech</h2>
        <p className="text-sm text-zinc-500 mt-1">Vosk for real-time speech-to-text, Piper for text-to-speech. All local, no cloud.</p>
      </div>
      <div className="flex flex-col gap-2.5">
        {items.map((item) => (
          <div key={item.label} className={cn("flex items-center gap-3 px-4 py-3 border rounded-xl transition-all", item.ready ? "border-emerald-200 bg-emerald-50" : "border-zinc-200 bg-white")}>
            <div className={cn("shrink-0 w-8 h-8 grid place-items-center rounded-full transition-colors", item.ready ? "bg-emerald-100 text-emerald-600" : "bg-zinc-100 text-zinc-400")}>
              {item.ready ? <IconCheck /> : <span className="w-2 h-2 rounded-full bg-zinc-300" />}
            </div>
            <div>
              <strong className="block text-sm font-semibold">{item.label}</strong>
              <span className="block text-xs text-zinc-500">{item.desc}</span>
            </div>
            <span className={cn("ml-auto text-xs font-medium", item.ready ? "text-emerald-600" : "text-zinc-400")}>
              {item.ready ? "Installed" : "Pending"}
            </span>
          </div>
        ))}
      </div>

      {installing && progressEvent && (
        <SpeechSetupProgress progress={progressEvent.progress} detail={progressEvent.detail} currentStep={progressEvent.step} />
      )}

      {status?.ready ? (
        <div className="px-4 py-3 rounded-xl bg-emerald-50 text-emerald-700 text-sm font-medium text-center">All speech models ready.</div>
      ) : (
        <Button onClick={handleInstall} disabled={installing} className="self-center min-w-[200px]">
          {installing ? "Installing..." : "Download & install speech models"}
        </Button>
      )}
      {error && <p className="text-sm text-red-500 bg-red-50 px-4 py-2.5 rounded-xl text-center">{error}</p>}
      {status && !status.piper_supported && (
        <p className="text-sm text-amber-600 bg-amber-50 px-4 py-2.5 rounded-xl">Piper TTS is not available for your platform. STT will still work.</p>
      )}
    </div>
  );
}

function ReadyStep({ onFinish, finishing }: { onFinish: () => void; finishing: boolean }) {
  return (
    <div className="flex flex-col gap-6 flex-1 items-center text-center justify-center">
      <div className="w-16 h-16 grid place-items-center rounded-full bg-emerald-100 text-emerald-600">
        <IconCheck className="w-8 h-8" />
      </div>
      <h1 className="text-2xl font-bold tracking-tight text-zinc-900">You're all set</h1>
      <p className="text-sm leading-relaxed text-zinc-500 max-w-[420px]">
        Jarvis will save your settings and build the local search index. This may take a moment on first run.
      </p>
      <Button className="mt-2 min-w-[200px]" onClick={onFinish} disabled={finishing}>
        {finishing ? "Setting up..." : "Save & build index"}
      </Button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Index browser                                                      */
/* ------------------------------------------------------------------ */

const INDEX_TABS = ["papers", "notes", "zotero_notes", "memories"] as const;
type IndexTab = (typeof INDEX_TABS)[number];
const TAB_LABELS: Record<IndexTab, string> = { papers: "Papers", notes: "Obsidian Notes", zotero_notes: "Zotero Notes", memories: "Memories" };

type ViewMode = "tree" | "flat";

function IconDocument({ className }: { className?: string }) {
  return (
    <svg className={className} width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 1.5h5.5L12 5v7.5a1 1 0 01-1 1H3a1 1 0 01-1-1v-11a1 1 0 011-1z" />
      <path d="M8.5 1.5V5H12" />
    </svg>
  );
}

function IconBook({ className }: { className?: string }) {
  return (
    <svg className={className} width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 1.5h3.5a2 2 0 012 2v9a1.5 1.5 0 00-1.5-1.5H2z" />
      <path d="M12 1.5H8.5a2 2 0 00-2 2v9A1.5 1.5 0 018 11h4z" />
    </svg>
  );
}

function IconNote({ className }: { className?: string }) {
  return (
    <svg className={className} width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 1H3a1 1 0 00-1 1v10a1 1 0 001 1h8a1 1 0 001-1V5L8 1z" />
      <path d="M5 7h4M5 9.5h4M5 4.5h1" />
    </svg>
  );
}

/** Collapsible section wrapper */
function TreeSection({ title, badge, defaultOpen, icon, children }: {
  title: string;
  badge?: string | number;
  defaultOpen?: boolean;
  icon?: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen ?? false);
  return (
    <div className="border border-zinc-200 rounded-xl bg-white overflow-hidden">
      <button
        type="button"
        className="flex items-center gap-2.5 w-full px-4 py-3 text-left hover:bg-zinc-50 transition-colors"
        onClick={() => setOpen(!open)}
      >
        <span className={cn("shrink-0 text-zinc-400 transition-transform duration-150", open && "rotate-90")}>
          <IconChevron />
        </span>
        {icon}
        <span className="flex-1 min-w-0 text-sm font-semibold text-zinc-900 truncate">{title}</span>
        {badge !== undefined && (
          <span className="shrink-0 text-[0.65rem] font-bold text-zinc-400 bg-zinc-100 px-2 py-0.5 rounded-full">{badge}</span>
        )}
      </button>
      {open && <div className="border-t border-zinc-100">{children}</div>}
    </div>
  );
}

/** Single paper row inside a collection tree */
function PaperRow({ paper, onSelect }: { paper: PaperTreeItem; onSelect: (paperId: string) => void }) {
  return (
    <button
      type="button"
      className="flex items-center gap-2.5 w-full px-4 py-2.5 text-left hover:bg-zinc-50 transition-colors border-b border-zinc-50 last:border-b-0"
      onClick={() => onSelect(paper.paper_id)}
    >
      <IconDocument className="shrink-0 text-zinc-400" />
      <div className="flex-1 min-w-0">
        <span className="text-sm text-zinc-800 truncate block">{paper.title}</span>
        <span className="text-[0.68rem] text-zinc-400 block mt-0.5">
          {paper.authors?.split(";")[0]?.trim() || ""}
          {paper.year ? ` · ${paper.year}` : ""}
          {paper.total_pages ? ` · ${paper.total_pages} pages` : ""}
          {paper.total_chunks ? ` · ${paper.total_chunks} chunks` : ""}
        </span>
      </div>
      <IconChevron className="shrink-0 text-zinc-300" />
    </button>
  );
}

/** Chunk detail viewer shown when drilling into a paper/note */
function ChunkViewer({ baseUrl, collection, groupId, groupField, title, onBack }: {
  baseUrl: string;
  collection: string;
  groupId: string;
  groupField: string;
  title: string;
  onBack: () => void;
}) {
  const [items, setItems] = useState<IndexBrowseItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    browseIndex(baseUrl, collection as "papers" | "notes" | "zotero_notes" | "memories", 2000, 0, true)
      .then((res) => {
        const filtered = res.items.filter((item) => String(item.metadata[groupField]) === groupId);
        filtered.sort((a, b) => ((a.metadata.chunk_index as number) || 0) - ((b.metadata.chunk_index as number) || 0));
        setItems(filtered);
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [baseUrl, collection, groupId, groupField]);

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-3 px-5 py-3 border-b border-zinc-200 bg-white shrink-0">
        <button type="button" className="text-zinc-400 hover:text-zinc-900 transition-colors p-1" onClick={onBack}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 11L5 7l4-4" />
          </svg>
        </button>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-bold text-zinc-900 truncate">{title}</h3>
          <span className="text-[0.68rem] text-zinc-400">{items.length} chunks</span>
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {loading && <p className="py-8 text-center text-sm text-zinc-400">Loading chunks...</p>}
        {!loading && items.length === 0 && <p className="py-8 text-center text-sm text-zinc-400">No chunks found.</p>}
        {items.map((chunk, i) => {
          const pageStart = chunk.metadata.page_start as number | undefined;
          const pageEnd = chunk.metadata.page_end as number | undefined;
          const pageLabel = pageStart
            ? pageStart === pageEnd ? `p.${pageStart}` : `pp.${pageStart}-${pageEnd}`
            : "";
          return (
            <div key={chunk.id} className="px-5 py-4 border-b border-zinc-100">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[0.65rem] font-bold text-zinc-400 uppercase tracking-wider">
                  Chunk {(chunk.metadata.chunk_index as number) ?? i}
                </span>
                {pageLabel && (
                  <span className="text-[0.65rem] font-medium text-blue-500 bg-blue-50 px-1.5 py-0.5 rounded">
                    {pageLabel}
                  </span>
                )}
              </div>
              <div className="text-sm text-zinc-700 leading-relaxed prose prose-sm max-w-none">
                <MarkdownContent content={chunk.text} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function IndexBrowser({ baseUrl, onClose }: { baseUrl: string; onClose: () => void }) {
  const [tab, setTab] = useState<IndexTab>("papers");
  const [viewMode, setViewMode] = useState<ViewMode>("tree");
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");

  // Tree data
  const [paperTree, setPaperTree] = useState<PaperTreeResult | null>(null);
  const [noteTree, setNoteTree] = useState<NoteTreeResult | null>(null);
  const [zoteroNoteTree, setZoteroNoteTree] = useState<ZoteroNoteTreeResult | null>(null);

  // Flat data (for memories which don't have tree view)
  const [flatItems, setFlatItems] = useState<IndexBrowseItem[]>([]);
  const [flatTotal, setFlatTotal] = useState(0);

  // Drill-down state
  const [drillDown, setDrillDown] = useState<{ collection: string; groupId: string; groupField: string; title: string } | null>(null);

  // Expanded sections tracking
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set());
  const toggleSection = (key: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  useEffect(() => {
    if (!baseUrl) return;
    setLoading(true);
    setDrillDown(null);
    setFilter("");

    if (tab === "memories") {
      browseIndex(baseUrl, "memories", 500, 0, false)
        .then((res) => { setFlatItems(res.items); setFlatTotal(res.total); })
        .catch(() => { setFlatItems([]); setFlatTotal(0); })
        .finally(() => setLoading(false));
      return;
    }

    if (viewMode === "tree") {
      getIndexTree(baseUrl, tab)
        .then((res) => {
          if (tab === "papers") setPaperTree(res as PaperTreeResult);
          else if (tab === "notes") setNoteTree(res as NoteTreeResult);
          else setZoteroNoteTree(res as ZoteroNoteTreeResult);
        })
        .catch(() => {})
        .finally(() => setLoading(false));
    } else {
      browseIndex(baseUrl, tab, 500, 0, false)
        .then((res) => { setFlatItems(res.items); setFlatTotal(res.total); })
        .catch(() => { setFlatItems([]); setFlatTotal(0); })
        .finally(() => setLoading(false));
    }
  }, [baseUrl, tab, viewMode]);

  // If drilling down into a specific paper/note, show chunk viewer
  if (drillDown) {
    return (
      <div className="flex flex-col h-full min-h-0">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-zinc-200 bg-white shrink-0">
          <h2 className="text-base font-bold text-zinc-900">Index Browser</h2>
          <button type="button" className="text-zinc-400 hover:text-zinc-900 transition-colors p-1" onClick={onClose}><IconX /></button>
        </div>
        <ChunkViewer
          baseUrl={baseUrl}
          collection={drillDown.collection}
          groupId={drillDown.groupId}
          groupField={drillDown.groupField}
          title={drillDown.title}
          onBack={() => setDrillDown(null)}
        />
      </div>
    );
  }

  const filterLower = filter.toLowerCase();

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-zinc-200 bg-white shrink-0">
        <h2 className="text-base font-bold text-zinc-900">Index Browser</h2>
        <button type="button" className="text-zinc-400 hover:text-zinc-900 transition-colors p-1" onClick={onClose}><IconX /></button>
      </div>

      {/* Tabs + view toggle */}
      <div className="flex items-center gap-1 px-5 py-2.5 border-b border-zinc-100 bg-white shrink-0 overflow-x-auto">
        {INDEX_TABS.map((t) => (
          <button
            key={t}
            type="button"
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors",
              tab === t ? "bg-zinc-900 text-white" : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900"
            )}
            onClick={() => setTab(t)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-1">
          {tab !== "memories" && (
            <div className="flex border border-zinc-200 rounded-lg overflow-hidden">
              <button
                type="button"
                className={cn("px-2 py-1 text-[0.65rem] font-medium", viewMode === "tree" ? "bg-zinc-900 text-white" : "text-zinc-500 hover:bg-zinc-100")}
                onClick={() => setViewMode("tree")}
              >
                Tree
              </button>
              <button
                type="button"
                className={cn("px-2 py-1 text-[0.65rem] font-medium", viewMode === "flat" ? "bg-zinc-900 text-white" : "text-zinc-500 hover:bg-zinc-100")}
                onClick={() => setViewMode("flat")}
              >
                Flat
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Filter */}
      <div className="px-5 py-2.5 shrink-0 bg-white border-b border-zinc-100">
        <Input placeholder="Filter by title..." value={filter} onChange={(e) => setFilter(e.target.value)} className="h-8 text-sm" />
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 overflow-y-auto px-5 py-3">
        {loading && <p className="py-8 text-center text-sm text-zinc-400">Loading...</p>}

        {/* ── Papers tree ── */}
        {!loading && tab === "papers" && viewMode === "tree" && paperTree && (
          <div className="flex flex-col gap-2">
            <div className="text-[0.68rem] text-zinc-400 mb-1">{paperTree.total_papers} papers in {paperTree.groups.length} collections</div>
            {paperTree.groups
              .filter((g) => !filterLower || g.name.toLowerCase().includes(filterLower) || g.papers.some((p) => p.title.toLowerCase().includes(filterLower)))
              .map((group) => (
                <TreeSection
                  key={group.name}
                  title={group.name}
                  badge={group.paper_count}
                  icon={<IconFolder className="shrink-0 text-amber-500 w-4 h-4" />}
                  defaultOpen={paperTree.groups.length <= 5}
                >
                  {group.papers
                    .filter((p) => !filterLower || p.title.toLowerCase().includes(filterLower) || p.authors?.toLowerCase().includes(filterLower))
                    .map((paper) => (
                      <PaperRow
                        key={paper.paper_id}
                        paper={paper}
                        onSelect={(id) => setDrillDown({ collection: "papers", groupId: id, groupField: "paper_id", title: paper.title })}
                      />
                    ))}
                </TreeSection>
              ))}
          </div>
        )}

        {/* ── Notes tree ── */}
        {!loading && tab === "notes" && viewMode === "tree" && noteTree && (
          <div className="flex flex-col gap-2">
            <div className="text-[0.68rem] text-zinc-400 mb-1">{noteTree.total_notes} notes in {noteTree.groups.length} vaults</div>
            {noteTree.groups.map((vault) => (
              <TreeSection
                key={vault.name}
                title={vault.name}
                badge={vault.total_notes}
                icon={<IconBook className="shrink-0 text-purple-500 w-4 h-4" />}
                defaultOpen={true}
              >
                {vault.folders
                  .filter((f) => !filterLower || f.path.toLowerCase().includes(filterLower) || f.notes.some((n) => n.title.toLowerCase().includes(filterLower)))
                  .map((folder) => (
                    <div key={folder.path}>
                      <div className="flex items-center gap-2 px-4 py-2 bg-zinc-50 border-b border-zinc-100">
                        <IconFolder className="shrink-0 text-zinc-400 w-3.5 h-3.5" />
                        <span className="text-xs font-medium text-zinc-500">{folder.path}</span>
                        <span className="text-[0.6rem] text-zinc-400 ml-auto">{folder.note_count}</span>
                      </div>
                      {folder.notes
                        .filter((n) => !filterLower || n.title.toLowerCase().includes(filterLower))
                        .map((note) => (
                          <button
                            key={note.note_id}
                            type="button"
                            className="flex items-center gap-2.5 w-full pl-8 pr-4 py-2 text-left hover:bg-zinc-50 transition-colors border-b border-zinc-50 last:border-b-0"
                            onClick={() => setDrillDown({ collection: "notes", groupId: note.note_id, groupField: "note_id", title: note.title })}
                          >
                            <IconNote className="shrink-0 text-zinc-400" />
                            <div className="flex-1 min-w-0">
                              <span className="text-sm text-zinc-800 truncate block">{note.title}</span>
                              <span className="text-[0.68rem] text-zinc-400">{note.total_chunks} chunks</span>
                            </div>
                            <IconChevron className="shrink-0 text-zinc-300" />
                          </button>
                        ))}
                    </div>
                  ))}
              </TreeSection>
            ))}
          </div>
        )}

        {/* ── Zotero Notes tree ── */}
        {!loading && tab === "zotero_notes" && viewMode === "tree" && zoteroNoteTree && (
          <div className="flex flex-col gap-2">
            <div className="text-[0.68rem] text-zinc-400 mb-1">{zoteroNoteTree.total_notes} notes across {zoteroNoteTree.groups.length} papers</div>
            {zoteroNoteTree.groups
              .filter((g) => !filterLower || g.parent_title.toLowerCase().includes(filterLower))
              .map((group) => (
                <TreeSection
                  key={group.parent_title}
                  title={group.parent_title}
                  badge={group.note_count}
                  icon={<IconDocument className="shrink-0 text-blue-500 w-4 h-4" />}
                  defaultOpen={zoteroNoteTree.groups.length <= 10}
                >
                  {group.notes.map((note) => (
                    <button
                      key={note.note_id}
                      type="button"
                      className="flex items-center gap-2.5 w-full px-4 py-2.5 text-left hover:bg-zinc-50 transition-colors border-b border-zinc-50 last:border-b-0"
                      onClick={() => setDrillDown({ collection: "zotero_notes", groupId: note.note_id, groupField: "note_id", title: `${note.parent_title} (${note.note_type})` })}
                    >
                      <span className={cn(
                        "shrink-0 text-[0.6rem] font-bold uppercase px-1.5 py-0.5 rounded",
                        note.note_type === "annotation" ? "bg-amber-50 text-amber-600" : "bg-blue-50 text-blue-600"
                      )}>
                        {note.note_type}
                      </span>
                      <span className="flex-1 min-w-0 text-sm text-zinc-700 truncate">{note.total_chunks} chunks</span>
                      <IconChevron className="shrink-0 text-zinc-300" />
                    </button>
                  ))}
                </TreeSection>
              ))}
          </div>
        )}

        {/* ── Flat view (for any tab or memories) ── */}
        {!loading && (tab === "memories" || viewMode === "flat") && (() => {
          const grouped = new Map<string, { title: string; meta: Record<string, unknown>; chunks: IndexBrowseItem[] }>();
          for (const item of flatItems) {
            const m = item.metadata;
            const groupKey = String(m.paper_id || m.note_id || m.session_id || item.id);
            const title = String(m.title || m.parent_title || m.note_id || m.paper_id || item.id);
            if (!grouped.has(groupKey)) grouped.set(groupKey, { title, meta: m, chunks: [] });
            grouped.get(groupKey)!.chunks.push(item);
          }
          let arr = Array.from(grouped.entries()).map(([key, g]) => ({ key, ...g }));
          if (filterLower) {
            arr = arr.filter((g) => g.title.toLowerCase().includes(filterLower) || g.chunks.some((c) => c.text.toLowerCase().includes(filterLower)));
          }

          if (arr.length === 0) {
            return <p className="py-8 text-center text-sm text-zinc-400">{filter ? "No matches." : `No ${tab} indexed yet.`}</p>;
          }

          return (
            <div className="flex flex-col gap-2">
              <div className="text-[0.68rem] text-zinc-400 mb-1">{flatTotal} chunks / {arr.length} sources</div>
              {arr.map((group) => {
                const groupField = tab === "papers" ? "paper_id" : tab === "notes" ? "note_id" : "";
                return (
                  <div key={group.key} className="border border-zinc-200 rounded-xl bg-white overflow-hidden">
                    <button
                      type="button"
                      className="flex items-center gap-3 w-full px-4 py-3 text-left cursor-pointer transition-colors hover:bg-zinc-50"
                      onClick={() => {
                        if (groupField) {
                          setDrillDown({ collection: tab, groupId: group.key, groupField, title: group.title });
                        }
                      }}
                    >
                      <div className="flex-1 min-w-0">
                        <span className="text-sm font-semibold truncate block">{group.title}</span>
                        <span className="text-[0.7rem] text-zinc-400 block mt-0.5">
                          {group.chunks.length} chunk{group.chunks.length !== 1 ? "s" : ""}
                          {group.meta.authors ? ` · ${String(group.meta.authors).split(";")[0].trim()}` : ""}
                          {group.meta.year ? ` · ${String(group.meta.year)}` : ""}
                          {group.meta.page_start ? ` · pp.${group.meta.page_start}-${group.meta.page_end}` : ""}
                          {group.meta.collections ? ` · ${String(group.meta.collections).split(";")[0].trim()}` : ""}
                        </span>
                      </div>
                      <IconChevron className="shrink-0 text-zinc-400" />
                    </button>
                  </div>
                );
              })}
            </div>
          );
        })()}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Settings panel                                                     */
/* ------------------------------------------------------------------ */

type VoiceInfo = { id: string; label: string; installed: boolean };
type STTModelLocal = { id: string; label: string; size_mb: number; lang: string; installed: boolean };

function SpeechSettingsSection({ baseUrl, configForm, setConfigForm }: { baseUrl: string; configForm: ConfigForm; setConfigForm: Dispatch<SetStateAction<ConfigForm>> }) {
  const [status, setStatus] = useState<SpeechStatus | null>(null);
  const [installing, setInstalling] = useState(false);
  const [progressEvent, setProgressEvent] = useState<SpeechSetupEvent | null>(null);
  const [error, setError] = useState("");
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [downloadingVoice, setDownloadingVoice] = useState<string | null>(null);
  const [sttModels, setSTTModels] = useState<STTModelLocal[]>([]);
  const [downloadingSTT, setDownloadingSTT] = useState<string | null>(null);
  const [sttProgress, setSTTProgress] = useState<{ detail: string; progress: number } | null>(null);

  useEffect(() => {
    if (!baseUrl) return;
    getSpeechStatus(baseUrl).then(setStatus).catch(() => {});
    fetch(`${baseUrl}/api/voices`).then((r) => r.json()).then((d) => setVoices(d.voices || [])).catch(() => {});
    fetch(`${baseUrl}/api/stt/models`).then((r) => r.json()).then((d) => setSTTModels(d.models || [])).catch(() => {});
  }, [baseUrl]);

  async function handleInstall() {
    if (!baseUrl) return;
    setInstalling(true);
    setError("");
    setProgressEvent(null);
    try {
      await setupSpeechStreaming(baseUrl, (event) => {
        setProgressEvent(event);
        if (event.status === "done" || event.step === "done") {
          getSpeechStatus(baseUrl).then(setStatus).catch(() => {});
        }
      });
      setStatus(await getSpeechStatus(baseUrl));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setInstalling(false);
    }
  }

  async function handleDownloadVoice(voiceId: string) {
    setDownloadingVoice(voiceId);
    setError("");
    try {
      const resp = await fetch(`${baseUrl}/api/voices/download/${encodeURIComponent(voiceId)}`, { method: "POST" });
      if (!resp.ok) throw new Error(await resp.text());
      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      if (reader) {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (!line.trim()) continue;
            const ev = JSON.parse(line);
            if (ev.status === "error") throw new Error(ev.detail);
          }
        }
      }
      const d = await fetch(`${baseUrl}/api/voices`).then((r) => r.json());
      setVoices(d.voices || []);
      setConfigForm((c) => ({ ...c, speech: { ...c.speech, voice_id: voiceId, piper_voice_model_path: "" } }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloadingVoice(null);
    }
  }

  async function handleDownloadSTT(modelId: string) {
    setDownloadingSTT(modelId);
    setSTTProgress(null);
    setError("");
    try {
      const resp = await fetch(`${baseUrl}/api/stt/download/${encodeURIComponent(modelId)}`, { method: "POST" });
      if (!resp.ok) throw new Error(await resp.text());
      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      if (reader) {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (!line.trim()) continue;
            const ev = JSON.parse(line);
            if (ev.status === "error") throw new Error(ev.detail);
            setSTTProgress({ detail: ev.detail || "", progress: ev.progress ?? 0 });
          }
        }
      }
      // Refresh model list and auto-select
      const d = await fetch(`${baseUrl}/api/stt/models`).then((r) => r.json());
      setSTTModels(d.models || []);
      setConfigForm((c) => ({ ...c, speech: { ...c.speech, stt_model: modelId } }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloadingSTT(null);
      setSTTProgress(null);
    }
  }

  const statusItems = [
    { label: "Vosk STT", ready: status?.vosk_ready ?? false },
    { label: "Piper TTS", ready: status?.piper_installed ?? false },
    { label: "Voice model", ready: status?.voice_installed ?? false },
  ];

  const currentVoice = configForm.speech?.voice_id || "en_US-amy-medium";
  const currentSpeed = configForm.speech?.speed ?? 1.15;
  const currentSTT = configForm.speech?.stt_model || "vosk-model-small-en-us-0.15";

  return (
    <section className="flex flex-col gap-4">
      <h3 className="text-xs font-bold text-zinc-500 uppercase tracking-wider">Speech</h3>

      {/* Status indicators */}
      <div className="flex flex-col gap-2">
        {statusItems.map((item) => (
          <div key={item.label} className={cn("flex items-center gap-2.5 px-3 py-2 border rounded-lg text-xs", item.ready ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-zinc-200 bg-zinc-50 text-zinc-500")}>
            <span className={cn("shrink-0 w-5 h-5 grid place-items-center rounded-full", item.ready ? "bg-emerald-100" : "bg-zinc-200")}>
              {item.ready ? <IconCheck className="w-3 h-3" /> : <span className="w-1.5 h-1.5 rounded-full bg-zinc-400" />}
            </span>
            <span className="font-medium">{item.label}</span>
            <span className="ml-auto font-medium">{item.ready ? "Installed" : "Not installed"}</span>
          </div>
        ))}
      </div>

      {installing && progressEvent && (
        <SpeechSetupProgress progress={progressEvent.progress} detail={progressEvent.detail} currentStep={progressEvent.step} />
      )}
      {status && !status.ready && (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-zinc-500">Missing components will be downloaded automatically. This may take a few minutes.</p>
          <Button size="sm" onClick={handleInstall} disabled={installing}>
            {installing ? "Installing..." : "Install missing components"}
          </Button>
        </div>
      )}

      <Separator />

      {/* ── STT Model Selection ── */}
      <Field label="Speech-to-text model" hint="Larger models are more accurate but use more memory and take longer to load.">
        <div className="flex flex-col gap-2">
          {sttModels.map((m) => (
            <div
              key={m.id}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2.5 border rounded-xl text-xs transition-all",
                m.id === currentSTT
                  ? "border-zinc-900 bg-zinc-50 ring-1 ring-zinc-900"
                  : m.installed
                    ? "border-zinc-200 hover:border-zinc-300 cursor-pointer"
                    : "border-zinc-100 bg-zinc-50 text-zinc-400"
              )}
              onClick={() => {
                if (m.installed) {
                  setConfigForm((c) => ({ ...c, speech: { ...c.speech, stt_model: m.id } }));
                }
              }}
            >
              <div className="flex-1 min-w-0">
                <span className={cn("font-semibold", m.installed ? "text-zinc-900" : "text-zinc-500")}>{m.label}</span>
              </div>
              {m.installed ? (
                <span className={cn("text-[0.65rem] font-semibold px-2 py-0.5 rounded-full shrink-0", m.id === currentSTT ? "bg-zinc-900 text-white" : "bg-emerald-100 text-emerald-700")}>
                  {m.id === currentSTT ? "Active" : "Installed"}
                </span>
              ) : downloadingSTT === m.id ? (
                <div className="flex items-center gap-2 shrink-0">
                  <div className="w-20 h-1.5 bg-zinc-200 rounded-full overflow-hidden">
                    <div className="h-full bg-zinc-500 rounded-full transition-all duration-300" style={{ width: `${Math.round((sttProgress?.progress ?? 0) * 100)}%` }} />
                  </div>
                  <span className="text-[0.6rem] text-zinc-400 w-8 text-right">{Math.round((sttProgress?.progress ?? 0) * 100)}%</span>
                </div>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={downloadingSTT !== null}
                  onClick={(e) => { e.stopPropagation(); void handleDownloadSTT(m.id); }}
                >
                  Download ({m.size_mb >= 1000 ? `${(m.size_mb / 1000).toFixed(1)} GB` : `${m.size_mb} MB`})
                </Button>
              )}
            </div>
          ))}
          {sttModels.length === 0 && (
            <p className="text-xs text-zinc-400 text-center py-2">Loading models…</p>
          )}
        </div>
      </Field>

      <Separator />

      {/* ── TTS Voice Selection ── */}
      <Field label="Text-to-speech voice" hint="Choose a voice for spoken responses. Click download to install new voices.">
        <div className="flex flex-col gap-2">
          {voices.map((v) => (
            <div
              key={v.id}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2.5 border rounded-xl text-xs cursor-pointer transition-all",
                v.id === currentVoice
                  ? "border-zinc-900 bg-zinc-50 ring-1 ring-zinc-900"
                  : v.installed
                    ? "border-zinc-200 hover:border-zinc-300"
                    : "border-zinc-100 bg-zinc-50 text-zinc-400"
              )}
              onClick={() => {
                if (v.installed) {
                  setConfigForm((c) => ({ ...c, speech: { ...c.speech, voice_id: v.id, piper_voice_model_path: "" } }));
                }
              }}
            >
              <div className="flex-1 min-w-0">
                <span className={cn("font-semibold", v.installed ? "text-zinc-900" : "text-zinc-500")}>{v.label}</span>
                <span className="ml-2 text-zinc-400 font-mono text-[0.65rem]">{v.id}</span>
              </div>
              {v.installed ? (
                <span className={cn("text-[0.65rem] font-semibold px-2 py-0.5 rounded-full shrink-0", v.id === currentVoice ? "bg-zinc-900 text-white" : "bg-emerald-100 text-emerald-700")}>
                  {v.id === currentVoice ? "Active" : "Installed"}
                </span>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={downloadingVoice === v.id}
                  onClick={(e) => { e.stopPropagation(); void handleDownloadVoice(v.id); }}
                >
                  {downloadingVoice === v.id ? "Downloading..." : "Download"}
                </Button>
              )}
            </div>
          ))}
        </div>
      </Field>

      <Separator />

      {/* Speed control */}
      <Field label={`Speaking speed: ${currentSpeed.toFixed(2)}x`} hint="1.0 = normal, higher = faster. Default 1.15x.">
        <div className="flex items-center gap-3">
          <span className="text-xs text-zinc-400 w-8">0.8x</span>
          <input
            type="range"
            min={0.8}
            max={2.0}
            step={0.05}
            value={currentSpeed}
            onChange={(e) => setConfigForm((c) => ({ ...c, speech: { ...c.speech, speed: Number(e.target.value) } }))}
            className="flex-1 accent-zinc-900"
          />
          <span className="text-xs text-zinc-400 w-8">2.0x</span>
        </div>
      </Field>

      {error && <p className="text-xs text-red-500 bg-red-50 px-3 py-2 rounded-lg">{error}</p>}
    </section>
  );
}

type SettingsTab = "models" | "sources" | "speech" | "general";

const SETTINGS_TABS: { id: SettingsTab; label: string; icon: string }[] = [
  { id: "models", label: "Models", icon: "🤖" },
  { id: "sources", label: "Sources", icon: "📚" },
  { id: "speech", label: "Speech", icon: "🎙" },
  { id: "general", label: "General", icon: "⚙️" },
];

function SettingsPanel({ configForm, setConfigForm, savedConfig, saving, onSave, onClose, baseUrl }: {
  configForm: ConfigForm;
  setConfigForm: Dispatch<SetStateAction<ConfigForm>>;
  savedConfig: PublicConfig | null;
  saving: boolean;
  onSave: () => void;
  onClose: () => void;
  baseUrl: string;
}) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("models");

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-200 bg-white shrink-0">
        <h2 className="text-sm font-bold text-zinc-900">Settings</h2>
        <button type="button" className="text-zinc-400 hover:text-zinc-900 transition-colors p-1 rounded-md hover:bg-zinc-100" onClick={onClose}><IconX /></button>
      </div>

      {/* Tab layout: sidebar + content */}
      <div className="flex-1 min-h-0 flex">
        {/* Tab sidebar */}
        <nav className="w-40 shrink-0 border-r border-zinc-100 bg-white py-2 px-2 flex flex-col gap-0.5">
          {SETTINGS_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={cn(
                "flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-colors text-left",
                activeTab === tab.id ? "bg-zinc-100 text-zinc-900 font-semibold" : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-700"
              )}
              onClick={() => setActiveTab(tab.id)}
            >
              <span className="text-sm">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Tab content */}
        <div className="flex-1 min-h-0 overflow-y-auto p-5">
          {activeTab === "models" && (
            <div className="flex flex-col gap-4 max-w-lg">
              <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Language Model</h3>
              <Field label="Provider">
                <Select value={configForm.anthropic.provider} onChange={(e) => {
                  const p = e.target.value as LLMProvider;
                  const defaultModel = MODEL_PRESETS[p]?.[0]?.value || "";
                  setConfigForm((c) => ({
                    ...c,
                    anthropic: { ...c.anthropic, provider: p, model: defaultModel, base_url: p === "ollama" ? "http://localhost:11434/v1" : c.anthropic.base_url },
                  }));
                }}>
                  <option value="anthropic">Anthropic</option>
                  <option value="openai">OpenAI</option>
                  <option value="ollama">Ollama (local)</option>
                </Select>
              </Field>
              {configForm.anthropic.provider !== "ollama" && (
                <Field label="API key" hint="Leave blank to keep saved key.">
                  <Input type="password" placeholder={savedConfig?.anthropic.api_key ? "••••••••" : configForm.anthropic.provider === "anthropic" ? "sk-ant-..." : "sk-..."} value={configForm.anthropic.api_key} onChange={(e) => setConfigForm((c) => ({ ...c, anthropic: { ...c.anthropic, api_key: e.target.value } }))} />
                </Field>
              )}
              <Field label="Model">
                <Select value={configForm.anthropic.model} onChange={(e) => setConfigForm((c) => ({ ...c, anthropic: { ...c.anthropic, model: e.target.value } }))}>
                  {(MODEL_PRESETS[configForm.anthropic.provider] || []).map((p) => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </Select>
                {configForm.anthropic.provider === "ollama" && (
                  <Input className="mt-2" placeholder="Or type a custom model name..." value={configForm.anthropic.model} onChange={(e) => setConfigForm((c) => ({ ...c, anthropic: { ...c.anthropic, model: e.target.value } }))} />
                )}
              </Field>
              {(configForm.anthropic.provider === "openai" || configForm.anthropic.provider === "ollama") && (
                <Field label="API base URL">
                  <Input value={configForm.anthropic.base_url} placeholder={configForm.anthropic.provider === "ollama" ? "http://localhost:11434/v1" : "https://api.openai.com/v1"} onChange={(e) => setConfigForm((c) => ({ ...c, anthropic: { ...c.anthropic, base_url: e.target.value } }))} />
                </Field>
              )}
              <Field label="Max tokens">
                <Input type="number" min={512} max={4096} value={configForm.anthropic.max_tokens} onChange={(e) => setConfigForm((c) => ({ ...c, anthropic: { ...c.anthropic, max_tokens: Number(e.target.value) || 1400 } }))} />
              </Field>
              {configForm.anthropic.provider === "ollama" && (
                <>
                  <Separator />
                  <h4 className="text-xs font-semibold text-zinc-500">Ollama Status</h4>
                  <OllamaSetupPanel baseUrl={baseUrl} configForm={configForm} setConfigForm={setConfigForm} />
                </>
              )}
            </div>
          )}

          {activeTab === "sources" && (
            <div className="flex flex-col gap-6 max-w-lg">
              {/* Zotero */}
              <section className="flex flex-col gap-3">
                <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Zotero</h3>
                <Field label="Storage folder">
                  <PathPicker label="Storage" value={configForm.zotero.storage_path} placeholder="Click to select..." onPick={async () => { const p = await window.jarvis.pickDirectory(); if (p) setConfigForm((c) => ({ ...c, zotero: { ...c.zotero, storage_path: p } })); }} />
                </Field>
                <Field label="Database">
                  <PathPicker label="Database" value={configForm.zotero.database_path} placeholder="Click to select..." onPick={async () => { const p = await window.jarvis.pickFile([{ name: "SQLite", extensions: ["sqlite", "sqlite3", "db"] }]); if (p) setConfigForm((c) => ({ ...c, zotero: { ...c.zotero, database_path: p } })); }} />
                </Field>
              </section>

              <Separator />

              {/* Obsidian */}
              <section className="flex flex-col gap-3">
                <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Obsidian Vaults</h3>
                {configForm.obsidian_vaults.map((vault, i) => (
                  <div key={vault.id} className="flex flex-col gap-2.5 p-3.5 border border-zinc-200 rounded-xl bg-zinc-50/50">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-zinc-400 uppercase">Vault {i + 1}</span>
                      {configForm.obsidian_vaults.length > 1 && (
                        <button type="button" className="text-zinc-400 text-xs hover:text-red-600 transition-colors" onClick={() => setConfigForm((c) => ({ ...c, obsidian_vaults: c.obsidian_vaults.filter((v) => v.id !== vault.id) }))}>Remove</button>
                      )}
                    </div>
                    <PathPicker label="Folder" value={vault.path} placeholder="Select vault..." onPick={async () => {
                      const p = await window.jarvis.pickDirectory();
                      if (p) {
                        const name = p.split("/").pop() || "";
                        setConfigForm((c) => ({ ...c, obsidian_vaults: c.obsidian_vaults.map((v) => v.id === vault.id ? { ...v, path: p, name: v.name || name } : v) }));
                      }
                    }} />
                    <Field label="Name">
                      <Input value={vault.name} placeholder="Display name" onChange={(e) => setConfigForm((c) => ({ ...c, obsidian_vaults: c.obsidian_vaults.map((v) => v.id === vault.id ? { ...v, name: e.target.value } : v) }))} />
                    </Field>
                  </div>
                ))}
                <Button size="sm" variant="outline" onClick={() => setConfigForm((c) => ({ ...c, obsidian_vaults: [...c.obsidian_vaults, blankVault()] }))}>+ Add vault</Button>
              </section>
            </div>
          )}

          {activeTab === "speech" && (
            <div className="max-w-lg">
              <SpeechSettingsSection baseUrl={baseUrl} configForm={configForm} setConfigForm={setConfigForm} />
            </div>
          )}

          {activeTab === "general" && (
            <div className="flex flex-col gap-4 max-w-lg">
              <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Embeddings</h3>
              <Field label="Provider">
                <Select value={configForm.embeddings.provider} onChange={(e) => setConfigForm((c) => ({ ...c, embeddings: { ...c.embeddings, provider: e.target.value as "fastembed" | "openai" } }))}>
                  <option value="fastembed">FastEmbed (local)</option>
                  <option value="openai">OpenAI</option>
                </Select>
              </Field>
              <Field label="Model">
                <Input value={configForm.embeddings.model} onChange={(e) => setConfigForm((c) => ({ ...c, embeddings: { ...c.embeddings, model: e.target.value } }))} />
              </Field>
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="shrink-0 px-5 py-3 border-t border-zinc-200 bg-white flex justify-end">
        <Button onClick={onSave} disabled={saving}>{saving ? "Saving..." : "Save settings"}</Button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main App                                                           */
/* ------------------------------------------------------------------ */

export function App() {
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [savedConfig, setSavedConfig] = useState<PublicConfig | null>(null);
  const [configForm, setConfigForm] = useState<ConfigForm>({ ...EMPTY_CONFIG, obsidian_vaults: [blankVault()] });
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [papers, setPapers] = useState<PaperHit[]>([]);
  const [notes, setNotes] = useState<NoteHit[]>([]);
  const [draft, setDraft] = useState("");
  const [showSetup, setShowSetup] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busyLabel, setBusyLabel] = useState("");
  const [bootError, setBootError] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [autoSpeak, setAutoSpeak] = useState(false);
  const [wizardStep, setWizardStep] = useState<WizardStep>(0);
  const [finishing, setFinishing] = useState(false);
  const [showPanel, setShowPanel] = useState<"" | "settings" | "index">("");
  const [indexStats, setIndexStats] = useState<IndexStats | null>(null);
  const [saving, setSaving] = useState(false);
  const [setupNeed, setSetupNeed] = useState<SetupNeed>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);

  /** Open setup modal AND stop any active conversation/voice */
  function triggerSetup(need: SetupNeed) {
    setSetupNeed(need);
    setIsSending(false);
    if (voiceModeRef.current) {
      stopVoiceConversation();
    }
  }

  /** True when the LLM is properly configured and ready to chat */
  const chatReady = Boolean(savedConfig?.is_complete);

  // Voice conversation mode
  const [voiceMode, setVoiceMode] = useState(false);
  const voiceModeRef = useRef(false); // Ref mirror to avoid stale closures
  const [liveTranscript, setLiveTranscript] = useState("");
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const voiceAnalyserRef = useRef<AnalyserNode | null>(null);
  const voiceAnimFrameRef = useRef<number | null>(null);

  const { toasts, addToast, dismissToast } = useToasts();
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recordingChunksRef = useRef<Blob[]>([]);
  const sessionIdRef = useRef(makeId());
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  /* ---- Bootstrap ---- */

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const rt = await window.jarvis.getRuntimeInfo();
        if (cancelled) return;
        setRuntime(rt);
        setBaseUrl(rt.backendBaseUrl);
        await waitForBackend(rt.backendBaseUrl);
        const cfg = await getConfig(rt.backendBaseUrl);
        if (cancelled) return;
        setSavedConfig(cfg);
        setConfigForm(publicToForm(cfg));
        if (cfg.is_complete) {
          setShowSetup(false);
        } else {
          setShowSetup(true);
          const hasKey = Boolean(cfg.anthropic.api_key);
          const hasModel = Boolean(cfg.anthropic.model?.trim());
          const hasZotero = Boolean(cfg.zotero.storage_path?.trim());
          const hasV = cfg.obsidian_vaults.some((v) => v.name.trim() && v.path.trim());
          if (hasKey && hasModel && hasZotero && hasV) setWizardStep(4);
          else if (hasKey && hasModel && hasZotero) setWizardStep(3);
          else if (hasKey && hasModel) setWizardStep(2);
          else if (hasKey) setWizardStep(1);
          else setWizardStep(0);
        }
      } catch (error) {
        setBootError(error instanceof Error ? error.message : String(error));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void bootstrap();
    return () => {
      cancelled = true;
      if (voiceAnimFrameRef.current) cancelAnimationFrame(voiceAnimFrameRef.current);
      if (mediaRecorderRef.current?.state === "recording") mediaRecorderRef.current.stop();
      mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  /* ---- Wizard navigation ---- */

  function canAdvance(): boolean {
    if (wizardStep === 0) return true;
    if (wizardStep === 1) {
      const hasModel = Boolean(configForm.anthropic.model.trim());
      if (configForm.anthropic.provider === "ollama") return hasModel;
      return Boolean((savedConfig?.anthropic.api_key || configForm.anthropic.api_key.trim()) && hasModel);
    }
    if (wizardStep === 2) return Boolean(configForm.zotero.storage_path.trim());
    if (wizardStep === 3) return hasVaults(configForm.obsidian_vaults);
    return true;
  }

  async function persistCurrentStep(): Promise<void> {
    if (!baseUrl) return;
    setSaving(true);
    try {
      const nextConfig = await saveConfig(baseUrl, sanitizeConfig(configForm));
      setSavedConfig(nextConfig);
      setConfigForm(publicToForm(nextConfig));
    } catch {} finally {
      setSaving(false);
    }
  }

  async function nextWizardStep() {
    if (wizardStep >= TOTAL_STEPS - 1) return;
    if (wizardStep >= 1 && wizardStep <= 3) await persistCurrentStep();
    setWizardStep((wizardStep + 1) as WizardStep);
  }

  async function prevWizardStep() {
    if (wizardStep <= 0) return;
    if (wizardStep >= 1 && wizardStep <= 4) await persistCurrentStep();
    setWizardStep((wizardStep - 1) as WizardStep);
  }

  async function finishSetup() {
    if (!baseUrl) return;
    setFinishing(true);
    try {
      const nextConfig = await saveConfig(baseUrl, sanitizeConfig(configForm));
      setSavedConfig(nextConfig);
      setConfigForm(publicToForm(nextConfig));
      await runIndex(baseUrl, "all");
      addToast("success", "Setup complete", "Your index has been built.");
      setShowSetup(false);
    } catch (error) {
      addToast("error", "Setup error", error instanceof Error ? error.message : String(error));
    } finally {
      setFinishing(false);
    }
  }

  /* ---- Conversations ---- */

  async function fetchConversations() {
    if (!baseUrl) return;
    try {
      setConversations(await listConversations(baseUrl));
    } catch {}
  }

  async function startNewConversation() {
    if (!baseUrl) return;
    try {
      const conv = await createConversation(baseUrl);
      setActiveConvId(conv.id);
      setMessages([]);
      setPapers([]);
      setNotes([]);
      setDraft("");
      await fetchConversations();
    } catch {}
  }

  async function switchConversation(convId: string) {
    if (!baseUrl || convId === activeConvId) return;
    try {
      const conv = await getConversation(baseUrl, convId);
      setActiveConvId(convId);
      // Rebuild UI messages from stored conversation
      const uiMessages: ChatMessage[] = conv.messages.map((m, i) => ({
        id: `conv-${convId}-${i}`,
        role: m.role as ChatMessage["role"],
        content: m.content,
      }));
      setMessages(uiMessages);
      setPapers([]);
      setNotes([]);
      setDraft("");
      setShowPanel("");
    } catch {}
  }

  async function handleDeleteConversation(convId: string) {
    if (!baseUrl) return;
    try {
      await deleteConversation(baseUrl, convId);
      if (activeConvId === convId) {
        setActiveConvId(null);
        setMessages([]);
      }
      await fetchConversations();
    } catch {}
  }

  /* ---- Workspace actions ---- */

  async function fetchStats() {
    if (!baseUrl) return;
    try {
      setIndexStats(await getIndexStats(baseUrl));
    } catch {}
  }

  useEffect(() => {
    if (!showSetup && !loading && baseUrl) {
      void fetchStats();
      void fetchConversations();
    }
  }, [showSetup, loading, baseUrl]);

  async function triggerIndex(scope: "all" | "papers" | "notes") {
    if (!baseUrl) return;
    setBusyLabel(`Indexing ${scope}...`);
    try {
      await runIndex(baseUrl, scope);
      addToast("success", "Indexing complete", `${scope} re-indexed successfully.`);
      await fetchStats();
    } catch (error) {
      addToast("error", "Index error", error instanceof Error ? error.message : String(error));
    } finally {
      setBusyLabel("");
    }
  }

  /* ---- Chat ---- */

  async function handleSend(overrideText?: string) {
    const prompt = (overrideText ?? draft).trim();
    if (!prompt || !baseUrl) return;
    // In voice mode, allow concurrent sends (don't block on isSending)
    if (!voiceModeRef.current && isSending) return;
    const assistantMessageId = makeId();

    // Reset TTS state for new message
    ttsCancelledRef.current = false;
    ttsQueueRef.current = [];
    ttsSentenceBufferRef.current = "";
    if (!overrideText) setDraft("");
    setIsSending(true);

    // Auto-create a conversation if there isn't one active
    let convId = activeConvId;
    if (!convId) {
      try {
        const conv = await createConversation(baseUrl, prompt.slice(0, 80));
        convId = conv.id;
        setActiveConvId(convId);
      } catch {}
    }

    // Build conversation history from existing messages (user + assistant only, with content)
    const history = messages
      .filter((m) => (m.role === "user" || m.role === "assistant") && m.content.trim())
      .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));

    setMessages((c) => [...c, { id: makeId(), role: "user", content: prompt }, { id: assistantMessageId, role: "assistant", content: "" }]);

    // Persist user message
    if (convId) void appendMessage(baseUrl, convId, "user", prompt);

    try {
      let finalAssistantText = "";
      await streamChat(
        baseUrl,
        { message: prompt, history, session_id: sessionIdRef.current, voice_mode: voiceModeRef.current },
        async (event) => {
          await handleStreamEvent(event, assistantMessageId);
          // Capture the final assistant text
          if (event.type === "assistant_done") {
            finalAssistantText = ((event.payload as { message?: string })?.message) || "";
          }
        }
      );
      // Persist assistant response
      if (convId && finalAssistantText) {
        void appendMessage(baseUrl, convId, "assistant", finalAssistantText);
        void fetchConversations(); // refresh sidebar list
      }
    } catch (error) {
      appendStatusMessage(setMessages, `Error: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsSending(false);
    }
  }

  async function handleStreamEvent(event: StreamEvent, assistantMessageId: string) {
    if (event.type === "assistant_delta") {
      setMessages((c) => c.map((m) => (m.id === assistantMessageId ? { ...m, content: `${m.content}${event.delta || ""}` } : m)));
      // Stream text to TTS sentence-by-sentence as it arrives
      if (autoSpeak && event.delta) {
        feedTTSDelta(event.delta);
      }
      return;
    }
    if (event.type === "assistant_done") {
      const payload = (event.payload || {}) as { message?: string };
      if (payload.message) {
        setMessages((c) => c.map((m) => (m.id === assistantMessageId ? { ...m, content: payload.message || "" } : m)));
        // Flush any remaining text in the TTS buffer
        if (autoSpeak) {
          flushTTSBuffer();
        }
      }
      return;
    }
    if (event.type === "status") {
      appendStatusMessage(setMessages, event.message || "Running tool...");
      // Speak tool status in voice mode (only if the LLM didn't already narrate)
      if (autoSpeak && event.tool && !ttsPlayingRef.current && ttsQueueRef.current.length === 0) {
        const toolSpeech: Record<string, string> = {
          search_zotero: "Searching now.",
          search_zotero_metadata: "Looking that up.",
          retrieve_paper_chunks: "Reading the paper.",
          get_paper_metadata: "Getting details.",
          get_paper_notes: "Checking notes.",
          get_paper_annotations: "Checking highlights.",
          search_zotero_notes: "Searching notes.",
          list_zotero_collections: "Listing collections.",
          get_collection_papers: "Getting papers.",
          read_notes: "Checking notes.",
          write_note: "Writing a note.",
          open_pdf: "Opening the PDF.",
        };
        const phrase = toolSpeech[event.tool] || "Working on it.";
        enqueueTTS(phrase);
      }
      return;
    }
    if (event.type === "tool_result") {
      applyToolPayload(event);
      return;
    }
    if (event.type === "error") {
      const msg = event.message || "Unknown error.";
      // Check for setup-required tags like [SETUP_REQUIRED:ollama]
      const setupMatch = msg.match(/\[SETUP_REQUIRED:(\w+)\]/);
      if (setupMatch) {
        const need = setupMatch[1] as "ollama" | "vosk" | "piper";
        triggerSetup(need);
        appendStatusMessage(setMessages, msg.replace(/\[SETUP_REQUIRED:\w+\]\s*/, ""));
      } else {
        appendStatusMessage(setMessages, msg);
      }
    }
  }

  function applyToolPayload(event: StreamEvent) {
    const showableTools = ["search_zotero", "search_zotero_metadata", "retrieve_paper_chunks", "get_paper_notes", "get_paper_annotations"];
    if (event.tool && showableTools.includes(event.tool)) {
      // Insert a tool card into the chat
      setMessages((c) => [
        ...c,
        {
          id: makeId(),
          role: "tool_card" as const,
          content: "",
          toolCard: { tool: event.tool!, payload: event.payload },
        },
      ]);
    }

    if (event.tool === "search_zotero" || event.tool === "search_zotero_metadata") {
      setPapers((c) => mergePapers(c, (event.payload as PaperHit[]) || []));
      return;
    }
    if (event.tool === "retrieve_paper_chunks") {
      const derived = ((event.payload as Array<Record<string, unknown>>) || []).map((item) => ({
        paper_id: String(item.paper_id || ""),
        title: String(item.title || "Untitled paper"),
        file_path: String(item.file_path || ""),
        chunk: String(item.chunk || ""),
      }));
      setPapers((c) => mergePapers(c, derived));
      return;
    }
    if (event.tool === "read_notes") {
      setNotes((event.payload as NoteHit[]) || []);
      return;
    }
    if (event.tool === "write_note") {
      const payload = event.payload as { relative_path?: string; vault_name?: string };
      appendStatusMessage(setMessages, `Note written to ${payload.relative_path || "unknown"} in ${payload.vault_name || "vault"}.`);
    }
  }

  /* ---- Speech (streaming sentence queue) ---- */

  const piperCheckedRef = useRef(false);
  const ttsQueueRef = useRef<string[]>([]);
  const ttsPlayingRef = useRef(false);
  const ttsCancelledRef = useRef(false);
  // Buffer for accumulating text and splitting into sentences
  const ttsSentenceBufferRef = useRef("");

  /** Add a sentence to the TTS queue and start draining if not already playing */
  function enqueueTTS(sentence: string) {
    if (!sentence.trim() || ttsCancelledRef.current) return;
    ttsQueueRef.current.push(sentence.trim());
    if (!ttsPlayingRef.current) {
      void drainTTSQueue();
    }
  }

  /** Drain the TTS queue, playing one sentence at a time */
  async function drainTTSQueue() {
    if (!baseUrl || ttsPlayingRef.current) return;
    ttsPlayingRef.current = true;
    setIsSpeaking(true);

    while (ttsQueueRef.current.length > 0 && !ttsCancelledRef.current) {
      const sentence = ttsQueueRef.current.shift()!;
      try {
        const audioUrl = await synthesizeSpeech(baseUrl, sentence);
        if (ttsCancelledRef.current) break;
        await new Promise<void>((resolve, reject) => {
          const audio = new Audio(audioUrl);
          audioRef.current = audio;
          audio.onended = () => resolve();
          audio.onerror = () => reject(new Error("Audio playback error"));
          audio.play().catch(reject);
        });
      } catch (error) {
        if (!ttsCancelledRef.current) {
          addToast("error", "TTS error", error instanceof Error ? error.message : String(error));
        }
        break;
      }
    }

    ttsPlayingRef.current = false;
    ttsQueueRef.current = [];
    setIsSpeaking(false);
  }

  /** Feed a text delta from the stream — splits into sentences and enqueues complete ones */
  function feedTTSDelta(delta: string) {
    ttsSentenceBufferRef.current += delta;
    // Split on sentence boundaries: . ! ? followed by space or end
    const parts = ttsSentenceBufferRef.current.split(/(?<=[.!?])\s+/);
    // All parts except the last are complete sentences
    for (let i = 0; i < parts.length - 1; i++) {
      const sentence = parts[i].trim();
      if (sentence.length > 5) { // Don't TTS tiny fragments
        enqueueTTS(sentence);
      }
    }
    // Keep the last (possibly incomplete) part in the buffer
    ttsSentenceBufferRef.current = parts[parts.length - 1] || "";
  }

  /** Flush any remaining text in the buffer as a final sentence */
  function flushTTSBuffer() {
    const remaining = ttsSentenceBufferRef.current.trim();
    ttsSentenceBufferRef.current = "";
    if (remaining.length > 5) {
      enqueueTTS(remaining);
    }
  }

  /** Check piper is installed, then speak a full text (non-streaming fallback) */
  async function speakText(text: string) {
    if (!baseUrl || !text.trim()) return;
    if (!piperCheckedRef.current) {
      piperCheckedRef.current = true;
      try {
        const speechSt = await getSpeechStatus(baseUrl);
        if (!speechSt.piper_installed || !speechSt.voice_installed) {
          piperCheckedRef.current = false;
          triggerSetup("piper");
          return;
        }
      } catch {}
    }
    // Use the queue approach for consistency
    ttsCancelledRef.current = false;
    const sentences = text.split(/(?<=[.!?])\s+/).filter((s) => s.trim().length > 5);
    if (sentences.length === 0) sentences.push(text);
    for (const s of sentences) enqueueTTS(s);
  }

  function stopSpeaking() {
    ttsCancelledRef.current = true;
    ttsQueueRef.current = [];
    ttsSentenceBufferRef.current = "";
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    ttsPlayingRef.current = false;
    setIsSpeaking(false);
  }

  async function toggleRecording() {
    if (!baseUrl) return;
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      mediaStreamRef.current = stream;
      recordingChunksRef.current = [];
      setIsRecording(true);

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) recordingChunksRef.current.push(event.data);
      };

      recorder.onstop = async () => {
        setIsRecording(false);
        const blob = new Blob(recordingChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        stream.getTracks().forEach((t) => t.stop());
        mediaStreamRef.current = null;
        mediaRecorderRef.current = null;
        if (!blob.size) return;

        setIsTranscribing(true);
        try {
          const text = await uploadAudio(baseUrl, blob);
          setDraft((c) => [c.trim(), text.trim()].filter(Boolean).join(" ").trim());
        } catch (error) {
          addToast("error", "Transcription error", error instanceof Error ? error.message : String(error));
        } finally {
          setIsTranscribing(false);
        }
      };
      recorder.start();
    } catch (error) {
      setIsRecording(false);
      addToast("error", "Mic error", error instanceof Error ? error.message : String(error));
    }
  }

  /* ---- Voice conversation mode (WebSocket streaming transcription) ---- */

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const scriptNodeRef = useRef<ScriptProcessorNode | null>(null);

  async function startVoiceConversation() {
    if (!baseUrl) return;

    // Check if speech dependencies are installed
    try {
      const speechSt = await getSpeechStatus(baseUrl);
      if (!speechSt.vosk_ready) {
        triggerSetup("vosk");
        return;
      }
    } catch {}

    voiceModeRef.current = true;
    setVoiceMode(true);
    setAutoSpeak(true); // Voice mode = always speak responses

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      mediaStreamRef.current = stream;

      // Set up AudioContext to get raw PCM data
      const audioCtx = new AudioContext({ sampleRate: 16000 });
      audioContextRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);

      // Analyser for speech detection (visual feedback + silence detection)
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0.3;
      source.connect(analyser);
      voiceAnalyserRef.current = analyser;

      // ScriptProcessor to capture raw PCM float32 and send to WebSocket
      // (createScriptProcessor is deprecated but widely supported; AudioWorklet alternative is more complex)
      const scriptNode = audioCtx.createScriptProcessor(4096, 1, 1);
      scriptNodeRef.current = scriptNode;
      source.connect(scriptNode);
      scriptNode.connect(audioCtx.destination); // needed for it to process

      // Connect WebSocket
      const wsUrl = baseUrl.replace(/^http/, "ws") + "/api/audio/stream";
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        // Send config
        ws.send(JSON.stringify({ sample_rate: audioCtx.sampleRate }));
        setIsRecording(true);
      };

      // Track accumulated text from Vosk finals (phrase-level) vs user-triggered END finals
      let accumulatedText = "";
      let sendTimer: ReturnType<typeof setTimeout> | null = null;

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "interim") {
            // Show real-time partial transcript (accumulated + current partial)
            setLiveTranscript((accumulatedText + " " + (data.text || "")).trim());
          } else if (data.type === "final") {
            const text = (data.text || "").trim();
            if (text) {
              accumulatedText = (accumulatedText + " " + text).trim();
              setLiveTranscript(accumulatedText);

              // Reset the silence send timer — user might keep talking
              if (sendTimer) clearTimeout(sendTimer);
              // After 1.5s of no new finals, send the accumulated text
              sendTimer = setTimeout(() => {
                const trimmed = accumulatedText.trim();
                if (!trimmed || !voiceModeRef.current) return;

                // Check for HALT keyword — stop voice conversation
                if (trimmed.toLowerCase().replace(/[^a-z]/g, "") === "halt") {
                  setLiveTranscript("");
                  accumulatedText = "";
                  stopVoiceConversation();
                  return;
                }

                setLiveTranscript("");
                setIsTranscribing(false);
                handleSend(trimmed);
                accumulatedText = "";
                // Tell server to reset recognizer for next utterance
                if (ws.readyState === WebSocket.OPEN) {
                  ws.send("RESET");
                }
              }, 1500);
            }
          } else if (data.type === "error") {
            addToast("error", "Transcription error", data.text || "Unknown error");
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onerror = () => {
        addToast("error", "WebSocket error", "Lost connection to transcription service");
        stopVoiceConversation();
      };

      ws.onclose = () => {
        // Only stop if we didn't initiate the close
        if (voiceModeRef.current) {
          addToast("error", "Connection lost", "Transcription WebSocket closed");
          stopVoiceConversation();
        }
      };

      // Send audio chunks to Vosk — it handles speech detection internally
      scriptNode.onaudioprocess = (e) => {
        if (!voiceModeRef.current || ws.readyState !== WebSocket.OPEN) return;
        const inputData = e.inputBuffer.getChannelData(0);
        ws.send(inputData.buffer.slice(inputData.byteOffset, inputData.byteOffset + inputData.byteLength));
      };
    } catch (error) {
      voiceModeRef.current = false;
      setVoiceMode(false);
      addToast("error", "Mic error", error instanceof Error ? error.message : String(error));
    }
  }

  function stopVoiceConversation() {
    voiceModeRef.current = false;
    setVoiceMode(false);
    setAutoSpeak(false);
    setIsRecording(false);
    setLiveTranscript("");

    if (voiceAnimFrameRef.current) {
      cancelAnimationFrame(voiceAnimFrameRef.current);
      voiceAnimFrameRef.current = null;
    }
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }

    // Close WebSocket
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch {}
      wsRef.current = null;
    }

    // Stop ScriptProcessor
    if (scriptNodeRef.current) {
      scriptNodeRef.current.disconnect();
      scriptNodeRef.current = null;
    }

    // Close AudioContext
    if (audioContextRef.current) {
      try {
        void audioContextRef.current.close();
      } catch {}
      audioContextRef.current = null;
    }

    // Stop media stream
    mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
    mediaStreamRef.current = null;
    mediaRecorderRef.current = null;
    voiceAnalyserRef.current = null;
  }

  // Auto-speak response in voice mode
  useEffect(() => {
    if (!voiceMode) return;
    const lastMsg = messages[messages.length - 1];
    const prevMsg = messages.length > 1 ? messages[messages.length - 2] : null;
    // Check if we just got a complete assistant response
    if (lastMsg?.role === "assistant" && lastMsg.content && !isSending && prevMsg?.role !== "tool_card") {
      void speakText(lastMsg.content);
    }
  }, [isSending]);

  /* ---- Settings save ---- */

  async function saveSettingsFromPanel() {
    if (!baseUrl) return;
    setSaving(true);
    try {
      const nextConfig = await saveConfig(baseUrl, sanitizeConfig(configForm));
      setSavedConfig(nextConfig);
      setConfigForm(publicToForm(nextConfig));
      addToast("success", "Settings saved", "Your configuration has been updated.");
    } catch (error) {
      addToast("error", "Save error", error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }

  /* ---- Loading / Error ---- */

  if (loading) {
    return (
      <div className="h-full grid place-items-center bg-zinc-50">
        <div className="flex flex-col items-center gap-3 animate-[fade-in_400ms_ease-out_both]">
          <div className="w-8 h-8 border-[3px] border-zinc-200 border-t-zinc-900 rounded-full animate-spin" />
          <p className="text-sm text-zinc-500">Starting Jarvis...</p>
        </div>
      </div>
    );
  }

  if (bootError) {
    return (
      <div className="h-full grid place-items-center bg-zinc-50">
        <div className="flex flex-col items-center gap-3 animate-[fade-in_400ms_ease-out_both] max-w-[400px] text-center">
          <div className="w-12 h-12 grid place-items-center rounded-full bg-red-100 text-red-600">
            <IconX className="w-6 h-6" />
          </div>
          <h2 className="text-lg font-bold text-red-600">Startup Error</h2>
          <p className="text-sm text-zinc-500">{bootError}</p>
        </div>
      </div>
    );
  }

  /* ---- Onboarding Wizard ---- */

  if (showSetup) {
    return (
      <div className="h-full grid place-items-center bg-zinc-50 p-6">
        <ToastContainer toasts={toasts} onDismiss={dismissToast} />
        <div className="w-full max-w-[540px] flex flex-col gap-6 animate-[fade-in_300ms_ease-out_both]">
          <StepDots current={wizardStep} total={TOTAL_STEPS} />
          <div className="bg-white border border-zinc-200 rounded-2xl shadow-lg p-8 min-h-[340px] flex flex-col">
            {wizardStep === 0 && <WelcomeStep onNext={nextWizardStep} />}
            {wizardStep === 1 && <AnthropicStep configForm={configForm} setConfigForm={setConfigForm} savedConfig={savedConfig} baseUrl={baseUrl} />}
            {wizardStep === 2 && <ZoteroStep configForm={configForm} setConfigForm={setConfigForm} baseUrl={baseUrl} />}
            {wizardStep === 3 && <VaultsStep configForm={configForm} setConfigForm={setConfigForm} />}
            {wizardStep === 4 && <SpeechStep baseUrl={baseUrl} />}
            {wizardStep === 5 && <ReadyStep onFinish={finishSetup} finishing={finishing} />}
          </div>
          {wizardStep > 0 && (
            <div className="flex items-center justify-between">
              <Button variant="ghost" onClick={() => void prevWizardStep()} disabled={saving}>Back</Button>
              {wizardStep < 5 && (
                <Button onClick={() => void nextWizardStep()} disabled={!canAdvance() || saving}>
                  {saving ? "Saving..." : "Continue"}
                </Button>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  /* ---- Workspace ---- */

  return (
    <div className="h-full overflow-hidden grid grid-cols-[260px_minmax(0,1fr)]">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <SetupModal need={setupNeed} baseUrl={baseUrl} configForm={configForm} setConfigForm={setConfigForm} onClose={() => setSetupNeed(null)} />

      {/* ── Sidebar ── */}
      <aside className="flex flex-col h-full overflow-hidden border-r border-zinc-200 bg-white">
        {/* Sidebar header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-100">
          <span className="text-sm font-bold tracking-tight text-zinc-900">Jarvis</span>
          <Badge tone={busyLabel ? "muted" : "success"}>{busyLabel || "Ready"}</Badge>
        </div>

        {/* New chat + Conversations */}
        <div className="px-3 py-2 border-b border-zinc-100">
          <button
            type="button"
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-zinc-900 text-white text-xs font-semibold hover:bg-zinc-800 transition-colors mb-2"
            onClick={() => void startNewConversation()}
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
            New chat
          </button>
          {conversations.length > 0 && (
            <div className="flex flex-col gap-0.5 max-h-[180px] overflow-y-auto">
              {conversations.map((conv) => (
                <div
                  key={conv.id}
                  className={cn(
                    "group flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs cursor-pointer transition-colors",
                    activeConvId === conv.id
                      ? "bg-zinc-100 text-zinc-900 font-semibold"
                      : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-700"
                  )}
                  onClick={() => void switchConversation(conv.id)}
                >
                  <svg className="w-3 h-3 shrink-0 opacity-40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 0 1-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8Z" /></svg>
                  <span className="flex-1 truncate">{conv.title}</span>
                  <button
                    type="button"
                    className="shrink-0 opacity-0 group-hover:opacity-60 hover:!opacity-100 text-zinc-400 hover:text-red-500 transition-all p-0.5"
                    onClick={(e) => { e.stopPropagation(); void handleDeleteConversation(conv.id); }}
                  >
                    <IconX className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Index stats */}
        <div className="px-4 py-3 border-b border-zinc-100">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[0.68rem] font-bold text-zinc-400 uppercase tracking-wider">Index</span>
            <button
              type="button"
              className="text-[0.68rem] font-semibold text-zinc-400 uppercase tracking-wider hover:text-zinc-900 transition-colors"
              onClick={() => setShowPanel(showPanel === "index" ? "" : "index")}
            >
              Browse
            </button>
          </div>
          <div className="grid grid-cols-4 gap-1">
            {([
              ["papers", indexStats?.papers],
              ["notes", indexStats?.notes],
              ["z-notes", indexStats?.zotero_notes],
              ["mem", indexStats?.memories],
            ] as const).map(([label, count]) => (
              <button
                key={label}
                type="button"
                className="flex flex-col items-center gap-0.5 py-2 rounded-lg bg-zinc-50 hover:bg-zinc-100 transition-colors"
                onClick={() => setShowPanel("index")}
              >
                <span className="text-base font-bold text-zinc-900">{count ?? "—"}</span>
                <span className="text-[0.6rem] font-medium text-zinc-400 uppercase">{label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Actions */}
        <div className="px-4 py-2.5 border-b border-zinc-100 flex gap-1.5 flex-wrap">
          <Button size="sm" variant="outline" disabled={!!busyLabel} onClick={() => void triggerIndex("all")} className="text-xs h-7">
            <IconRefresh className="w-3 h-3 mr-1" /> Reindex
          </Button>
          <Button size="sm" variant="outline" disabled={!!busyLabel} onClick={() => void triggerIndex("papers")} className="text-xs h-7">Papers</Button>
          <Button size="sm" variant="outline" disabled={!!busyLabel} onClick={() => void triggerIndex("notes")} className="text-xs h-7">Notes</Button>
        </div>

        {/* Papers list */}
        <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[0.68rem] font-bold text-zinc-400 uppercase tracking-wider">Papers</span>
            <Badge tone="muted">{papers.length}</Badge>
          </div>
          {papers.length ? (
            <div className="flex flex-col gap-0.5">
              {papers.map((p) => (
                <button
                  key={p.paper_id}
                  type="button"
                  className="flex flex-col px-2.5 py-2 rounded-lg text-left hover:bg-zinc-50 transition-colors"
                  onClick={() => void window.jarvis.openPath(p.file_path)}
                >
                  <span className="text-xs font-semibold text-zinc-900 truncate">{p.title}</span>
                  <span className="text-[0.68rem] text-zinc-400 truncate">{p.file_path.split("/").pop()}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="text-xs text-zinc-400 py-2">Papers appear here after search.</p>
          )}

          <Separator className="my-2" />

          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[0.68rem] font-bold text-zinc-400 uppercase tracking-wider">Notes</span>
            <Badge tone="muted">{notes.length}</Badge>
          </div>
          {notes.length ? (
            <div className="flex flex-col gap-0.5">
              {notes.map((n) => (
                <button
                  key={n.note_id}
                  type="button"
                  className="flex flex-col px-2.5 py-2 rounded-lg text-left hover:bg-zinc-50 transition-colors"
                  onClick={() => void window.jarvis.openPath(n.absolute_path)}
                >
                  <span className="text-xs font-semibold text-zinc-900 truncate">{n.title}</span>
                  <span className="text-[0.68rem] text-zinc-400 truncate">{n.vault_name} / {n.relative_path}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="text-xs text-zinc-400 py-2">Notes appear here after search.</p>
          )}
        </div>

        {/* Settings button */}
        <div className="px-4 py-2.5 border-t border-zinc-100">
          <button
            type="button"
            className={cn(
              "flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm font-medium transition-colors",
              showPanel === "settings" ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-900"
            )}
            onClick={() => setShowPanel(showPanel === "settings" ? "" : "settings")}
          >
            <IconSettings className="w-4 h-4" />
            Settings
          </button>
        </div>
      </aside>

      {/* ── Main ── */}
      <main className="flex flex-col h-full min-h-0 bg-zinc-50">
        {showPanel === "index" ? (
          <IndexBrowser baseUrl={baseUrl} onClose={() => setShowPanel("")} />
        ) : showPanel === "settings" ? (
          <SettingsPanel
            configForm={configForm}
            setConfigForm={setConfigForm}
            savedConfig={savedConfig}
            saving={saving}
            onSave={() => void saveSettingsFromPanel()}
            onClose={() => setShowPanel("")}
            baseUrl={baseUrl}
          />
        ) : (
          <>
            {/* Chat header */}
            <div className="flex items-center justify-between px-5 py-2.5 border-b border-zinc-200 bg-white shrink-0">
              <div className="flex items-center gap-2.5">
                <span className="text-sm font-semibold text-zinc-900">{savedConfig?.anthropic.model || "Model"}</span>
                {isSending && <Badge tone="muted">Thinking...</Badge>}
              </div>
              <div className="flex items-center gap-3">
                {/* Speech status indicators */}
                {isRecording && <RecordingPill />}
                {isTranscribing && <TranscribingPill />}
                {isSpeaking && (
                  <button type="button" onClick={stopSpeaking} className="cursor-pointer">
                    <SpeakingPill />
                  </button>
                )}
                {/* Voice conversation mode toggle */}
                <button
                  type="button"
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors border",
                    voiceMode
                      ? "bg-emerald-50 border-emerald-300 text-emerald-700"
                      : "bg-white border-zinc-200 text-zinc-500 hover:border-zinc-300 hover:text-zinc-900"
                  )}
                  onClick={() => voiceMode ? stopVoiceConversation() : void startVoiceConversation()}
                >
                  <IconMic className="w-3.5 h-3.5" />
                  {voiceMode ? "End conversation" : "Voice chat"}
                </button>
                {/* Auto-speak toggle */}
                <div className="flex items-center gap-2">
                  <IconSpeaker className={cn("w-4 h-4", autoSpeak ? "text-blue-600" : "text-zinc-400")} />
                  <Switch checked={autoSpeak} onCheckedChange={setAutoSpeak} />
                </div>
              </div>
            </div>

            {/* Messages */}
            <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 flex flex-col gap-3">
              {messages.length === 0 && (
                <div className="flex-1 flex flex-col items-center justify-center text-center gap-2">
                  <h2 className="text-base font-semibold text-zinc-900">Ask Jarvis anything about your research</h2>
                  <p className="text-sm text-zinc-400 max-w-[440px] leading-relaxed">
                    Search your Zotero papers, look through notes, or ask Jarvis to summarize a paper.
                  </p>
                </div>
              )}
              {(() => {
                const groups = groupMessages(messages);
                return groups.map((group, gi) => {
                  if (group.kind === "tool_steps") {
                    // Check if this is the latest tool step group (still running)
                    const isLatest = gi === groups.length - 1 || (gi === groups.length - 2 && groups[groups.length - 1].kind === "assistant" && !(groups[groups.length - 1] as { msg: ChatMessage }).msg.content);
                    return <ToolStepsGroup key={`tg-${gi}`} steps={group.steps} isLatest={isLatest && isSending} />;
                  }
                  const msg = group.msg;
                  return (
                    <div
                      key={msg.id}
                      className={cn(
                        "max-w-[min(85%,720px)] animate-[fade-in_200ms_ease-out_both]",
                        msg.role === "user" && "self-end",
                        msg.role === "assistant" && "self-start",
                      )}
                    >
                      {msg.role === "user" ? (
                        <div className="bg-zinc-900 text-white rounded-2xl rounded-br-sm px-4 py-3">
                          <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">{msg.content}</p>
                        </div>
                      ) : (
                        <div className="bg-white border border-zinc-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
                          {msg.content ? (
                            <CitationContent content={msg.content} />
                          ) : (
                            <div className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-zinc-300 animate-pulse" />
                              <div className="w-1.5 h-1.5 rounded-full bg-zinc-300 animate-pulse [animation-delay:150ms]" />
                              <div className="w-1.5 h-1.5 rounded-full bg-zinc-300 animate-pulse [animation-delay:300ms]" />
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                });
              })()}
              <div ref={messagesEndRef} />
            </div>

            {/* Composer */}
            <div className="shrink-0 px-5 py-3 border-t border-zinc-200 bg-white">
              {voiceMode ? (
                <div className="flex flex-col gap-2 py-2">
                  {/* Live transcript display */}
                  {liveTranscript && (
                    <div className="px-3 py-2 mx-auto max-w-[600px] bg-zinc-50 border border-zinc-200 rounded-xl animate-[fade-in_150ms_ease-out_both]">
                      <p className="text-sm text-zinc-700 italic leading-relaxed">&ldquo;{liveTranscript}&rdquo;</p>
                    </div>
                  )}
                  {/* Status bar */}
                  <div className="flex items-center justify-center gap-3">
                    <div className={cn(
                      "flex items-center gap-2 px-4 py-2 rounded-full border transition-all",
                      isRecording && !isTranscribing ? "bg-emerald-50 border-emerald-200" : isTranscribing ? "bg-amber-50 border-amber-200" : isSending ? "bg-blue-50 border-blue-200" : isSpeaking ? "bg-blue-50 border-blue-200" : "bg-zinc-50 border-zinc-200"
                    )}>
                      {isRecording && !isTranscribing && (
                        <>
                          <span className="relative flex h-2.5 w-2.5">
                            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
                          </span>
                          <span className="text-xs font-medium text-emerald-700">
                            {liveTranscript ? "Listening..." : "Speak now..."}
                          </span>
                        </>
                      )}
                      {isTranscribing && (
                        <>
                          <svg className="w-3.5 h-3.5 text-amber-600 animate-spin" viewBox="0 0 16 16" fill="none">
                            <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" opacity="0.25" />
                            <path d="M8 2a6 6 0 014.9 9.46" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                          </svg>
                          <span className="text-xs font-medium text-amber-700">Processing...</span>
                        </>
                      )}
                      {isSending && !isTranscribing && (
                        <>
                          <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
                          <span className="text-xs font-medium text-blue-700">Thinking...</span>
                        </>
                      )}
                      {isSpeaking && !isSending && (
                        <>
                          <IconSpeaker className="w-3.5 h-3.5 text-blue-600" />
                          <span className="text-xs font-medium text-blue-700">Speaking...</span>
                        </>
                      )}
                      {!isRecording && !isTranscribing && !isSending && !isSpeaking && (
                        <span className="text-xs font-medium text-zinc-500">Voice mode active</span>
                      )}
                    </div>
                    <button
                      type="button"
                      className="text-xs text-zinc-400 hover:text-zinc-900 transition-colors"
                      onClick={stopVoiceConversation}
                    >
                      End
                    </button>
                  </div>
                </div>
              ) : !chatReady ? (
                /* Chat disabled — setup incomplete */
                <button
                  type="button"
                  className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-amber-50 border border-amber-200 text-amber-700 text-sm font-medium hover:bg-amber-100 transition-colors"
                  onClick={() => {
                    const provider = savedConfig?.anthropic?.provider || configForm.anthropic.provider;
                    if (provider === "ollama") triggerSetup("ollama");
                    else setShowPanel("settings");
                  }}
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>
                  Setup incomplete — click to configure
                </button>
              ) : (
                <div className="flex items-end gap-2">
                  {/* Voice button */}
                  <button
                    type="button"
                    className={cn(
                      "shrink-0 w-9 h-9 grid place-items-center rounded-xl border transition-colors",
                      isRecording
                        ? "bg-red-50 border-red-300 text-red-600"
                        : "bg-white border-zinc-200 text-zinc-500 hover:border-zinc-300 hover:text-zinc-900"
                    )}
                    onClick={() => void toggleRecording()}
                    title={isRecording ? "Stop recording" : "Start voice input"}
                  >
                    <IconMic />
                  </button>
                  {/* Text input */}
                  <div className="flex-1 min-w-0">
                    <Textarea
                      className="min-h-[40px] max-h-[120px] resize-none rounded-xl text-sm"
                      placeholder="Ask Jarvis..."
                      rows={1}
                      value={draft}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          void handleSend();
                        }
                      }}
                      onChange={(e) => setDraft(e.target.value)}
                    />
                  </div>
                  {/* Send button */}
                  <button
                    type="button"
                    className={cn(
                      "shrink-0 w-9 h-9 grid place-items-center rounded-xl transition-colors",
                      draft.trim() && !isSending
                        ? "bg-zinc-900 text-white hover:bg-zinc-800"
                        : "bg-zinc-100 text-zinc-400 cursor-not-allowed"
                    )}
                    disabled={!draft.trim() || isSending}
                    onClick={() => void handleSend()}
                    title="Send message"
                  >
                    <IconSend />
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
