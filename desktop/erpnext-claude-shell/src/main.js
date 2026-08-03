"use strict";

const {app, BrowserWindow, WebContentsView, ipcMain, shell, dialog, Menu} = require("electron");
const {autoUpdater} = require("electron-updater");
const fs = require("node:fs");
const path = require("node:path");

const DEFAULT_ERP_URL = "https://desktop-vlfuuk4.tail39f829.ts.net/desk";
const CLAUDE_URL = "https://claude.ai/new";
const CHATGPT_URL = "https://chatgpt.com/";
const ASSISTANTS = {
  claude: {name: "Claude", url: CLAUDE_URL, partition: "persist:claude"},
  chatgpt: {name: "ChatGPT", url: CHATGPT_URL, partition: "persist:chatgpt"},
};
const TOOLBAR_HEIGHT = 48;
const MIN_PANEL_WIDTH = 360;
const MIN_ERP_WIDTH = 560;

let mainWindow;
let assistantViews = {};
let initializedAssistants = new Set();
let preparedAssistantSessions = new Set();
let assistantLastUrls = {};
const pendingLoginAccounts = new Map();
let activeAssistant = "claude";
let erpHomeUrl = DEFAULT_ERP_URL;
let erpTabs = [];
let closedErpTabs = [];
let activeTabId = null;
let nextTabId = 1;
let claudeVisible = true;
let panelWidth = 520;
let dragging = false;
let updatePromptOpen = false;

function configureAutoUpdates() {
  if (!app.isPackaged || process.platform !== "win32") return;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.on("error", (error) => console.error("Automatic update failed:", error));
  autoUpdater.on("update-downloaded", async (info) => {
    if (updatePromptOpen || !mainWindow || mainWindow.isDestroyed()) return;
    updatePromptOpen = true;
    const result = await dialog.showMessageBox(mainWindow, {
      type: "info",
      title: "ERPNext AI Desktop update ready",
      message: `Version ${info.version} is ready to install.`,
      detail: "Restart the application now to finish the update.",
      buttons: ["Restart and update", "Later"],
      defaultId: 0,
      cancelId: 1,
      noLink: true,
    });
    updatePromptOpen = false;
    if (result.response === 0) autoUpdater.quitAndInstall(false, true);
  });
  const check = () => autoUpdater.checkForUpdates().catch((error) => {
    console.error("Automatic update check failed:", error);
  });
  setTimeout(check, 10000);
  setInterval(check, 4 * 60 * 60 * 1000).unref();
}

function settingsPath() {
  return path.join(app.getPath("userData"), "settings.json");
}

function readSettings() {
  try {
    return JSON.parse(fs.readFileSync(settingsPath(), "utf8"));
  } catch {
    return {};
  }
}

function writeSettings(settings) {
  fs.mkdirSync(path.dirname(settingsPath()), {recursive: true});
  fs.writeFileSync(settingsPath(), `${JSON.stringify(settings, null, 2)}\n`, "utf8");
}

function commandLineErpUrl() {
  const argument = process.argv.find((value) => value.startsWith("--erp-url="));
  return argument ? argument.slice("--erp-url=".length) : null;
}

function normalizeUrl(value, fallback) {
  try {
    const parsed = new URL(value || fallback);
    if (!["http:", "https:"].includes(parsed.protocol)) throw new Error("Unsupported protocol");
    return parsed.toString();
  } catch {
    return fallback;
  }
}

function activeTab() {
  return erpTabs.find((tab) => tab.id === activeTabId) || null;
}

function assistantContents(key = activeAssistant) {
  const view = assistantViews[key];
  const contents = view?.webContents;
  return contents && !contents.isDestroyed() ? contents : null;
}

function createAssistantView(key) {
  const definition = ASSISTANTS[key];
  if (!mainWindow || !definition) return null;
  const previous = assistantViews[key];
  if (previous) {
    try { mainWindow.contentView.removeChildView(previous); } catch {}
  }

  initializedAssistants.delete(key);
  const view = createView(definition.partition, path.join(__dirname, "assistant-preload.js"));
  configureAssistantContents(view.webContents, definition.partition, key);
  assistantViews[key] = view;
  mainWindow.contentView.addChildView(view);
  return view.webContents;
}

function destroyAssistantView(key) {
  const view = assistantViews[key];
  const contents = view?.webContents;
  if (!view) return;
  if (contents && !contents.isDestroyed()) {
    const url = contents.getURL();
    if (url) assistantLastUrls[key] = url;
  }
  try { mainWindow?.contentView.removeChildView(view); } catch {}
  if (contents && !contents.isDestroyed()) contents.close();
  delete assistantViews[key];
  initializedAssistants.delete(key);
}

