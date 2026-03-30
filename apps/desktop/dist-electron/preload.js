"use strict";

// src/main/preload.ts
var import_electron = require("electron");
import_electron.contextBridge.exposeInMainWorld("roxanne", {
  getRuntimeInfo: () => import_electron.ipcRenderer.invoke("roxanne:get-runtime-info"),
  pickDirectory: () => import_electron.ipcRenderer.invoke("roxanne:pick-directory"),
  pickFile: (filters) => import_electron.ipcRenderer.invoke("roxanne:pick-file", filters),
  openPath: (targetPath) => import_electron.ipcRenderer.invoke("roxanne:open-path", targetPath),
  openPdfAtPage: (targetPath, page) => import_electron.ipcRenderer.invoke("roxanne:open-pdf-page", targetPath, page)
});
