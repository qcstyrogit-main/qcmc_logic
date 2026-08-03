"use strict";

const toggle = document.querySelector("#toggle-claude");
const divider = document.querySelector("#divider");
const tabsContainer = document.querySelector("#erp-tabs");
const assistantSelect = document.querySelector("#assistant-select");
const tabNavigator = document.querySelector("#tab-navigator");
const tabMenu = document.querySelector("#tab-menu");
const tabMenuList = document.querySelector("#tab-menu-list");
const tabSearch = document.querySelector("#tab-search");
let lastX = null;
let currentTabs = [];
let currentActiveTabId = null;

document.querySelector("#erp-new-tab").addEventListener("click", () => window.desktopShell.newErpTab());
document.querySelector("#erp-back").addEventListener("click", () => window.desktopShell.erpBack());
document.querySelector("#erp-forward").addEventListener("click", () => window.desktopShell.erpForward());
document.querySelector("#erp-reload").addEventListener("click", () => window.desktopShell.erpReload());
toggle.addEventListener("click", () => window.desktopShell.toggleClaude());
assistantSelect.addEventListener("change", () => window.desktopShell.selectAssistant(assistantSelect.value));
document.querySelector("#claude-back").addEventListener("click", () => window.desktopShell.claudeBack());
document.querySelector("#claude-forward").addEventListener("click", () => window.desktopShell.claudeForward());
document.querySelector("#claude-reload").addEventListener("click", () => window.desktopShell.reloadClaude());

function renderTabs(tabs, activeTabId) {
  const fragment = document.createDocumentFragment();
  for (const tab of tabs) {
    const element = document.createElement("div");
    element.className = `erp-tab${tab.id === activeTabId ? " active" : ""}`;
    element.title = tab.title;

    const label = document.createElement("button");
    label.type = "button";
    label.className = "erp-tab-label";
    const icon = document.createElement(tab.favicon ? "img" : "span");
    icon.className = `erp-tab-icon${tab.loading ? " loading" : ""}`;
    if (tab.favicon) {
      icon.src = tab.favicon;
      icon.alt = "";
    } else {
      icon.textContent = tab.loading ? "◌" : "◆";
      icon.setAttribute("aria-hidden", "true");
    }
    const title = document.createElement("span");
    title.className = "erp-tab-title";
    title.textContent = tab.title;
    label.append(icon, title);
    label.addEventListener("click", () => window.desktopShell.activateErpTab(tab.id));

    const close = document.createElement("button");
    close.type = "button";
    close.className = "erp-tab-close";
    close.textContent = "×";
    close.setAttribute("aria-label", `Close ${tab.title}`);
    close.addEventListener("click", () => window.desktopShell.closeErpTab(tab.id));
    element.addEventListener("auxclick", (event) => {
      if (event.button === 1) window.desktopShell.closeErpTab(tab.id);
    });

    element.append(label, close);
    fragment.appendChild(element);
  }
  tabsContainer.replaceChildren(fragment);
  const available = Math.max(1, tabsContainer.clientWidth);
  const perTab = Math.max(42, Math.min(210, Math.floor(available / Math.max(1, tabs.length))));
  tabsContainer.style.setProperty("--erp-tab-width", `${perTab}px`);
  tabsContainer.classList.toggle("compact", perTab < 125);
  tabsContainer.classList.toggle("icons-only", perTab < 72);
  tabsContainer.querySelector(".erp-tab.active")?.scrollIntoView({block: "nearest", inline: "nearest"});
  requestAnimationFrame(() => {
    const overflowing = tabsContainer.scrollWidth > tabsContainer.clientWidth + 2;
    const hideNavigator = !overflowing && tabs.length <= 5;
    tabNavigator.hidden = hideNavigator;
    if (hideNavigator) closeTabMenu();
    tabNavigator.textContent = `Tabs ${tabs.length}`;
  });
}

function closeTabMenu() {
  if (tabMenu.hidden) return;
  tabMenu.hidden = true;
  tabNavigator.setAttribute("aria-expanded", "false");
}