function ensureAssistantContents(key = activeAssistant) {
  return assistantContents(key) || createAssistantView(key);
}

function loadAssistant(key) {
  const contents = ensureAssistantContents(key);
  const definition = ASSISTANTS[key];
  if (!contents || !definition || initializedAssistants.has(key)) return;
  initializedAssistants.add(key);
  const targetUrl = assistantLastUrls[key] || definition.url;
  if (preparedAssistantSessions.has(key)) {
    contents.loadURL(targetUrl);
    return;
  }
  preparedAssistantSessions.add(key);
  Promise.all([
    contents.session.clearCache(),
    contents.session.clearStorageData({storages: ["serviceworkers", "cachestorage"]}),
  ]).finally(() => {
    if (!contents.isDestroyed()) contents.loadURL(targetUrl);
  });
}

function handleShortcut(input, sourceTabId = null) {
  const key = input.key.toLowerCase();
  const contents = activeTab()?.view.webContents;
  if (input.alt && key === "arrowleft") {
    if (contents?.navigationHistory.canGoBack()) contents.navigationHistory.goBack();
    return;
  }
  if (input.alt && key === "arrowright") {
    if (contents?.navigationHistory.canGoForward()) contents.navigationHistory.goForward();
    return;
  }
  if (!input.control) return;
  if (input.shift && key === "a") toggleClaude();
  else if (input.shift && key === "t") reopenClosedErpTab();
  else if (key === "t") createErpTab(erpHomeUrl, true);
  else if (key === "w" && sourceTabId) closeErpTab(sourceTabId);
  else if (key === "tab") activateAdjacentTab(input.shift ? -1 : 1);
  else if (key === "pageup") activateAdjacentTab(-1);
  else if (key === "pagedown") activateAdjacentTab(1);
  else if (key === "r") contents?.reload();
  else if (/^[1-9]$/.test(key)) {
    const requested = Number(key) === 9 ? erpTabs.length - 1 : Number(key) - 1;
    if (erpTabs[requested]) activateErpTab(erpTabs[requested].id);
  }
}

function accountHistory(key) {
  const settings = readSettings();
  const history = settings.accountHistory?.[key];
  return Array.isArray(history) ? history.filter((value) => typeof value === "string").slice(0, 10) : [];
}

function sendAccountHistory(key) {
  if (key === "erpnext") {
    for (const tab of erpTabs) {
      if (!tab.view.webContents.isDestroyed()) {
        tab.view.webContents.send("assistant:configure", {key, accounts: accountHistory(key)});
      }
    }
    return;
  }
  const contents = assistantContents(key);
  if (contents) {
    contents.send("assistant:configure", {key, accounts: accountHistory(key)});
  }
}

function validAccount(key, account) {
  return key === "erpnext"
    ? /^[A-Za-z0-9][A-Za-z0-9._@+-]{1,253}$/.test(account)
    : /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(account);
}

function rememberAccount(key, account) {
  const settings = readSettings();
  const histories = settings.accountHistory && typeof settings.accountHistory === "object"
    ? settings.accountHistory
    : {};
  const existing = Array.isArray(histories[key]) ? histories[key] : [];
  histories[key] = [account, ...existing.filter((value) => value !== account)].slice(0, 10);
  writeSettings({...settings, accountHistory: histories});
  sendAccountHistory(key);
}

async function confirmSuccessfulLogin(contents, key) {
  const pending = pendingLoginAccounts.get(contents.id);
  if (!pending || pending.key !== key || contents.isDestroyed()) return;

  let authenticated = false;
  if (key === "erpnext") {
    const cookies = await contents.session.cookies.get({url: erpHomeUrl, name: "sid"});
    authenticated = cookies.some((cookie) => cookie.value && cookie.value !== "Guest");
  } else {
    const currentUrl = contents.getURL().toLowerCase();
    authenticated = Boolean(currentUrl) && !/login|signin|sign-in|auth/.test(new URL(currentUrl).pathname);
  }
  if (!authenticated) return;

  pendingLoginAccounts.delete(contents.id);
  rememberAccount(key, pending.account);
}

