import { app, BrowserWindow, dialog, ipcMain, session, shell } from "electron";
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const rendererUrl = process.env.ROXANNE_RENDERER_URL;
const backendBaseUrl = process.env.ROXANNE_BACKEND_URL || "http://127.0.0.1:8000";

let backendProcess: ChildProcess | null = null;
let mainWindow: BrowserWindow | null = null;

// ── Unmute origin pre-bootstrap ────────────────────────────────────────────
// `navigator.mediaDevices` is only exposed in a secure context. A
// self-signed HTTPS origin (or plain HTTP on a non-localhost host) does not
// qualify — even when we approve the cert programmatically. To make the
// embedded Unmute window's microphone work, we have to register the user's
// Unmute origin with Chromium's "treat as secure" allowlist BEFORE
// app.whenReady() fires. So we peek at the saved config at startup, parse
// out the Unmute URL, and pass it into Chromium via command-line switches.
// This means changing the URL requires restarting Roxanne — which we surface
// in the UI separately.
function readUnmuteOriginsFromConfig(): string[] {
  try {
    // Same path the backend uses (apps/backend/roxanne_backend/main.py /api/config writes here).
    // app.getPath() isn't available before `whenReady`, so derive it manually.
    // Honor ROXANNE_HOME so e2e tests can swap in an isolated config dir.
    const roxanneHome = process.env.ROXANNE_HOME;
    let configPath: string;
    if (roxanneHome) {
      configPath = path.join(roxanneHome, "config.json");
    } else {
      const home = process.env.HOME || process.env.USERPROFILE || "";
      if (!home) return [];
      configPath = path.join(home, "Library", "Application Support", "roxanne-desktop", "config.json");
    }
    if (!fs.existsSync(configPath)) return [];
    const data = JSON.parse(fs.readFileSync(configPath, "utf8")) as {
      speech?: { unmute_url?: string | null };
    };
    const raw = (data.speech?.unmute_url || "").trim();
    if (!raw) return [];
    const parsed = new URL(raw);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return [];
    // Register both http and https variants of the same origin so the
    // window's auto-upgrade still hits the allowlist.
    const httpOrigin = `http://${parsed.host}`;
    const httpsOrigin = `https://${parsed.host}`;
    return Array.from(new Set([httpOrigin, httpsOrigin]));
  } catch {
    return [];
  }
}

const unmuteSecureOrigins = readUnmuteOriginsFromConfig();
if (unmuteSecureOrigins.length) {
  app.commandLine.appendSwitch(
    "unsafely-treat-insecure-origin-as-secure",
    unmuteSecureOrigins.join(","),
  );
  // Required so the switch above takes effect for getUserMedia.
  app.commandLine.appendSwitch("disable-features", "BlockInsecurePrivateNetworkRequests");
}

function repoRoot() {
  return path.resolve(__dirname, "../../..");
}

function backendWorkingDirectory() {
  return path.join(repoRoot(), "apps", "backend");
}

function developmentPythonPath() {
  const venvPython = process.platform === "win32"
    ? path.join(backendWorkingDirectory(), ".venv", "Scripts", "python.exe")
    : path.join(backendWorkingDirectory(), ".venv", "bin", "python3");
  return fs.existsSync(venvPython) ? venvPython : "python3";
}

function desktopProjectDirectory() {
  return path.join(repoRoot(), "apps", "desktop");
}

function developmentAppIconPath() {
  const candidate = path.join(desktopProjectDirectory(), "build", "icon.png");
  return fs.existsSync(candidate) ? candidate : undefined;
}

