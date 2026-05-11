import { test as base, _electron, type ElectronApplication, type Page } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Path to the packaged Roxanne.app — produced by `electron-builder --dir`.
// Tests assume `apps/desktop/release/mac-arm64/Roxanne.app` is up-to-date.
const REPO_ROOT = path.resolve(__dirname, "../../../..");
const APP_PATH = path.join(REPO_ROOT, "apps/desktop/release/mac-arm64/Roxanne.app");
const APP_EXEC = path.join(APP_PATH, "Contents/MacOS/Roxanne");

// Where the BAG bearer token lives (so tests can drive the LLM through Bedrock).
const BAG_ENV_FILE = path.join(os.homedir(), "code-projects/tools/bedrock-access-gateway/.env.local");

const FAKE_MIC_WAV = path.resolve(__dirname, "../fixtures/fake-mic.wav");

export const UNMUTE_URL = process.env.ROXANNE_TEST_UNMUTE_URL || "http://54.92.132.37";

export type TestConfig = {
  bagApiKey: string;
  unmuteUrl: string;
  voiceId: string;
};

export function loadBagApiKey(): string {
  if (!fs.existsSync(BAG_ENV_FILE)) {
    throw new Error(`Missing ${BAG_ENV_FILE} — Bedrock proxy not set up locally`);
  }
  const txt = fs.readFileSync(BAG_ENV_FILE, "utf8");
  const m = txt.match(/^API_KEY=(.+)$/m);
  if (!m) throw new Error(`No API_KEY= line in ${BAG_ENV_FILE}`);
  return m[1].trim();
}

/** Build a complete config.json that reaches `is_complete: true` so the chat
 *  endpoints work end-to-end without onboarding. The api_key here lands in the
 *  same encrypted secret store the running app uses. */
export function makeConfigJson(overrides: Partial<TestConfig> = {}): unknown {
  const apiKey = overrides.bagApiKey ?? loadBagApiKey();
  const unmuteUrl = overrides.unmuteUrl ?? UNMUTE_URL;
  const voiceId = overrides.voiceId ?? "Watercooler";
  return {
    anthropic: {
      provider: "openai",
      api_key: apiKey,
      model: "us.anthropic.claude-opus-4-6-v1",
      max_tokens: 1024,
      max_tool_loops: 6,
      base_url: "http://127.0.0.1:8001/api/v1",
    },
    zotero: { database_path: null, storage_path: path.join(os.homedir(), "Zotero") },
    embeddings: {
      provider: "fastembed",
      model: "BAAI/bge-base-en-v1.5",
      openai_api_key: null,
      openai_base_url: null,
    },
    speech: {
      stt_model: "small",
      voice_id: voiceId,
      speed: 1.15,
      unmute_url: unmuteUrl,
      tts_provider: "unmute",
    },
    obsidian_vaults: [{ name: "memory", path: path.join(os.homedir(), "code-projects/memory") }],
  };
}

export type Fixtures = {
  app: ElectronApplication;
  page: Page;
  roxanneHome: string;
};

export const test = base.extend<Fixtures>({
  /** Per-test ROXANNE_HOME so we don't clobber the user's real settings. */
  // eslint-disable-next-line no-empty-pattern
  roxanneHome: async ({}, use) => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "roxanne-e2e-"));
    fs.writeFileSync(
      path.join(dir, "config.json"),
      JSON.stringify(makeConfigJson(), null, 2),
    );
    await use(dir);
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch {}
  },

  app: async ({ roxanneHome }, use) => {
    if (!fs.existsSync(APP_EXEC)) {
      throw new Error(
        `${APP_EXEC} missing. Run \`npm --workspace apps/desktop run build && npx electron-builder --dir --publish never\` first.`,
      );
    }
    const app = await _electron.launch({
      executablePath: APP_EXEC,
      args: [
        // Auto-grant getUserMedia without prompting; pipe a known WAV in as
        // the "microphone" so we can test the audio pipeline deterministically.
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        `--use-file-for-fake-audio-capture=${FAKE_MIC_WAV}`,
      ],
      env: {
        ...process.env,
        ROXANNE_HOME: roxanneHome,
      },
      timeout: 60_000,
    });
    await use(app);
    await app.close();
  },

  page: async ({ app }, use) => {
    const page = await app.firstWindow({ timeout: 60_000 });
    await page.waitForLoadState("domcontentloaded");
    // Wait for the backend to bind on 8000 (it spawns from main.ts on app ready).
    // We poll via the renderer so we don't need to add a Node-side fetch.
    await page.waitForFunction(
      async () => {
        try {
          const r = await fetch("http://127.0.0.1:8000/health");
          return r.ok;
        } catch { return false; }
      },
      undefined,
      { timeout: 90_000 },
    );
    await use(page);
  },
});

export { expect } from "@playwright/test";