function configureAssistantContents(contents, partition, key) {
  contents.setUserAgent(contents.getUserAgent().replace(/\sElectron\/[^\s]+/g, ""));
  contents.on("before-input-event", (_event, input) => handleShortcut(input));
  contents.on("did-finish-load", () => sendAccountHistory(key));
  contents.on("did-finish-load", () => confirmSuccessfulLogin(contents, key));
  contents.on("did-navigate", () => confirmSuccessfulLogin(contents, key));
  contents.on("did-navigate-in-page", () => confirmSuccessfulLogin(contents, key));
  contents.on("did-create-window", (childWindow) => {
    childWindow.on("closed", () => {
      setTimeout(() => {
        const current = assistantContents(key);
        if (current && key === activeAssistant) current.reload();
      }, 300);
    });
  });
  contents.setWindowOpenHandler(({url}) => {
    if (url.startsWith("http://") || url.startsWith("https://")) {
      return {
        action: "allow",
        overrideBrowserWindowOptions: {
          width: 720,
          height: 820,
          autoHideMenuBar: true,
          webPreferences: {
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true,
            partition,
          },
        },
      };
    }
    shell.openExternal(url).catch(() => {});
    return {action: "deny"};
  });
}

function createView(partition, preload = null) {
  return new WebContentsView({
    webPreferences: {
      partition,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: true,
      backgroundThrottling: true,
      ...(preload ? {preload} : {}),
    },
  });
}

function tabState(tab) {
  return {
    id: tab.id,
    title: tab.title || "ERPNext",
    url: tab.view.webContents.getURL(),
    loading: tab.view.webContents.isLoading(),
    favicon: tab.favicon || "",
    canGoBack: tab.view.webContents.navigationHistory.canGoBack(),
    canGoForward: tab.view.webContents.navigationHistory.canGoForward(),
  };
}

function sendState() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send("shell:state", {
    claudeVisible,
    activeAssistant,
    panelWidth,
    activeTabId,
    tabs: erpTabs.map(tabState),
  });
}

function createErpTab(url = erpHomeUrl, activate = true) {
  if (!mainWindow) return null;
  const id = nextTabId++;
  const view = createView("persist:erpnext", path.join(__dirname, "assistant-preload.js"));
  const tab = {id, title: "ERPNext", favicon: "", view};
  erpTabs.push(tab);
  mainWindow.contentView.addChildView(view);

  view.webContents.on("before-input-event", (_event, input) => handleShortcut(input, id));
  view.webContents.setWindowOpenHandler(({url: popupUrl}) => {
    if (popupUrl.startsWith("http://") || popupUrl.startsWith("https://")) {
      createErpTab(popupUrl, true);
    } else {
      shell.openExternal(popupUrl).catch(() => {});
    }
    return {action: "deny"};
  });

  const update = () => {
    tab.title = view.webContents.getTitle() || "ERPNext";
    sendState();
  };
  view.webContents.on("page-title-updated", update);
  view.webContents.on("page-favicon-updated", (_event, favicons) => {
    tab.favicon = favicons?.[0] || "";
    sendState();
  });
  view.webContents.on("did-start-loading", sendState);
  view.webContents.on("did-finish-load", () => sendAccountHistory("erpnext"));
  view.webContents.on("did-finish-load", () => confirmSuccessfulLogin(view.webContents, "erpnext"));
  view.webContents.on("did-navigate", () => confirmSuccessfulLogin(view.webContents, "erpnext"));
  view.webContents.on("did-navigate-in-page", () => confirmSuccessfulLogin(view.webContents, "erpnext"));
  view.webContents.on("did-stop-loading", update);
  view.webContents.on("did-navigate", update);
  view.webContents.on("did-navigate-in-page", update);
  view.webContents.on("render-process-gone", update);

  view.webContents.loadURL(normalizeUrl(url, erpHomeUrl));
  if (activate) activeTabId = id;
  layoutViews();
  return id;
}

function activateErpTab(id) {
  if (!erpTabs.some((tab) => tab.id === id)) return;
  activeTabId = id;
  layoutViews();
  activeTab()?.view.webContents.focus();
}

function activateAdjacentTab(direction) {
  if (erpTabs.length < 2) return;
  const currentIndex = erpTabs.findIndex((tab) => tab.id === activeTabId);
  const nextIndex = (currentIndex + direction + erpTabs.length) % erpTabs.length;
  activateErpTab(erpTabs[nextIndex].id);
}

