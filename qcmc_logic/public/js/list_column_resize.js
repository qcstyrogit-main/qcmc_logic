/* Shared resize engine with personal widths for ERP lists and form tables. */
(() => {
    const setting = "qcmc_list_column_widths";
    const properties = ["width", "min-width", "max-width", "flex"];
    const narrowScreen = window.matchMedia?.("(max-width: 767px)");
    let stylesAdded = false;
    let cancelActiveDrag = null;
    const saveQueues = new Map();
    const settingFor = list => list.qcmcResizeAdapter?.setting || setting;
    const minimum = (index, list) => list.qcmcResizeAdapter?.minimum ?? (index === 0 ? 160 : 80);
    const keyFor = column => column.df?.fieldname ? `field:${column.df.fieldname}` : `type:${column.type}`;
    const clamp = (width, index, list) => Math.round(Math.max(minimum(index, list), Math.min(1200, width)));
    const groups = list => list.qcmcResizeAdapter?.groups() || Array.from(list.$result[0].querySelectorAll(".list-row-head .list-header-subject, .list-row .level-left"));
    const cells = (group, list) => list.qcmcResizeAdapter?.cells(group) || Array.from(group.querySelectorAll(":scope > .list-row-col"));

    function stateFor(list) {
        if (!list._qcmcColumnResize) {
            const saved = frappe.get_user_settings(list.doctype, settingFor(list));
            const widths = {};
            Object.entries(saved || {}).forEach(([key, width]) => {
                if (/^(field:|type:)/.test(key) && typeof width === "number" && Number.isFinite(width)) widths[key] = width;
            });
            list._qcmcColumnResize = {widths, baselines: new Map(), saveQueue: Promise.resolve()};
        }
        return list._qcmcColumnResize;
    }

    function restoreCell(state, cell) {
        const baseline = state.baselines.get(cell);
        if (!baseline) return;
        baseline.forEach(([property, value, priority]) => {
            if (value) cell.style.setProperty(property, value, priority);
            else cell.style.removeProperty(property);
        });
        state.baselines.delete(cell);
    }

    function restoreAll(list) {
        const state = list?._qcmcColumnResize;
        state?.cancelDrag?.();
        if (state) Array.from(state.baselines.keys()).forEach(cell => restoreCell(state, cell));
        list?.qcmcResizeAdapter?.onRestore?.();
    }

    function applyWidth(list, index, width) {
        const state = stateFor(list);
        if (width == null) width = list.qcmcResizeAdapter?.defaultWidth?.(index) ?? null;
        groups(list).forEach(group => {
            const cell = cells(group, list)[index];
            if (!cell) return;
            if (width == null) restoreCell(state, cell);
            else {
                width = clamp(width, index, list);
                if (!state.baselines.has(cell)) {
                    state.baselines.set(cell, properties.map(property => [property, cell.style.getPropertyValue(property), cell.style.getPropertyPriority(property)]));
                }
                ["width", "min-width", "max-width"].forEach(property => cell.style.setProperty(property, `${width}px`));
                cell.style.setProperty("flex", `0 0 ${width}px`);
            }
            cell.querySelector(".qcmc-list-column-resizer")?.setAttribute("aria-valuenow", Math.round(cell.getBoundingClientRect().width));
        });
        list.qcmcResizeAdapter?.afterApply?.();
        frappe.qcmc_horizontal_scroll?.refresh();
    }

    function persist(list) {
        const state = stateFor(list);
        const snapshot = {...state.widths};
        // Serialize saves so a quick second resize cannot be overwritten by an
        // older request. Null values also survive Frappe's settings-object merge.
        const queueKey = `${frappe.session.user}:${list.doctype}`;
        state.saveQueue = (saveQueues.get(queueKey) || Promise.resolve()).then(() => frappe.model.user_settings.save(list.doctype, settingFor(list), snapshot)).catch(error => {
            console.warn("Could not save column widths", error);
            frappe.show_alert?.({message: __("Column width could not be saved. Please try resizing again."), indicator: "orange"});
        });
        saveQueues.set(queueKey, state.saveQueue);
    }

    function contentWidth(cell) {
        // Measure an unconstrained copy: scrollWidth alone misses text clipped
        // by nested ellipsis wrappers and grid controls. Keep the copy inside
        // the original cell so it inherits the same theme and field styles.
        const copy = cell.cloneNode(true);
        copy.querySelectorAll(".qcmc-list-column-resizer").forEach(handle => handle.remove());
        const style = getComputedStyle(cell);
        ["font", "letter-spacing", "padding-left", "padding-right", "border-left-width", "border-right-width", "box-sizing"].forEach(property => {
            const value = style.getPropertyValue?.(property);
            if (value) copy.style.setProperty(property, value, "important");
        });
        [copy, ...copy.querySelectorAll("*")].forEach(node => {
            node.removeAttribute("id");
            node.removeAttribute("autofocus");
            node.style.setProperty("min-width", "0", "important");
            node.style.setProperty("max-width", "none", "important");
            node.style.setProperty("text-overflow", "clip", "important");
            // Frappe formatters indent their HTML with tabs/newlines. Match
            // normal rendering rather than measuring that markup whitespace.
            node.style.setProperty("white-space", "nowrap", "important");
            if (!["svg", "use", "path", "img"].includes(node.tagName?.toLowerCase())) {
                node.style.setProperty("width", "max-content", "important");
                node.style.setProperty("flex", "0 0 auto", "important");
            }
        });
        // Native input widths describe the editor, rather than its value.
        const originals = cell.querySelectorAll("input,textarea,select");
        copy.querySelectorAll("input,textarea,select").forEach((input, index) => {
            if (["checkbox", "radio", "hidden"].includes(input.type)) return;
            const text = document.createElement("span");
            const original = originals[index];
            text.textContent = original?.selectedOptions?.[0]?.text || original?.value || "";
            text.style.setProperty("font", getComputedStyle(original).font);
            input.replaceWith(text);
        });
        copy.setAttribute("aria-hidden", "true");
        copy.style.setProperty("position", "fixed", "important");
        copy.style.setProperty("inset", "0 auto auto -100000px", "important");
        copy.style.setProperty("visibility", "hidden", "important");
        copy.style.setProperty("pointer-events", "none", "important");
        cell.appendChild(copy);
        try {return Math.ceil(copy.getBoundingClientRect().width) + 10;}
        finally {copy.remove();}
    }

    function autoFit(list, index) {
        cancelActiveDrag?.();
        let width = minimum(index, list);
        groups(list).forEach(group => {
            const cell = cells(group, list)[index];
            if (cell) width = Math.max(width, contentWidth(cell));
        });
        width = clamp(width, index, list);
        stateFor(list).widths[keyFor(list.columns[index])] = width;
        applyWidth(list, index, width);
        persist(list);
    }

    function addHandle(list, cell, column, index) {
        const key = keyFor(column);
        const previous = cell.querySelector(".qcmc-list-column-resizer");
        if (previous?.qcmcColumnKey === key) return;
        previous?.remove();
        const handle = document.createElement("span");
        handle.className = "qcmc-list-column-resizer";
        handle.qcmcColumnKey = key;
        handle.setAttribute("role", "separator");
        handle.setAttribute("tabindex", "0");
        handle.setAttribute("aria-orientation", "vertical");
        handle.setAttribute("aria-valuemin", minimum(index, list));
        handle.setAttribute("aria-valuemax", 1200);
        handle.setAttribute("aria-valuenow", Math.round(cell.getBoundingClientRect().width));
        const label = column.df?.label || column.type;
        handle.setAttribute("aria-label", __("Resize {0} column", [label]));
        handle.setAttribute("title", __("Drag to resize {0}. Double-click to fit loaded values. Arrow keys adjust width; Home resets.", [label]));
        const direction = () => getComputedStyle(list.$result[0]).direction === "rtl" ? -1 : 1;
        const reset = () => {
            stateFor(list).widths[key] = null;
            applyWidth(list, index, null);
            persist(list);
        };
        let drag = null;
        const finish = cancelled => {
            if (!drag) return;
            const current = drag;
            drag = null;
            const state = stateFor(list);
            if (cancelActiveDrag === state.cancelDrag) cancelActiveDrag = null;
            state.cancelDrag = null;
            document.body.classList.remove("qcmc-resizing-list-column");
            if (cancelled) applyWidth(list, index, stateFor(list).widths[key] ?? null);
            else if (current.moved) {
                stateFor(list).widths[key] = current.width;
                applyWidth(list, index, current.width);
                persist(list);
            }
            if (handle.hasPointerCapture?.(current.pointerId)) handle.releasePointerCapture(current.pointerId);
        };
        handle.addEventListener("click", event => event.stopPropagation());
        handle.addEventListener("dblclick", event => {event.preventDefault(); event.stopPropagation(); autoFit(list, index);});
        handle.addEventListener("pointerdown", event => {
            if (event.button !== 0 || event.isPrimary === false || drag) return;
            event.preventDefault(); event.stopPropagation();
            cancelActiveDrag?.();
            drag = {pointerId: event.pointerId, x: event.clientX, startWidth: cell.getBoundingClientRect().width, moved: false};
            cancelActiveDrag = stateFor(list).cancelDrag = () => finish(true);
            handle.setPointerCapture(event.pointerId);
            document.body.classList.add("qcmc-resizing-list-column");
        });
        handle.addEventListener("pointermove", event => {
            if (!drag || drag.pointerId !== event.pointerId) return;
            const delta = (event.clientX - drag.x) * direction();
            if (!drag.moved && Math.abs(delta) < 3) return;
            drag.moved = true;
            drag.width = clamp(drag.startWidth + delta, index, list);
            applyWidth(list, index, drag.width);
        });
        handle.addEventListener("pointerup", event => {if (drag?.pointerId === event.pointerId) finish(false);});
        handle.addEventListener("pointercancel", () => finish(true));
        handle.addEventListener("lostpointercapture", () => finish(true));
        handle.addEventListener("keydown", event => {
            if (event.key === "Escape" && drag) {event.preventDefault(); event.stopPropagation(); finish(true); return;}
            if (!["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
            event.preventDefault(); event.stopPropagation();
            if (event.key === "Home") {reset(); return;}
            const step = (event.shiftKey ? 50 : 10) * (event.key === "ArrowRight" ? 1 : -1) * direction();
            const width = clamp(cell.getBoundingClientRect().width + step, index, list);
            stateFor(list).widths[key] = width;
            applyWidth(list, index, width);
            persist(list);
        });
        cell.appendChild(handle);
    }

    function enhance(list) {
        if (!list || (list.view_name !== "List" && !list.qcmcResizeAdapter) || !list.$result?.[0] || !list.columns || frappe.session?.user === "Guest") return;
        const rootClass = list.qcmcResizeAdapter?.rootClass || "qcmc-resizable-list";
        if (narrowScreen?.matches) {
            restoreAll(list);
            list.$result[0].classList?.remove(rootClass);
            return;
        }
        const header = list.qcmcResizeAdapter?.header() || list.$result[0].querySelector(".list-row-head .list-header-subject");
        if (!header) return;
        list.$result[0].classList?.add(rootClass);
        const state = stateFor(list);
        const headers = cells(header, list);
        list.columns.forEach((column, index) => {
            if (!headers[index]) return;
            addHandle(list, headers[index], column, index);
            const width = state.widths[keyFor(column)] ?? list.qcmcResizeAdapter?.defaultWidth?.(index);
            if (typeof width === "number" && Number.isFinite(width)) applyWidth(list, index, width);
        });
        const root = list.$result[0];
        if (list.qcmcResizeAdapter) frappe.qcmc_horizontal_scroll?.register(root);
        else {
            // overflow-y:hidden on Frappe's inner .result can make it the
            // horizontal scroller, while .result-container scrolls vertically.
            // Register both; only the one with horizontal overflow is shown.
            frappe.qcmc_horizontal_scroll?.register(root, root.parentElement || root);
            frappe.qcmc_horizontal_scroll?.register(root.parentElement);
        }
    }

    function install() {
        // A route change can detach the captured header before pointerup.
        cancelActiveDrag?.();
        if (!stylesAdded) {
            const style = document.createElement("style");
            style.textContent = `
                .qcmc-resizable-list .list-row-head .list-header-subject>.list-row-col{position:relative;padding-inline-end:10px}
                .qcmc-list-column-resizer{position:absolute;inset-inline-end:0;top:0;bottom:0;width:8px;cursor:col-resize;touch-action:none;user-select:none;z-index:1}
                .qcmc-list-column-resizer::after{content:"";position:absolute;top:25%;bottom:25%;inset-inline-start:3px;width:2px;background:var(--border-color,#dce3ed);border-radius:2px}
                .qcmc-list-column-resizer:hover::after,.qcmc-list-column-resizer:focus-visible::after{background:#5387ed}
                .qcmc-list-column-resizer:focus-visible{outline:2px solid #5387ed;outline-offset:-2px}
                .qcmc-resizing-list-column,.qcmc-resizing-list-column *{cursor:col-resize!important;user-select:none!important}
                @media(max-width:767px){.qcmc-list-column-resizer{display:none}}
            `;
            document.head.appendChild(style);
            stylesAdded = true;
        }
        const prototype = frappe.views?.ListView?.prototype;
        if (prototype && !prototype._qcmcColumnResizeInstalled) {
            const render = prototype.render_list;
            prototype.render_list = function (...args) {
                restoreAll(this);
                const result = render.apply(this, args);
                enhance(this);
                return result;
            };
            prototype._qcmcColumnResizeInstalled = true;
        }
        enhance(window.cur_list);
    }

    // Form tables provide a DOM adapter and reuse the same drag/save lifecycle.
    frappe.qcmc_column_resize = {enhance, restoreAll};
    // ListView is lazy-loaded, so app_ready alone is insufficient.
    $(document).on("app_ready", install);
    $(document).on("page-change", install);
    narrowScreen?.addEventListener?.("change", () => {restoreAll(window.cur_list); enhance(window.cur_list);});
})();