function packagedBackendPath() {
  const backendDir = path.join(process.resourcesPath, "backend");
  const candidates = process.platform === "win32"
    ? [path.join(backendDir, "roxanne-backend.exe"), path.join(backendDir, "roxanne-backend")]
    : [path.join(backendDir, "roxanne-backend")];

  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

function backendEnvironment() {
  return {
    ...process.env,
    ROXANNE_HOME: process.env.ROXANNE_HOME || app.getPath("userData"),
    ROXANNE_HOST: "127.0.0.1",
    ROXANNE_PORT: "8000",
    ROXANNE_SECRET_STORE: process.env.ROXANNE_SECRET_STORE || "local",
    ROXANNE_DESKTOP_APP: "1",
  };
}

function startBackend() {
  if (backendProcess || process.env.ROXANNE_SKIP_BACKEND_SPAWN === "1") {
    return;
  }

  if (process.env.ROXANNE_BACKEND_CMD) {
    backendProcess = spawn(process.env.ROXANNE_BACKEND_CMD, {
      cwd: repoRoot(),
      env: backendEnvironment(),
      shell: true,
    });
  } else if (app.isPackaged) {
    const bundledBackend = packagedBackendPath();
    if (!bundledBackend) {
      dialog.showErrorBox(
        "Backend Missing",
        "Roxanne could not find its bundled backend executable. Reinstall the app or rebuild the release package."
      );
      return;
    }

    backendProcess = spawn(bundledBackend, [], {
      cwd: path.dirname(bundledBackend),
      env: backendEnvironment(),
    });
  } else {
    backendProcess = spawn(
      developmentPythonPath(),
      [
        "-m",
        "uvicorn",
        "roxanne_backend.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--app-dir",
        backendWorkingDirectory(),
      ],
      {
        cwd: repoRoot(),
        env: backendEnvironment(),
      }
    );
  }

  backendProcess.stdout?.on("data", (chunk) => {
    process.stdout.write(`[roxanne-backend] ${chunk}`);
  });

  backendProcess.stderr?.on("data", (chunk) => {
    process.stderr.write(`[roxanne-backend] ${chunk}`);
  });

  backendProcess.on("exit", () => {
    backendProcess = null;
  });

  backendProcess.on("error", (error) => {
    dialog.showErrorBox(
      "Backend Launch Failed",
      `Roxanne could not start its local backend.\n\n${error.message}`
    );
    backendProcess = null;
  });
}

function stopBackend() {
  if (!backendProcess) {
    return;
  }
  backendProcess.kill();
  backendProcess = null;
}

async function createWindow() {
  const isMac = process.platform === "darwin";
  const windowIcon = !isMac ? developmentAppIconPath() : undefined;
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 980,
    minWidth: 1160,
    minHeight: 780,
    backgroundColor: "#ffffff",
    titleBarStyle: isMac ? "hiddenInset" : "hidden",
    ...(isMac ? { trafficLightPosition: { x: 16, y: 16 } } : {}),
    ...(windowIcon ? { icon: windowIcon } : {}),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (rendererUrl) {
    await mainWindow.loadURL(rendererUrl);
  } else {
    await mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

app.whenReady().then(async () => {
  if (process.platform === "darwin") {
    const dockIcon = developmentAppIconPath();
    if (dockIcon) {
      app.dock.setIcon(dockIcon);
    }
  }

  startBackend();
  await createWindow();

  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  stopBackend();
});

ipcMain.handle("roxanne:get-runtime-info", async () => {
  return {
    backendBaseUrl,
    userDataPath: app.getPath("userData"),
    platform: process.platform,
  };
});

ipcMain.handle("roxanne:pick-directory", async () => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    properties: ["openDirectory"],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle("roxanne:pick-file", async (_, filters?: Electron.FileFilter[]) => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    properties: ["openFile"],
    filters,
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle("roxanne:open-path", async (_, targetPath: string) => {
  const error = await shell.openPath(targetPath);
  return { ok: !error, error };
});

let unmuteWindow: BrowserWindow | null = null;
const unmuteTrustedHosts = new Set<string>();

function isLocalHost(host: string): boolean {
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

ipcMain.handle("roxanne:open-unmute", async (_, rawUrl: string) => {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    return { ok: false, error: "Invalid Unmute URL" };
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return { ok: false, error: "Unmute URL must be http or https" };
  }

  // The Unmute origin is registered as "treat as secure" via a Chromium
  // switch at app startup (see readUnmuteOriginsFromConfig at the top of
  // this file). That makes getUserMedia available on http://, so we don't
  // auto-upgrade here. We do still trust the cert if the user explicitly
  // typed an https URL with a self-signed cert.
  unmuteTrustedHosts.add(parsed.host);

  // Use a dedicated partition so we can scope permissions and cert overrides
  // without touching the main Roxanne renderer's session.
  const sessionPartition = "persist:unmute";
  const unmuteSession = session.fromPartition(sessionPartition);

  // 1) Approve mic / camera / display-media for the Unmute origin.
  unmuteSession.setPermissionRequestHandler((webContents, permission, callback) => {
    const url = webContents.getURL();
    let host = "";
    try { host = new URL(url).host; } catch {}
    const allowed = unmuteTrustedHosts.has(host) && (
      permission === "media" ||
      permission === "audioCapture" ||
      permission === "videoCapture" ||
      permission === "display-capture"
    );
    callback(allowed);
  });
  unmuteSession.setPermissionCheckHandler((_wc, permission, requestingOrigin) => {
    let host = "";
    try { host = new URL(requestingOrigin).host; } catch {}
    return unmuteTrustedHosts.has(host) && (
      permission === "media" ||
      permission === "audioCapture" ||
      permission === "videoCapture" ||
      permission === "display-capture"
    );
  });

  // 2) Trust the self-signed cert for the configured Unmute host only.
  unmuteSession.setCertificateVerifyProc((req, callback) => {
    if (unmuteTrustedHosts.has(req.hostname) || unmuteTrustedHosts.has(`${req.hostname}:443`)) {
      callback(0); // 0 = trust the certificate
    } else {
      callback(-3); // use Chromium's default verdict
    }
  });

  if (unmuteWindow && !unmuteWindow.isDestroyed()) {
    unmuteWindow.focus();
    await unmuteWindow.loadURL(parsed.toString());
    return { ok: true, error: "" };
  }

  unmuteWindow = new BrowserWindow({
    width: 1100,
    height: 820,
    title: "Unmute (voice)",
    backgroundColor: "#000000",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      partition: sessionPartition,
      // Unmute is a third-party site; do not share preload or session with the
      // main Roxanne renderer.
    },
  });

  // Belt-and-suspenders: also handle certificate-error on the WebContents.
  unmuteWindow.webContents.on("certificate-error", (event, url, _err, _cert, callback) => {
    let host = "";
    try { host = new URL(url).host; } catch {}
    if (unmuteTrustedHosts.has(host)) {
      event.preventDefault();
      callback(true);
    } else {
      callback(false);
    }
  });

  unmuteWindow.on("closed", () => {
    unmuteWindow = null;
  });
  await unmuteWindow.loadURL(parsed.toString());
  return { ok: true, error: "" };
});

ipcMain.handle("roxanne:open-pdf-page", async (_, targetPath: string, page: number) => {
  // Try to open via Zotero's URL scheme first (handles page navigation)
  // Zotero stores PDFs in storage/<KEY>/ folders — extract the key
  const match = targetPath.match(/storage[/\\]([A-Z0-9]{8})[/\\]/);
  if (match) {
    const itemKey = match[1];
    const zoteroUrl = `zotero://open-pdf/library/items/${itemKey}?page=${page}`;
    try {
      await shell.openExternal(zoteroUrl);
      return { ok: true, error: "" };
    } catch {
      // Fall through to default open
    }
  }
  // Fallback: open the file normally (can't specify page without Zotero)
  const error = await shell.openPath(targetPath);
  return { ok: !error, error };
});
