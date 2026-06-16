const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  selectFolder: () => ipcRenderer.invoke('dialog:openDirectory'),
  setBaseDir: (path) => ipcRenderer.invoke('file:setBaseDir', path),
  readJson: (path) => ipcRenderer.invoke('file:readJson', path),
  writeJson: (path, data) => ipcRenderer.invoke('file:writeJson', { path, data }),
  deleteFile: (path) => ipcRenderer.invoke('file:deleteFile', path),
  listDir: (path) => ipcRenderer.invoke('file:listDir', path),
  fileExists: (path) => ipcRenderer.invoke('file:exists', path),
  readText: (path) => ipcRenderer.invoke('file:readText', path),
  writeText: (path, text) => ipcRenderer.invoke('file:writeText', { path, text }),
  ensureDir: (path) => ipcRenderer.invoke('file:ensureDir', path),
  focusWindow: () => ipcRenderer.invoke('window:focus'),
});