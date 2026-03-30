export type RuntimeInfo = {
  backendBaseUrl: string;
  userDataPath: string;
  platform: string;
};

export type VaultConfig = {
  id: string;
  name: string;
  path: string;
};

export type LLMProvider = "anthropic" | "openai" | "ollama";

export type ConfigForm = {
  anthropic: {
    provider: LLMProvider;
    api_key: string;
    model: string;
    max_tokens: number;
    base_url: string;
  };
  zotero: {
    database_path: string;
    storage_path: string;
  };
  embeddings: {
    provider: "fastembed" | "openai";
    model: string;
    openai_api_key: string;
    openai_base_url: string;
  };
  speech: {
    stt_model: string;
    piper_executable_path: string;
    piper_voice_model_path: string;
    voice_id: string;
    speed: number;
  };
  obsidian_vaults: VaultConfig[];
};

export type PublicConfig = {
  anthropic: {
    provider: LLMProvider;
    api_key?: string | null;
    model: string;
    max_tokens: number;
    base_url?: string | null;
  };
  zotero: {
    database_path?: string | null;
    storage_path?: string | null;
  };
  embeddings: {
    provider: "fastembed" | "openai";
    model: string;
    openai_api_key?: string | null;
    openai_base_url?: string | null;
  };
  speech: {
    stt_model: string;
    piper_executable_path?: string | null;
    piper_voice_model_path?: string | null;
    voice_id?: string;
    speed?: number;
  };
  obsidian_vaults: VaultConfig[];
  is_complete: boolean;
};

export type ConversationTurn = {
  role: "user" | "assistant";
  content: string;
};

export type ChatRequest = {
  message: string;
  history?: ConversationTurn[];
  session_id: string;
  voice_mode?: boolean;
};

export type StreamEvent = {
  type: string;
  message?: string;
  tool?: string;
  delta?: string;
  payload?: unknown;
};

export type ToolResultCard = {
  tool: string;
  payload: unknown;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "status" | "tool_card";
  content: string;
  toolCard?: ToolResultCard;
};

export type PaperHit = {
  paper_id: string;
  title: string;
  file_path: string;
  authors?: string;
  year?: string;
  score?: number;
  chunk?: string;
  page_start?: number;
  page_end?: number;
};

export type NoteHit = {
  note_id: string;
  title: string;
  vault_name: string;
  relative_path: string;
  absolute_path: string;
  excerpt: string;
  score?: number;
};

export type ZoteroDetectResult = {
  found: boolean;
  storage_path: string | null;
  database_path: string | null;
};

export type SpeechStatus = {
  whisper_ready: boolean;
  vosk_ready: boolean;
  piper_installed: boolean;
  voice_installed: boolean;
  piper_supported: boolean;
  ready: boolean;
};

export type SpeechSetupResult = {
  vosk: string;
  piper: string;
  voice: string;
  ready: boolean;
};

export type STTModelInfo = {
  id: string;
  label: string;
  size_mb: number;
  lang: string;
  installed: boolean;
};

export type IndexStats = {
  papers: number;
  notes: number;
  memories: number;
  zotero_notes: number;
};

export type IndexBrowseItem = {
  id: string;
  text: string;
  metadata: Record<string, unknown>;
};

export type IndexBrowseResult = {
  total: number;
  items: IndexBrowseItem[];
};

// Tree types for hierarchical browsing
export type PaperTreeItem = {
  paper_id: string;
  title: string;
  authors: string;
  year: string;
  tags: string;
  total_chunks: number;
  total_pages: number;
};

export type PaperCollectionGroup = {
  name: string;
  type: "collection";
  paper_count: number;
  papers: PaperTreeItem[];
};

export type PaperTreeResult = {
  groups: PaperCollectionGroup[];
  total_papers: number;
};

export type NoteTreeItem = {
  note_id: string;
  title: string;
  relative_path: string;
  total_chunks: number;
};

export type NoteFolderGroup = {
  path: string;
  note_count: number;
  notes: NoteTreeItem[];
};

export type NoteVaultGroup = {
  name: string;
  type: "vault";
  folder_count: number;
  total_notes: number;
  folders: NoteFolderGroup[];
};

export type NoteTreeResult = {
  groups: NoteVaultGroup[];
  total_notes: number;
};

export type ZoteroNoteInfo = {
  note_id: string;
  note_type: string;
  parent_title: string;
  collections: string;
  total_chunks: number;
};

export type ZoteroNoteGroup = {
  parent_title: string;
  notes: ZoteroNoteInfo[];
  note_count: number;
};

export type ZoteroNoteTreeResult = {
  groups: ZoteroNoteGroup[];
  total_notes: number;
};
