import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import { spawn, type ChildProcess } from "node:child_process";
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

function startBackend() {
  if (backendProcess) {
    return;
  }

  if (process.env.ROXANNE_BACKEND_CMD) {
    backendProcess = spawn(process.env.ROXANNE_BACKEND_CMD, {
      cwd: repoRoot(),
      env: process.env,
      shell: true,
    });
  } else {
    // Use the project venv Python if it exists, otherwise fall back to python3
    const venvPython = path.join(backendWorkingDirectory(), ".venv", "bin", "python3");
    const fs = require("node:fs");
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
        env: process.env,
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
