"use strict";
var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));

// src/main/main.ts
var import_electron = require("electron");
var import_node_child_process = require("child_process");
var import_node_path = __toESM(require("path"));
var rendererUrl = process.env.JARVIS_RENDERER_URL;
var backendBaseUrl = process.env.JARVIS_BACKEND_URL || "http://127.0.0.1:8000";
var backendProcess = null;
var mainWindow = null;
function repoRoot() {
  return import_node_path.default.resolve(__dirname, "../../..");
}
function backendWorkingDirectory() {
  return import_node_path.default.join(repoRoot(), "apps", "backend");
}
function startBackend() {
  if (backendProcess) {
    return;
  }
  if (process.env.JARVIS_BACKEND_CMD) {
    backendProcess = (0, import_node_child_process.spawn)(process.env.JARVIS_BACKEND_CMD, {
      cwd: repoRoot(),
      env: process.env,
      shell: true
    });
  } else {
    const venvPython = import_node_path.default.join(backendWorkingDirectory(), ".venv", "bin", "python3");
    const fs = require("fs");
    const pythonPath = fs.existsSync(venvPython) ? venvPython : "python3";
    backendProcess = (0, import_node_child_process.spawn)(
      pythonPath,
      [
        "-m",
        "uvicorn",
        "jarvis_backend.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--app-dir",
        backendWorkingDirectory()
      ],
      {
        cwd: repoRoot(),
        env: process.env
      }
    );
  }
  backendProcess.stdout?.on("data", (chunk) => {
    process.stdout.write(`[jarvis-backend] ${chunk}`);
  });
  backendProcess.stderr?.on("data", (chunk) => {
    process.stderr.write(`[jarvis-backend] ${chunk}`);
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
  mainWindow = new import_electron.BrowserWindow({
    width: 1480,
    height: 980,
    minWidth: 1160,
    minHeight: 780,
    backgroundColor: "#f8f9fa",
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    webPreferences: {
      preload: import_node_path.default.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  if (rendererUrl) {
    await mainWindow.loadURL(rendererUrl);
  } else {
    await mainWindow.loadFile(import_node_path.default.join(__dirname, "..", "dist", "index.html"));
  }
}
import_electron.app.whenReady().then(async () => {
  startBackend();
  await createWindow();
  import_electron.app.on("activate", async () => {
    if (import_electron.BrowserWindow.getAllWindows().length === 0) {
      await createWindow();
    }
  });
});
import_electron.app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    import_electron.app.quit();
  }
});
import_electron.app.on("before-quit", () => {
  stopBackend();
});
import_electron.ipcMain.handle("jarvis:get-runtime-info", async () => {
  return {
    backendBaseUrl,
    userDataPath: import_electron.app.getPath("userData"),
    platform: process.platform
  };
});
import_electron.ipcMain.handle("jarvis:pick-directory", async () => {
  const result = await import_electron.dialog.showOpenDialog(mainWindow, {
    properties: ["openDirectory"]
  });
  return result.canceled ? null : result.filePaths[0];
});
import_electron.ipcMain.handle("jarvis:pick-file", async (_, filters) => {
  const result = await import_electron.dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    filters
  });
  return result.canceled ? null : result.filePaths[0];
});
import_electron.ipcMain.handle("jarvis:open-path", async (_, targetPath) => {
  const error = await import_electron.shell.openPath(targetPath);
  return { ok: !error, error };
});
import_electron.ipcMain.handle("jarvis:open-pdf-page", async (_, targetPath, page) => {
  const match = targetPath.match(/storage[/\\]([A-Z0-9]{8})[/\\]/);
  if (match) {
    const itemKey = match[1];
    const zoteroUrl = `zotero://open-pdf/library/items/${itemKey}?page=${page}`;
    try {
      await import_electron.shell.openExternal(zoteroUrl);
      return { ok: true, error: "" };
    } catch {
    }
  }
  const error = await import_electron.shell.openPath(targetPath);
  return { ok: !error, error };
});