function positionTabMenu() {
  const rect = tabNavigator.getBoundingClientRect();
  const width = Math.min(420, window.innerWidth - 20);
  const left = Math.min(Math.max(10, rect.right - width), window.innerWidth - width - 10);
  tabMenu.style.width = `${width}px`;
  tabMenu.style.left = `${left}px`;
  tabMenu.style.top = `${rect.bottom + 6}px`;
}

function renderTabMenu() {
  const query = tabSearch.value.trim().toLowerCase();
  const filtered = currentTabs.filter((tab) => {
    return !query || tab.title.toLowerCase().includes(query) || tab.url.toLowerCase().includes(query);
  });
  tabMenuList.replaceChildren();

  for (const tab of filtered) {
    const row = document.createElement("div");
    row.className = `tab-menu-row${tab.id === currentActiveTabId ? " active" : ""}`;

    const select = document.createElement("button");
    select.type = "button";
    select.className = "tab-menu-select";
    const title = document.createElement("strong");
    title.textContent = `${tab.id === currentActiveTabId ? "✓ " : ""}${tab.title}`;
    const url = document.createElement("small");
    url.textContent = tab.url;
    select.append(title, url);
    select.addEventListener("click", () => {
      window.desktopShell.activateErpTab(tab.id);
      closeTabMenu();
    });

    const close = document.createElement("button");
    close.type = "button";
    close.className = "tab-menu-remove";
    close.textContent = "×";
    close.setAttribute("aria-label", `Close ${tab.title}`);
    close.addEventListener("click", () => window.desktopShell.closeErpTab(tab.id));
    row.append(select, close);
    tabMenuList.appendChild(row);
  }

  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "tab-menu-empty";
    empty.textContent = "No matching tabs";
    tabMenuList.appendChild(empty);
  }
}

tabNavigator.addEventListener("click", () => {
  const bounds = tabNavigator.getBoundingClientRect();
  window.desktopShell.openTabNavigator({x: bounds.left, y: bounds.bottom});
});
document.querySelector("#tab-menu-close").addEventListener("click", closeTabMenu);
tabSearch.addEventListener("input", renderTabMenu);
tabsContainer.addEventListener("wheel", (event) => {
  if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
    tabsContainer.scrollLeft += event.deltaY;
    event.preventDefault();
  }
}, {passive: false});
tabsContainer.addEventListener("dblclick", (event) => {
  if (!event.target.closest(".erp-tab")) window.desktopShell.newErpTab();
});
document.addEventListener("mousedown", (event) => {
  if (!tabMenu.hidden && !tabMenu.contains(event.target) && event.target !== tabNavigator) closeTabMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeTabMenu();
});
window.addEventListener("resize", () => {
  if (!tabMenu.hidden) positionTabMenu();
  renderTabs(currentTabs, currentActiveTabId);
});

divider.addEventListener("pointerdown", (event) => {
  lastX = event.screenX;
  divider.setPointerCapture(event.pointerId);
  window.desktopShell.resizeStart();
});

divider.addEventListener("pointermove", (event) => {
  if (lastX === null) return;
  const delta = lastX - event.screenX;
  lastX = event.screenX;
  window.desktopShell.resize(delta);
});

function finishResize() {
  if (lastX === null) return;
  lastX = null;
  window.desktopShell.resizeEnd();
}

divider.addEventListener("pointerup", finishResize);
divider.addEventListener("pointercancel", finishResize);

window.desktopShell.onState(({claudeVisible, activeAssistant, panelWidth, tabs, activeTabId}) => {
  document.body.classList.toggle("claude-hidden", !claudeVisible);
  document.documentElement.style.setProperty("--claude-panel-width", `${panelWidth}px`);
  assistantSelect.value = activeAssistant || "claude";
  toggle.textContent = claudeVisible ? "Hide AI" : "Show AI";
  currentTabs = tabs || [];
  currentActiveTabId = activeTabId;
  renderTabs(currentTabs, activeTabId);
  if (!tabMenu.hidden) renderTabMenu();
});
