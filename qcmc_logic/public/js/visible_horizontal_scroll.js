/* Keep horizontal scrolling within reach on long desktop lists and tables. */
(() => {
    const targets = new Map();
    let bar, spacer, active, scheduled = false;

    function schedule() {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => {scheduled = false; update();});
    }

    function makeBar() {
        if (bar) return;
        const style = document.createElement("style");
        style.textContent = `
            .qcmc-horizontal-scroll{position:fixed;bottom:8px;height:16px;overflow-x:scroll;overflow-y:hidden;z-index:1021;background:var(--card-bg,#fff);border:1px solid var(--border-color,#ddd);border-radius:5px;box-shadow:0 -2px 6px #0000000a;scrollbar-width:auto;scrollbar-color:var(--gray-400,#b9b9b9) var(--control-bg,#f3f3f3)}
            .qcmc-horizontal-scroll::-webkit-scrollbar{height:12px}
            .qcmc-horizontal-scroll::-webkit-scrollbar-track{background:var(--control-bg,#f3f3f3);border-radius:5px}
            .qcmc-horizontal-scroll::-webkit-scrollbar-thumb{background:var(--gray-400,#b9b9b9);border-radius:5px;border:2px solid var(--control-bg,#f3f3f3)}
            .qcmc-horizontal-scroll>div{height:1px;pointer-events:none}
            .qcmc-horizontal-scroll[hidden]{display:none!important}
            @media(max-width:767px){.qcmc-horizontal-scroll{display:none}}
        `;
        document.head.appendChild(style);
        bar = document.createElement("div");
        bar.className = "qcmc-horizontal-scroll";
        bar.setAttribute("role", "region");
        bar.setAttribute("aria-label", __("Scroll columns horizontally"));
        bar.setAttribute("tabindex", "0");
        bar.hidden = true;
        spacer = document.createElement("div");
        bar.appendChild(spacer);
        bar.addEventListener("scroll", () => {
            if (active && active.scrollLeft !== bar.scrollLeft) active.scrollLeft = bar.scrollLeft;
        });
        document.body.appendChild(bar);
    }

    function update() {
        if (!bar) return;
        let selected = null, area = 0;
        const height = window.innerHeight;
        targets.forEach((record, root) => {
            if (!root.isConnected) {
                root.removeEventListener("scroll", record.onScroll);
                record.resize?.disconnect(); record.mutation?.disconnect();
                targets.delete(root);
                return;
            }
            if (window.matchMedia?.("(max-width:767px)").matches) return;
            const nativeRect = root.getBoundingClientRect();
            const viewportRect = record.viewport.getBoundingClientRect();
            const rect = {
                left: Math.max(nativeRect.left, viewportRect.left),
                right: Math.min(nativeRect.right, viewportRect.right),
                top: Math.max(nativeRect.top, viewportRect.top),
                bottom: Math.min(nativeRect.bottom, viewportRect.bottom),
                width: Math.min(nativeRect.width, viewportRect.width),
            };
            if (root.scrollWidth <= root.clientWidth + 1 || rect.width <= 0 || rect.top >= height - 32 || rect.bottom <= 24) return;
            const visible = Math.min(rect.bottom, height - 8) - Math.max(rect.top, 0);
            if (visible > area) {area = visible; selected = {root, rect};}
        });
        active = selected?.root || null;
        bar.hidden = !active;
        if (!active) return;
        const left = Math.max(0, selected.rect.left + (active.clientLeft || 0));
        const right = Math.min(window.innerWidth - 8, selected.rect.right);
        const width = right - left;
        if (width <= 0) {bar.hidden = true; active = null; return;}
        bar.style.setProperty("left", `${left}px`);
        bar.style.setProperty("top", `${Math.min(height - 24, selected.rect.bottom - 16)}px`);
        bar.style.setProperty("bottom", "auto");
        bar.style.setProperty("width", `${width}px`);
        bar.style.setProperty("direction", getComputedStyle(active).direction);
        // Match the scroll range even if part of the table is horizontally
        // clipped by the viewport. RTL uses the same native negative offsets.
        spacer.style.setProperty("width", `${active.scrollWidth - active.clientWidth + (bar.clientWidth || width)}px`);
        if (bar.scrollLeft !== active.scrollLeft) bar.scrollLeft = active.scrollLeft;
    }

    function register(root, viewport = root) {
        if (!root) return;
        makeBar();
        if (!targets.has(root)) {
            const onScroll = () => {
                if (active === root && bar.scrollLeft !== root.scrollLeft) bar.scrollLeft = root.scrollLeft;
            };
            const record = {onScroll, viewport};
            root.addEventListener("scroll", onScroll, {passive: true});
            if (typeof ResizeObserver !== "undefined") {
                record.resize = new ResizeObserver(schedule);
                record.resize.observe(root);
                if (viewport !== root) record.resize.observe(viewport);
                if (root.firstElementChild) record.resize.observe(root.firstElementChild);
            }
            if (typeof MutationObserver !== "undefined") {
                record.mutation = new MutationObserver(schedule);
                record.mutation.observe(root, {subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["style", "class"]});
            }
            targets.set(root, record);
        }
        schedule();
    }

    frappe.qcmc_horizontal_scroll = {register, refresh: schedule};
    window.addEventListener("scroll", schedule, {capture: true, passive: true});
    window.addEventListener("resize", schedule, {passive: true});
    $(document).on("page-change", () => {if (bar) bar.hidden = true; active = null; schedule();});
    $(document).on("shown.bs.tab", schedule);
})();
