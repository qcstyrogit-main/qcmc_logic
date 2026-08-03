"use strict";

const {ipcRenderer} = require("electron");

let accountType = null;
let accounts = [];
let activeInput = null;
let panel = null;
let list = null;
let managing = false;

function isAccountField(element) {
  if (!(element instanceof HTMLInputElement)) return false;
  const signature = [element.type, element.name, element.id, element.autocomplete, element.placeholder]
    .join(" ")
    .toLowerCase();
  return element.type === "email" || /email|e-mail|username|login/.test(signature);
}

function isValidAccount(value) {
  return accountType === "erpnext"
    ? /^[A-Za-z0-9][A-Za-z0-9._@+-]{1,253}$/.test(value)
    : /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function applyStyles(element, styles) {
  Object.assign(element.style, styles);
}

function hidePanel() {
  if (panel) panel.style.display = "none";
  activeInput = null;
  managing = false;
}

function positionPanel() {
  if (!panel || !activeInput || panel.style.display === "none") return;
  const rect = activeInput.getBoundingClientRect();
  const width = Math.min(380, Math.max(300, rect.width));
  const left = Math.min(Math.max(10, rect.left), window.innerWidth - width - 10);
  const roomBelow = window.innerHeight - rect.bottom;
  const estimatedHeight = Math.min(330, 82 + Math.max(1, accounts.length) * 46);
  const top = roomBelow >= estimatedHeight + 12
    ? rect.bottom + 8
    : Math.max(10, rect.top - estimatedHeight - 8);
  applyStyles(panel, {left: `${left}px`, top: `${top}px`, width: `${width}px`});
}

function selectAccount(account) {
  if (!activeInput) return;
  const input = activeInput;
  input.value = account;
  input.dispatchEvent(new Event("input", {bubbles: true}));
  input.dispatchEvent(new Event("change", {bubbles: true}));
  hidePanel();
  input.focus();
}

function renderAccounts() {
  if (!list) return;
  const query = activeInput?.value.trim().toLowerCase() || "";
  const visible = accounts.filter((account) => !query || account.toLowerCase().includes(query));
  list.replaceChildren();

  if (!visible.length) {
    if (query) hidePanel();
    return;
  }

  for (const account of visible) {
    const row = document.createElement("div");
    applyStyles(row, {display: "flex", alignItems: "center", gap: "8px"});

    const choose = document.createElement("button");
    choose.type = "button";
    choose.textContent = account;
    applyStyles(choose, {
      flex: "1",
      minWidth: "0",
      overflow: "hidden",
      border: "0",
      padding: "12px 16px",
      color: "#fff",
      background: "transparent",
      font: "600 14px system-ui, sans-serif",
      textAlign: "left",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap",
      cursor: "pointer",
    });
    choose.addEventListener("mouseenter", () => { choose.style.background = "#333"; });
    choose.addEventListener("mouseleave", () => { choose.style.background = "transparent"; });
    choose.addEventListener("mousedown", (event) => event.preventDefault());
    choose.addEventListener("click", () => selectAccount(account));
    row.appendChild(choose);

    if (managing) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.title = `Remove ${account}`;
      applyStyles(remove, {
        flex: "0 0 34px",
        border: "0",
        padding: "8px",
        color: "#ddd",
        background: "transparent",
        fontSize: "20px",
        cursor: "pointer",
      });
      remove.addEventListener("mousedown", (event) => event.preventDefault());
      remove.addEventListener("click", () => {
        ipcRenderer.send("assistant:forget-account", {key: accountType, account});
      });
      row.appendChild(remove);
    }
    list.appendChild(row);
  }
}

