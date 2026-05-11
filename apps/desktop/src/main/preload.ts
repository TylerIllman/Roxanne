import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("roxanne", {
  getRuntimeInfo: () => ipcRenderer.invoke("roxanne:get-runtime-info"),
  pickDirectory: () => ipcRenderer.invoke("roxanne:pick-directory"),
  pickFile: (filters?: Electron.FileFilter[]) =>
    ipcRenderer.invoke("roxanne:pick-file", filters),
  openPath: (targetPath: string) => ipcRenderer.invoke("roxanne:open-path", targetPath),
  openPdfAtPage: (targetPath: string, page: number) => ipcRenderer.invoke("roxanne:open-pdf-page", targetPath, page),
  openUnmute: (url: string) => ipcRenderer.invoke("roxanne:open-unmute", url),
});
