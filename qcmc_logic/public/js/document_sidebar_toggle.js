/* Collapse the document details panel without hiding the reopen control. */
(() => {
    const preferences = new Map();
    let stylesAdded = false, sidebarId = 0;
    const preferenceKey = () => `qcmc-document-details:${frappe.session.user}`;
    const actions = [
        {label: "Assign", icon: "users", target: ".add-assignment-label", section: ".form-assignments"},
        {label: "Attachments", icon: "paperclip", target: ".add-attachment-btn", section: ".form-attachments"},
        {label: "Tags", icon: "tag", target: ".tags-input", section: ".form-tags", focus: true},
        {label: "Share", icon: "share-2", target: ".share-label", section: ".form-shared"},
        {label: "Rename", icon: "square-pen", command: "rename"},
        {label: "Print", icon: "printer", target: ".form-print button"},
        {label: "Favorite", icon: "heart", target: ".liked-by .like-icon", favorite: true},
        {label: "Info", icon: "info", command: "info"},
    ];

    function tooltip(node, label, enabled = true) {
        node.removeAttribute("title");
        node.setAttribute("aria-label", label);
        if (!node._qcmcTooltip && typeof $(node).tooltip === "function") {
            $(node).tooltip({title: () => node.getAttribute("aria-label"), placement: "left", container: "body", boundary: "window", offset: "0,8", template: '<div class="tooltip qcmc-action-tooltip" role="tooltip"><div class="arrow"></div><div class="tooltip-inner"></div></div>', trigger: "hover focus", delay: {show: 200, hide: 0}});
            node.addEventListener("click", () => $(node).tooltip("hide"));
            node._qcmcTooltip = true;
        }
        if (node._qcmcTooltip && node._qcmcTooltipEnabled !== enabled) {
            $(node).tooltip(enabled ? "enable" : "disable");
            if (!enabled) $(node).tooltip("hide");
            node._qcmcTooltipEnabled = enabled;
        }
    }

    function openInfo(frm) {
        const dialog = new frappe.ui.Dialog({title: __("Document info"), size: "small"});
        dialog.body.classList.add("qcmc-document-info");
        const user = value => value ? (frappe.user?.full_name?.(value) || value) : "—";
        const date = value => value ? (frappe.datetime?.str_to_user?.(value) || value) : "—";
        [
            ["Name", frm.doc.name],
            ["Last edited by", user(frm.doc.modified_by)],
            ["Last edited", date(frm.doc.modified)],
            ["Created by", user(frm.doc.owner)],
            ["Created on", date(frm.doc.creation)],
        ].forEach(([label, value]) => {
            const row = document.createElement("div");
            const caption = document.createElement("div"), content = document.createElement("div");
            caption.className = "text-muted small";
            caption.textContent = __(label);
            content.textContent = value || "—";
            row.appendChild(caption); row.appendChild(content);
            dialog.body.appendChild(row);
        });
        dialog.show();
    }

    function openTags(frm, sidebar) {
        const section = sidebar.querySelector(".form-tags");
        if (!section || !section.parentElement) return;
        const parent = section.parentElement, next = section.nextSibling;
        const input = section.querySelector(".tags-input");
        const inputWrapper = frm.tags?.tags?.$inputWrapper?.[0] || input?.parentElement;
        // Reuse the native editor and its persistence/permissions instead of
        // creating a second copy with independent tag state.
        const dialog = new frappe.ui.Dialog({
            title: __("Tags"),
            size: "small",
            on_hide() {
                inputWrapper?.classList.remove("qcmc-tags-input-wrap");
                if (parent.isConnected && section.parentElement === dialog.body) {
                    if (next?.parentElement === parent) parent.insertBefore(section, next);
                    else parent.appendChild(section);
                }
                if (window.cur_frm === frm) render(frm);
            },
        });
        dialog.body.classList.add("qcmc-tags-dialog-body");
        const hint = document.createElement("p");
        hint.className = "text-muted small";
        hint.textContent = __("Type a tag and press Enter to add it.");
        dialog.body.appendChild(hint);
        inputWrapper?.classList.add("qcmc-tags-input-wrap");
        dialog.body.appendChild(section);
        dialog.show();
        frm.tags?.tags?.activate();
        input?.setAttribute("aria-label", __("Add tag"));
        input?.focus();
    }

    function isCollapsed() {
        const key = preferenceKey();
        try {
            const stored = window.localStorage.getItem(key);
            if (stored !== null) return stored === "collapsed";
        } catch (error) { /* Browser storage is optional. */ }
        return preferences.get(key) || false;
    }

    function remember(collapsed) {
        const key = preferenceKey();
        preferences.set(key, collapsed);
        try {window.localStorage.setItem(key, collapsed ? "collapsed" : "expanded");}
        catch (error) { /* Keep the preference in memory for this session. */ }
    }

    function ensureStyles() {
        if (!stylesAdded) {
            const style = document.createElement("style");
            style.textContent = `
                .qcmc-action-tooltip{pointer-events:none}
                .qcmc-document-shortcut,.qcmc-document-details-toggle{cursor:pointer}
                .qcmc-document-shortcut svg,.qcmc-document-details-toggle svg{pointer-events:none}
                .qcmc-document-info{display:grid;gap:14px;overflow-wrap:anywhere}
                .qcmc-document-info>div{display:grid;gap:3px}
                .qcmc-document-shortcut[aria-pressed="true"]{color:var(--text-color,#1f272e);--icon-fill:currentColor;--icon-stroke:currentColor}
                .qcmc-document-shortcut[aria-pressed="true"] svg{fill:currentColor;stroke:currentColor}
                .qcmc-tags-dialog-body .form-tags{padding:0;margin:0;border:0}
                .qcmc-tags-dialog-body .form-sidebar-items{display:none}
                .qcmc-tags-dialog-body .qcmc-tags-input-wrap{display:block!important}
                .qcmc-tags-dialog-body .awesomplete{display:block;width:100%}
                .qcmc-tags-dialog-body .tags-input{width:100%;height:36px;padding:8px 10px;margin:0 0 8px!important;border:1px solid var(--border-color,#ddd);border-radius:7px;background:var(--control-bg,#f3f3f3);font-size:13px}
                .qcmc-tags-dialog-body .tags-input:focus{border-color:var(--primary,#5387ed);box-shadow:0 0 0 2px #5387ed18}
                .qcmc-tags-dialog-body .form-tag-row{margin:4px 6px 0 0}
                .qcmc-document-details-toggle{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;padding:5px!important;border:1px solid var(--border-color,#ddd);border-radius:8px;flex-shrink:0}
                .qcmc-document-details-toggle svg{width:16px;height:16px;flex-shrink:0}
                .qcmc-document-shortcuts{display:flex;flex-direction:column;gap:10px;padding:14px 5px;flex-shrink:0;position:relative;z-index:3;pointer-events:none}
                .qcmc-document-shortcut{display:flex;align-items:center;justify-content:center;width:30px;height:30px;padding:5px!important;color:var(--text-muted);border-radius:7px;pointer-events:auto}
                .qcmc-document-shortcut:hover{background:var(--control-bg,#f3f3f3);color:var(--text-color)}
                .qcmc-document-shortcut svg{width:16px;height:16px}
                .qcmc-document-details-toggle[hidden],.qcmc-sidebar-edge[hidden],.qcmc-document-shortcuts[hidden],.qcmc-document-shortcut[hidden]{display:none!important}
                @media(min-width:992px){
                    .qcmc-document-details-layout{position:relative;--qcmc-details-width:var(--form-sidebar-width,277px)}
                    .qcmc-document-details-layout>.layout-side-section:not(.hide-sidebar){display:flex;flex-direction:column}
                    .qcmc-document-details-layout>.layout-side-section{width:var(--qcmc-details-width);min-width:var(--qcmc-details-width);max-width:var(--qcmc-details-width);flex:0 0 var(--qcmc-details-width);overflow-x:hidden;transition:width .3s cubic-bezier(.4,0,.2,1),min-width .3s cubic-bezier(.4,0,.2,1),max-width .3s cubic-bezier(.4,0,.2,1),flex-basis .3s cubic-bezier(.4,0,.2,1)}
                    .qcmc-document-details-layout>.layout-main-section-wrapper{width:0!important;min-width:0;max-width:100%;flex:1 1 0!important}
                    .qcmc-document-details-layout>.layout-side-section>.form-sidebar{flex:1 0 auto;opacity:1;visibility:visible;transition:opacity .2s cubic-bezier(.4,0,.2,1),visibility 0s}
                    .qcmc-document-details-layout>.layout-side-section>.qcmc-document-details-toggle{position:sticky;bottom:10px;align-self:flex-start;margin:10px 5px;background:var(--control-bg,#f3f3f3);z-index:3}
                    .qcmc-sidebar-edge{position:absolute;top:0;bottom:0;width:5px;padding:0;border:0;background:transparent;z-index:4;cursor:col-resize;user-select:none}
                    .qcmc-document-details-layout>.layout-side-section>.qcmc-sidebar-edge{inset-inline-start:0}
                    .qcmc-sidebar-edge::after{content:"";position:absolute;inset-inline-start:0;top:0;bottom:0;width:2px;background:transparent;transition:background .15s ease}
                    .qcmc-sidebar-edge:hover::after{background:var(--ink-gray-2,#e2e2e2)}
                    .qcmc-document-details-collapsed>.layout-side-section{width:40px;min-width:40px;max-width:40px;flex-basis:40px}
                    .qcmc-document-details-collapsed>.layout-main-section-wrapper{--page-max-width:100%}
                    .qcmc-document-details-collapsed>.layout-side-section>.form-sidebar{opacity:0;visibility:hidden;pointer-events:none;max-height:0;overflow:hidden;flex:0 0 auto;transition:opacity .15s cubic-bezier(.4,0,.2,1),visibility 0s .3s}
                    .qcmc-document-details-collapsed>.layout-side-section>.qcmc-document-details-toggle{margin-top:auto}
                }
                @media(min-width:992px) and (max-width:1199px){.qcmc-document-details-layout{--qcmc-details-width:calc(38vw - var(--sidebar-width,220px))}}
                @media(prefers-reduced-motion:reduce){.qcmc-document-details-layout>.layout-side-section,.qcmc-document-details-layout>.layout-side-section>.form-sidebar{transition:none}}
                @media(max-width:991px){.qcmc-document-details-toggle,.qcmc-sidebar-edge,.qcmc-document-shortcuts{display:none}}
            `;
            document.head.appendChild(style); stylesAdded = true;
        }
    }

    function render(frm) {
        if (!frm?.doc || !frappe.session || frappe.session.user === "Guest") return;
        const sidebar = frm.page?.sidebar?.[0];
        const layout = sidebar?.parentElement;
        if (!sidebar || !layout) return;
        ensureStyles();
        if (!frm._qcmcDocumentDetailsToggle) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "btn btn-default btn-sm qcmc-document-details-toggle";
            const toggle = event => {
                event.preventDefault();
                event.stopPropagation();
                remember(!isCollapsed());
                render(frm);
            };
            button.addEventListener("click", toggle);
            const edge = document.createElement("div");
            edge.className = "qcmc-sidebar-edge";
            edge.setAttribute("aria-hidden", "true");
            edge.addEventListener("click", toggle);
            const shortcuts = document.createElement("div");
            shortcuts.className = "qcmc-document-shortcuts";
            shortcuts.setAttribute("role", "group");
            shortcuts.setAttribute("aria-label", __("Document actions"));
            actions.forEach(action => {
                const shortcut = document.createElement("button");
                shortcut.type = "button";
                shortcut.className = "btn btn-link qcmc-document-shortcut";
                tooltip(shortcut, __(action.label), false);
                shortcut.innerHTML = `<svg class="icon icon-sm" aria-hidden="true" focusable="false"><use href="#icon-${action.icon}"></use></svg>`;
                shortcut.addEventListener("click", event => {
                    event.preventDefault(); event.stopPropagation();
                    if (action.command === "rename") {
                        if (frm.toolbar?.can_rename?.()) frm.rename_doc();
                        return;
                    }
                    if (action.command === "info") {openInfo(frm); return;}
                    const target = sidebar.querySelector(action.target);
                    if (!target) return;
                    if (action.focus) openTags(frm, sidebar);
                    else if (action.favorite) {
                        // The native heart is SVG, not an HTMLElement with
                        // .click(). Trigger its existing jQuery handler.
                        const wrapper = sidebar.querySelector(".liked-by");
                        if (wrapper?.style.getPropertyValue("pointer-events") === "none") return;
                        $(target).trigger("click");
                    }
                    else target.click();
                });
                shortcuts.appendChild(shortcut);
            });
            frm._qcmcDocumentDetailsToggle = {button, edge, shortcuts};
        }
        const {button, edge, shortcuts} = frm._qcmcDocumentDetailsToggle;
        const available = !frm.doc.__islocal && !frm.meta?.istable && !frm.page.hide_sidebar && Boolean(sidebar.querySelector(".form-sidebar"));
        const collapsed = available && isCollapsed();
        layout.classList.add("qcmc-document-details-layout");
        layout.classList.toggle("qcmc-document-details-collapsed", collapsed);
        if (!sidebar.id) sidebar.id = `qcmc-document-details-${++sidebarId}`;
        const label = __(collapsed ? "Show details" : "Hide details");
        button.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true" focusable="false"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16M${collapsed ? "10 9l-3 3 3 3" : "7 9l3 3-3 3"}"/></svg>`;
        tooltip(button, label, collapsed);
        button.setAttribute("aria-expanded", String(!collapsed));
        button.setAttribute("aria-controls", sidebar.id);
        button.hidden = !available;
        shortcuts.hidden = !collapsed;
        actions.forEach((action, index) => {
            const shortcut = shortcuts.children[index];
            tooltip(shortcut, shortcut.getAttribute("aria-label"), collapsed);
            if (action.command) {
                shortcut.hidden = action.command === "rename" && !frm.toolbar?.can_rename?.();
                return;
            }
            const section = action.section ? sidebar.querySelector(action.section) : null;
            const target = sidebar.querySelector(action.target);
            shortcut.hidden = !target || target.disabled || Boolean(target && getComputedStyle(target).display === "none") || Boolean(section && getComputedStyle(section).display === "none");
            if (action.favorite) {
                const wrapper = sidebar.querySelector(".liked-by");
                const sync = () => {
                    const liked = Boolean(wrapper?.classList.contains("liked"));
                    shortcut.setAttribute("aria-pressed", String(liked));
                    tooltip(shortcut, __(liked ? "Remove from favorites" : "Favorite"), !shortcuts.hidden);
                };
                sync();
                const controls = frm._qcmcDocumentDetailsToggle;
                if (controls.likeWrapper !== wrapper) {
                    controls.likeObserver?.disconnect();
                    controls.likeWrapper = wrapper;
                    if (wrapper && typeof MutationObserver !== "undefined") {
                        controls.likeObserver = new MutationObserver(sync);
                        controls.likeObserver.observe(wrapper, {attributes: true, attributeFilter: ["class"]});
                    }
                }
            }
        });
        edge.hidden = !available;
        tooltip(edge, __("Click to show or hide details"), collapsed);
        sidebar.prepend(edge);
        sidebar.appendChild(shortcuts);
        sidebar.appendChild(button);
    }

    function renderActiveForm() {
        if (frappe.get_route?.()?.[0] === "Form") render(window.cur_frm);
    }
    $(document).on("form-refresh", (event, frm) => render(frm));
    $(document).on("page-change", renderActiveForm);
    $(document).on("app_ready", renderActiveForm);
})();