function createPanel() {
  if (panel || !document.body) return;
  panel = document.createElement("section");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Saved login accounts");
  applyStyles(panel, {
    position: "fixed",
    zIndex: "2147483647",
    display: "none",
    maxHeight: "330px",
    overflow: "hidden",
    border: "1px solid #333",
    borderRadius: "18px",
    color: "#fff",
    background: "#242424",
    boxShadow: "0 12px 32px rgba(0,0,0,.38)",
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
  });

  const header = document.createElement("header");
  applyStyles(header, {display: "flex", alignItems: "center", padding: "12px 12px 6px 16px"});
  const title = document.createElement("strong");
  title.textContent = "Saved accounts";
  applyStyles(title, {flex: "1", color: "#d5d5d5", fontSize: "12px"});
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = "×";
  applyStyles(close, {border: "0", color: "#ddd", background: "transparent", fontSize: "22px", cursor: "pointer"});
  close.addEventListener("mousedown", (event) => event.preventDefault());
  close.addEventListener("click", hidePanel);
  header.append(title, close);

  list = document.createElement("div");
  applyStyles(list, {maxHeight: "225px", overflowY: "auto"});

  const manage = document.createElement("button");
  manage.type = "button";
  manage.textContent = "⚙  Manage saved accounts";
  applyStyles(manage, {
    width: "100%",
    border: "0",
    borderTop: "1px solid #3a3a3a",
    padding: "13px 16px",
    color: "#fff",
    background: "transparent",
    font: "500 14px system-ui, sans-serif",
    textAlign: "left",
    cursor: "pointer",
  });
  manage.addEventListener("mousedown", (event) => event.preventDefault());
  manage.addEventListener("click", () => {
    managing = !managing;
    manage.textContent = managing ? "✓  Done managing" : "⚙  Manage saved accounts";
    renderAccounts();
  });
  panel.append(header, list, manage);
  document.body.appendChild(panel);
}

function showPanel(element) {
  if (!accounts.length) return;
  createPanel();
  activeInput = element;
  panel.style.display = "block";
  renderAccounts();
  positionPanel();
}

function reportLoginAttempt(root = document) {
  const element = Array.from(root.querySelectorAll?.("input") || []).find(isAccountField)
    || (isAccountField(activeInput) ? activeInput : null);
  const value = element?.value.trim() || "";
  if (accountType && isValidAccount(value)) {
    ipcRenderer.send("assistant:login-attempt", {key: accountType, account: value});
  }
}

function enhance(root = document) {
  const elements = [];
  if (root instanceof HTMLInputElement) elements.push(root);
  elements.push(...(root.querySelectorAll?.("input") || []));
  for (const element of elements) {
    if (!isAccountField(element) || element.dataset.erpnextAiHistory === "1") continue;
    element.dataset.erpnextAiHistory = "1";
    element.setAttribute("autocomplete", "off");
    element.addEventListener("focus", () => showPanel(element));
    element.addEventListener("click", () => showPanel(element));
    element.addEventListener("input", () => {
      if (accounts.length) showPanel(element);
      renderAccounts();
    });
  }
}

ipcRenderer.on("assistant:configure", (_event, configuration) => {
  accountType = configuration?.key || null;
  accounts = Array.isArray(configuration?.accounts) ? configuration.accounts : [];
  createPanel();
  enhance();
  if (panel?.style.display !== "none") renderAccounts();
});

window.addEventListener("DOMContentLoaded", () => {
  createPanel();
  enhance();
  document.addEventListener("mousedown", (event) => {
    if (panel?.contains(event.target) || event.target === activeInput) return;
    hidePanel();
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hidePanel();
  }, true);
  document.addEventListener("submit", (event) => reportLoginAttempt(event.target), true);
  document.addEventListener("click", (event) => {
    const button = event.target.closest?.("button, input[type='submit']");
    if (button && (button.type === "submit" || /login|sign in|continue/i.test(button.textContent || button.value || ""))) {
      reportLoginAttempt(button.form || document);
    }
  }, true);
  window.addEventListener("resize", positionPanel);
  window.addEventListener("scroll", positionPanel, true);
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE && node !== panel && !panel?.contains(node)) enhance(node);
      }
    }
  }).observe(document.documentElement, {childList: true, subtree: true});
});