function closeErpTab(id) {
  const index = erpTabs.findIndex((tab) => tab.id === id);
  if (index === -1) return;
  const [tab] = erpTabs.splice(index, 1);
  const closedUrl = tab.view.webContents.getURL();
  if (closedUrl) closedErpTabs = [{url: closedUrl, title: tab.title}, ...closedErpTabs].slice(0, 20);
  mainWindow.contentView.removeChildView(tab.view);
  tab.view.webContents.close();

  if (erpTabs.length === 0) {
    createErpTab(erpHomeUrl, true);
    return;
  }
  if (activeTabId === id) {
    activeTabId = erpTabs[Math.min(index, erpTabs.length - 1)].id;
  }
  layoutViews();
}

function reopenClosedErpTab() {
  const closed = closedErpTabs.shift();
  if (closed?.url) createErpTab(closed.url, true);
}

function showTabNavigator(bounds = {}) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const items = erpTabs.map((tab, index) => ({
    label: `${index + 1}. ${tab.title || "ERPNext"}`,
    type: "radio",
    checked: tab.id === activeTabId,
    click: () => activateErpTab(tab.id),
  }));
  items.push(
    {type: "separator"},
    {label: "New tab", accelerator: "Ctrl+T", click: () => createErpTab(erpHomeUrl, true)},
    {label: "Reopen closed tab", accelerator: "Ctrl+Shift+T", enabled: closedErpTabs.length > 0, click: reopenClosedErpTab},
    {label: "Close current tab", accelerator: "Ctrl+W", click: () => closeErpTab(activeTabId)},
  );
  const x = Number.isFinite(bounds.x) ? Math.max(0, Math.round(bounds.x)) : 0;
  Menu.buildFromTemplate(items).popup({window: mainWindow, x, y: TOOLBAR_HEIGHT});
}

function layoutViews() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const [width, height] = mainWindow.getContentSize();
  const bodyHeight = Math.max(0, height - TOOLBAR_HEIGHT);
  const maximumPanel = Math.max(MIN_PANEL_WIDTH, width - MIN_ERP_WIDTH);
  panelWidth = Math.min(Math.max(panelWidth, MIN_PANEL_WIDTH), maximumPanel);
  const erpWidth = claudeVisible ? Math.max(0, width - panelWidth - 5) : width;

  for (const tab of erpTabs) {
    const isActive = tab.id === activeTabId;
    tab.view.setBounds({x: 0, y: TOOLBAR_HEIGHT, width: erpWidth, height: bodyHeight});
    tab.view.setVisible(isActive);
  }

  for (const [key, view] of Object.entries(assistantViews)) {
    if (!view?.webContents || view.webContents.isDestroyed()) continue;
    view.setBounds({x: erpWidth + 5, y: TOOLBAR_HEIGHT, width: panelWidth, height: bodyHeight});
    view.setVisible(claudeVisible && key === activeAssistant);
  }
  sendState();
}

function saveLayout() {
  const settings = readSettings();
  writeSettings({
    ...settings,
    claudeVisible,
    panelWidth,
    activeAssistant,
    assistantLastUrls,
    erpUrl: erpHomeUrl,
  });
}

function toggleClaude(force) {
  const show = typeof force === "boolean" ? force : !claudeVisible;
  if (show) {
    claudeVisible = true;
    ensureAssistantContents(activeAssistant);
    loadAssistant(activeAssistant);
    layoutViews();
  } else {
    claudeVisible = false;
    layoutViews();
    destroyAssistantView(activeAssistant);
  }
  saveLayout();
}

function selectAssistant(key) {
  if (!ASSISTANTS[key]) return;
  const previous = activeAssistant;
  if (previous !== key) destroyAssistantView(previous);
  activeAssistant = key;
  claudeVisible = true;
  ensureAssistantContents(key);
  loadAssistant(key);
  layoutViews();
  saveLayout();
  assistantContents(key)?.focus();
}

