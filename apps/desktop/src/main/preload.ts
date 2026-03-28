import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("jarvis", {
  getRuntimeInfo: () => ipcRenderer.invoke("jarvis:get-runtime-info"),
  pickDirectory: () => ipcRenderer.invoke("jarvis:pick-directory"),
  pickFile: (filters?: Electron.FileFilter[]) =>
    ipcRenderer.invoke("jarvis:pick-file", filters),
  openPath: (targetPath: string) => ipcRenderer.invoke("jarvis:open-path", targetPath),
  openPdfAtPage: (targetPath: string, page: number) => ipcRenderer.invoke("jarvis:open-pdf-page", targetPath, page),
});

