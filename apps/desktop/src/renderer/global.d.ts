import type { RuntimeInfo } from "./types";

declare global {
  interface Window {
    roxanne: {
      getRuntimeInfo: () => Promise<RuntimeInfo>;
      pickDirectory: () => Promise<string | null>;
      pickFile: (filters?: Electron.FileFilter[]) => Promise<string | null>;
      openPath: (targetPath: string) => Promise<{ ok: boolean; error: string }>;
      openPdfAtPage: (targetPath: string, page: number) => Promise<{ ok: boolean; error: string }>;
      openUnmute: (url: string) => Promise<{ ok: boolean; error: string }>;
    };
  }
}

export {};
