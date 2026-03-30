import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const rendererUrl = process.env.ROXANNE_RENDERER_URL;
const backendBaseUrl = process.env.ROXANNE_BACKEND_URL || "http://127.0.0.1:8000";

let backendProcess: ChildProcess | null = null;
let mainWindow: BrowserWindow | null = null;

function repoRoot() {
  return path.resolve(__dirname, "../../..");
}

function backendWorkingDirectory() {
  return path.join(repoRoot(), "apps", "backend");
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
  };
}

function startBackend() {
  if (backendProcess) {
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
    // Use the project venv Python if it exists, otherwise fall back to python3
    const venvPython = path.join(backendWorkingDirectory(), ".venv", "bin", "python3");
    const pythonPath = fs.existsSync(venvPython) ? venvPython : "python3";

    backendProcess = spawn(
      pythonPath,
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
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 980,
    minWidth: 1160,
    minHeight: 780,
    backgroundColor: "#ffffff",
    titleBarStyle: isMac ? "hiddenInset" : "hidden",
    ...(isMac ? { trafficLightPosition: { x: 16, y: 16 } } : {}),
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