function createWindow() {
  const settings = readSettings();
  erpHomeUrl = normalizeUrl(
    commandLineErpUrl() || process.env.ERPNEXT_URL || settings.erpUrl,
    DEFAULT_ERP_URL,
  );
  claudeVisible = settings.claudeVisible !== false;
  activeAssistant = ASSISTANTS[settings.activeAssistant] ? settings.activeAssistant : "claude";
  assistantLastUrls = settings.assistantLastUrls && typeof settings.assistantLastUrls === "object"
    ? settings.assistantLastUrls
    : {};
  panelWidth = Number.isFinite(settings.panelWidth) ? settings.panelWidth : 520;

  mainWindow = new BrowserWindow({
    title: "ERPNext + AI",
    width: 1500,
    height: 930,
    minWidth: 980,
    minHeight: 680,
    autoHideMenuBar: true,
    backgroundColor: "#f7f7f7",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.loadFile(path.join(__dirname, "shell.html"));
  assistantViews = {};
  initializedAssistants = new Set();
  preparedAssistantSessions = new Set();
  if (claudeVisible) {
    createAssistantView(activeAssistant);
    loadAssistant(activeAssistant);
  }
  createErpTab(erpHomeUrl, true);

  mainWindow.on("resize", layoutViews);
  mainWindow.on("closed", () => {
    erpTabs = [];
    closedErpTabs = [];
    activeTabId = null;
    mainWindow = null;
    assistantViews = {};
    initializedAssistants = new Set();
    preparedAssistantSessions = new Set();
  });
  mainWindow.webContents.on("did-finish-load", layoutViews);
  mainWindow.webContents.on("before-input-event", (_event, input) => handleShortcut(input, activeTabId));
}

ipcMain.on("shell:toggle-claude", () => toggleClaude());
ipcMain.on("assistant:login-attempt", (event, payload) => {
  const key = String(payload?.key || "");
  const account = String(payload?.account || "").trim().slice(0, 254);
  const assistantView = assistantViews[key];
  const isErpTab = key === "erpnext" && erpTabs.some((tab) => tab.view.webContents.id === event.sender.id);
  const isAssistantView = Boolean(ASSISTANTS[key] && assistantView?.webContents.id === event.sender.id);
  if (!isErpTab && !isAssistantView) return;
  if (!validAccount(key, account)) return;
  pendingLoginAccounts.set(event.sender.id, {key, account});
  for (const delay of [500, 1500, 3000, 6000]) {
    setTimeout(() => confirmSuccessfulLogin(event.sender, key), delay);
  }
});
ipcMain.on("assistant:forget-account", (event, payload) => {
  const key = String(payload?.key || "");
  const account = String(payload?.account || "").trim();
  const assistantView = assistantViews[key];
  const isErpTab = key === "erpnext" && erpTabs.some((tab) => tab.view.webContents.id === event.sender.id);
  const isAssistantView = Boolean(ASSISTANTS[key] && assistantView?.webContents.id === event.sender.id);
  if (!isErpTab && !isAssistantView) return;

  const settings = readSettings();
  const histories = settings.accountHistory && typeof settings.accountHistory === "object"
    ? settings.accountHistory
    : {};
  const existing = Array.isArray(histories[key]) ? histories[key] : [];
  histories[key] = existing.filter((value) => value !== account).slice(0, 10);
  writeSettings({...settings, accountHistory: histories});
  sendAccountHistory(key);
});
ipcMain.on("shell:assistant-select", (_event, key) => selectAssistant(String(key)));
ipcMain.on("shell:claude-reload", () => {
  const contents = ensureAssistantContents();
  if (!contents) return;
  if (contents.getURL()) contents.reload();
  else loadAssistant(activeAssistant);
  layoutViews();
});
ipcMain.on("shell:claude-back", () => {
  const contents = assistantContents();
  if (contents?.navigationHistory.canGoBack()) contents.navigationHistory.goBack();
});
ipcMain.on("shell:claude-forward", () => {
  const contents = assistantContents();
  if (contents?.navigationHistory.canGoForward()) contents.navigationHistory.goForward();
});
ipcMain.on("shell:erp-new-tab", () => createErpTab(erpHomeUrl, true));
ipcMain.on("shell:erp-activate-tab", (_event, id) => activateErpTab(Number(id)));
ipcMain.on("shell:erp-close-tab", (_event, id) => closeErpTab(Number(id)));
ipcMain.on("shell:erp-back", () => {
  const contents = activeTab()?.view.webContents;
  if (contents?.navigationHistory.canGoBack()) contents.navigationHistory.goBack();
});
ipcMain.on("shell:erp-forward", () => {
  const contents = activeTab()?.view.webContents;
  if (contents?.navigationHistory.canGoForward()) contents.navigationHistory.goForward();
});
ipcMain.on("shell:erp-reload", () => activeTab()?.view.webContents.reload());
ipcMain.on("shell:tab-navigator", (_event, bounds) => showTabNavigator(bounds));
ipcMain.on("shell:resize-start", () => { dragging = true; });
ipcMain.on("shell:resize", (_event, delta) => {
  if (!dragging || !claudeVisible || !Number.isFinite(delta)) return;
  panelWidth += delta;
  layoutViews();
});
ipcMain.on("shell:resize-end", () => {
  if (!dragging) return;
  dragging = false;
  saveLayout();
});

app.whenReady().then(() => {
  createWindow();
  configureAutoUpdates();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
