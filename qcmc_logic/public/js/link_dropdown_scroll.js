/* Floating, vertically scrollable Frappe Link suggestions.
 * Uses a temporary body portal to prevent transformed child-row editors/modal
 * containers from offsetting a position:fixed dropdown. Preserves Frappe's
 * original Awesomplete instance, native selection and search behavior.
 */
(() => {
    if (window.qcmc_link_dropdown_scroll_installed) return;
    window.qcmc_link_dropdown_scroll_installed = true;

    const style = document.createElement("style");
    style.id = "qcmc-link-dropdown-scroll-style";
    style.textContent = `
        body > ul.qcmc-floating-link-list {
            position: fixed !important;
            z-index: 110000 !important;
            max-height: 220px !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            overscroll-behavior: contain;
            scrollbar-width: auto;
            scrollbar-color: #a1a1aa #f4f4f5;
            box-sizing: border-box;
            background: var(--card-bg, #fff);
            border: 1px solid var(--border-color, #ddd);
            border-radius: var(--border-radius-md, 6px);
            box-shadow: 0 4px 14px #0000001c;
            margin: 0 !important;
            padding: 0;
            list-style: none;
        }
        body > ul.qcmc-floating-link-list::-webkit-scrollbar { width: 10px; }
        body > ul.qcmc-floating-link-list::-webkit-scrollbar-thumb {
            background: #a1a1aa; border-radius: 6px;
        }
        body > ul.qcmc-floating-link-list::-webkit-scrollbar-track {
            background: #f4f4f5;
        }
        /* Frappe Link results are direct div[role=option] children, containing
           p > strong and span.small. Restore native readable spacing after
           moving the list out of .awesomplete's CSS scope. */
        body > ul.qcmc-floating-link-list > [role="option"] {
            display: block !important;
            box-sizing: border-box;
            cursor: pointer;
            padding: 9px 12px !important;
            margin: 0 !important;
            min-height: 42px;
            font-size: var(--text-base, 13px);
            line-height: 1.5 !important;
            color: var(--text-color, #333);
            text-align: left;
            white-space: normal !important;
            overflow-wrap: break-word;
        }
        body > ul.qcmc-floating-link-list > [role="option"] > p {
            margin: 0 !important;
            padding: 0 !important;
            white-space: normal !important;
            line-height: 1.5 !important;
            overflow-wrap: break-word;
        }
        body > ul.qcmc-floating-link-list > [role="option"] strong {
            display: inline;
            font-weight: 600;
            white-space: normal;
        }
        body > ul.qcmc-floating-link-list > [role="option"] .small {
            font-size: 12px;
            line-height: 1.5;
            white-space: normal;
        }
        body > ul.qcmc-floating-link-list > [role="option"]:hover,
        body > ul.qcmc-floating-link-list > [role="option"][aria-selected="true"] {
            background: var(--control-bg, #f3f4f6) !important;
        }
    `;
    document.head.appendChild(style);

    let input = null;
    let list = null;
    let originalParent = null;
    let originalNextSibling = null;
    let raf = null;
    let observer = null;

    const isLinkInput = (node) => node instanceof HTMLInputElement &&
        !!node.closest(".link-field") && !!node.closest(".awesomplete");

    const close = () => {
        if (raf !== null) cancelAnimationFrame(raf);
        raf = null;
        observer?.disconnect();
        observer = null;
        if (list) {
            list.classList.remove("qcmc-floating-link-list");
            ["left", "top", "width", "max-height"].forEach(key => list.style.removeProperty(key));
            // Put Awesomplete's original UL back exactly where Frappe created it.
            if (originalParent?.isConnected) {
                originalParent.insertBefore(list,
                    originalNextSibling?.parentNode === originalParent ? originalNextSibling : null);
            }
        }
        input = null;
        list = null;
        originalParent = null;
        originalNextSibling = null;
        frappe.qcmc_horizontal_scroll?.refresh?.();
    };

    const position = () => {
        raf = null;
        if (!input || !list || !input.isConnected || !list.isConnected) return;
        const rect = input.getBoundingClientRect();
        const below = Math.max(0, window.innerHeight - rect.bottom - 10);
        const above = Math.max(0, rect.top - 10);
        const flip = below < 130 && above > below;
        const space = flip ? above : below;
        const height = Math.max(40, Math.min(220, space - 2));
        const width = Math.max(220, Math.min(rect.width + 24, window.innerWidth - 16));
        const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
        list.style.setProperty("left", `${Math.round(left)}px`, "important");
        list.style.setProperty("top",
            `${Math.round(flip ? rect.top - Math.min(height, list.scrollHeight) - 2 : rect.bottom + 2)}px`,
            "important");
        list.style.setProperty("width", `${Math.round(width)}px`, "important");
        list.style.setProperty("max-height", `${Math.round(height)}px`, "important");
    };

    const schedule = () => {
        if (raf === null) raf = requestAnimationFrame(position);
    };

    const attach = (node) => {
        if (!isLinkInput(node)) return;
        const container = node.closest(".awesomplete");
        const candidate = container?.querySelector(":scope > ul");
        if (!candidate && node !== input) return;
        if (node !== input || (candidate && candidate !== list)) {
            close();
            if (!candidate) return;
            input = node;
            list = candidate;
            originalParent = list.parentNode;
            originalNextSibling = list.nextSibling;
            // Moving outside the modal/expanded grid avoids transformed-ancestor
            // positioning offsets and clipping; the original UL is reused.
            document.body.appendChild(list);
            list.classList.add("qcmc-floating-link-list");
            observer = new MutationObserver(() => {
                if (list?.hasAttribute("hidden")) close();
            });
            observer.observe(list, {attributes: true, attributeFilter: ["hidden"]});
        }
        schedule();
        frappe.qcmc_horizontal_scroll?.refresh?.();
    };

    document.addEventListener("awesomplete-open", event => attach(event.target), true);
    document.addEventListener("awesomplete-close", event => {
        if (event.target === input) close();
    }, true);
    document.addEventListener("focusout", event => {
        if (event.target === input) setTimeout(() => {
            if (document.activeElement !== input && list?.hasAttribute("hidden")) close();
        }, 180);
    }, true);
    document.addEventListener("scroll", schedule, true);
    window.addEventListener("resize", schedule, {passive: true});
    $(document).on("page-change", close);
})();

