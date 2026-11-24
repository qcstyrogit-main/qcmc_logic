/* Frappe persists Page scripts in localStorage even across hard refreshes. */
(() => {
    const revision = "pcw-create-ui-20261110-4";
    const key = "_page:process-card-workbench";
    try {
        const cached = localStorage.getItem(key);
        if (cached && !cached.includes(revision)) localStorage.removeItem(key);
    } catch (error) {
        // Desk must still load when the browser blocks localStorage.
    }
})();
