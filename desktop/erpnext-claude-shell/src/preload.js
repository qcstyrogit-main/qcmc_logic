"use strict";

const {contextBridge, ipcRenderer} = require("electron");

contextBridge.exposeInMainWorld("desktopShell", {
  toggleClaude: () => ipcRenderer.send("shell:toggle-claude"),
  selectAssistant: (key) => ipcRenderer.send("shell:assistant-select", key),
  reloadClaude: () => ipcRenderer.send("shell:claude-reload"),
  claudeBack: () => ipcRenderer.send("shell:claude-back"),
  claudeForward: () => ipcRenderer.send("shell:claude-forward"),
  newErpTab: () => ipcRenderer.send("shell:erp-new-tab"),
  activateErpTab: (id) => ipcRenderer.send("shell:erp-activate-tab", id),
  closeErpTab: (id) => ipcRenderer.send("shell:erp-close-tab", id),
  erpBack: () => ipcRenderer.send("shell:erp-back"),
  erpForward: () => ipcRenderer.send("shell:erp-forward"),
  erpReload: () => ipcRenderer.send("shell:erp-reload"),
  setTabNavigatorOpen: (open) => ipcRenderer.send("shell:tab-navigator", open),
  resizeStart: () => ipcRenderer.send("shell:resize-start"),
  resize: (delta) => ipcRenderer.send("shell:resize", delta),
  resizeEnd: () => ipcRenderer.send("shell:resize-end"),
  onState: (callback) => ipcRenderer.on("shell:state", (_event, state) => callback(state)),
});
