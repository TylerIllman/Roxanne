"use strict";

// src/main/preload.ts
var import_electron = require("electron");
import_electron.contextBridge.exposeInMainWorld("jarvis", {
  getRuntimeInfo: () => import_electron.ipcRenderer.invoke("jarvis:get-runtime-info"),
  pickDirectory: () => import_electron.ipcRenderer.invoke("jarvis:pick-directory"),
  pickFile: (filters) => import_electron.ipcRenderer.invoke("jarvis:pick-file", filters),
  openPath: (targetPath) => import_electron.ipcRenderer.invoke("jarvis:open-path", targetPath),
  openPdfAtPage: (targetPath, page) => import_electron.ipcRenderer.invoke("jarvis:open-pdf-page", targetPath, page)
});
