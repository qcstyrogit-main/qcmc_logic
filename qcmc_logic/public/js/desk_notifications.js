/* Announcement notifications open the accessible popup; the bell counts unread logs. */
(() => {
    const api = 'qcmc_logic.api.desk_notifications.';
    const bellSelector = '.navbar .dropdown-notifications > a, .navbar .dropdown-notifications > button, .sidebar-notification, .notifications-icon';
    let unread = 0, sequence = 0, listSequence = 0, opening = false, initialized = false;
    function renderBadge() {
        const hosts = new Set(Array.from(document.querySelectorAll(bellSelector), element => element.closest?.('a,button') || element));
        hosts.forEach(icon => {
            icon.classList.add('qcmc-notification-bell');
            let badge = icon.querySelector('.qcmc-notification-count');
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'qcmc-notification-count';
                badge.setAttribute('aria-hidden', 'true');
                icon.appendChild(badge);
            }
            const label = unread > 99 ? '99+' : String(unread);
            if (badge.textContent !== label) badge.textContent = label;
            badge.hidden = !unread;
            icon.setAttribute('aria-label', __('Notifications: {0} unread', [unread]));
        });
    }
    function closeNotifications(target) {
        const dropdown = $(target).closest('.dropdown-notifications');
        if (dropdown.closest('.navbar, .desktop-notifications').length) {
            dropdown.data('closable', true).dropdown('hide');
        } else {
            dropdown.addClass('hidden');
        }
    }
    async function refreshList() {
        const view = frappe.app?.sidebar?.notifications?.tabs?.notifications;
        if (!view?.render_notifications_dropdown) return;
        // Both Frappe and the installed navbar override use this same view.
        // Avoid its old cached GET response and refresh the complete list.
        view.update_dropdown = refreshList;
        const current = ++listSequence;
        try {
            const response = await frappe.call({method: api + 'get_notification_logs', args: {limit: 20}, type: 'POST', silent: true});
            if (current !== listSequence) return;
            view.dropdown_items = response.message.notification_logs;
            frappe.update_user_info(response.message.user_info);
            view.render_notifications_dropdown();
        } catch (error) {console.warn('Could not update notification list', error);}
    }
    async function refreshNotifications() {
        await refreshCount();
        await refreshList();
    }
    async function refreshCount() {
        const current = ++sequence;
        try {
            const response = await frappe.call({method: api + 'get_unread_count', silent: true});
            if (current !== sequence) return;
            unread = Math.max(0, Number(response.message) || 0);
            renderBadge();
        } catch (error) {console.warn('Could not update notification count', error);}
    }
    async function initialize() {
        if (initialized || !frappe.session?.user || frappe.session.user === 'Guest') return;
        initialized = true;
        const style = document.createElement('style');
        style.textContent = `.qcmc-notification-bell{position:relative!important;overflow:visible!important}
            .qcmc-notification-count{display:inline-block!important;position:absolute;top:-3px;inset-inline-end:-5px;z-index:100;min-width:16px;height:16px;padding:0 4px;border-radius:9px;background:var(--red-500,#e5484d);color:#fff;font-size:10px;line-height:16px;font-weight:650;text-align:center;pointer-events:none;box-shadow:0 0 0 2px var(--navbar-bg,#fff)}
            .qcmc-notification-count[hidden]{display:none!important}`;
        document.head.appendChild(style);
        new MutationObserver(renderBadge).observe(document.body, {childList: true, subtree: true});
        frappe.realtime?.on('notification', refreshNotifications);
        frappe.realtime?.on('qcmc_notifications_read', refreshNotifications);
        frappe.realtime?.on('connect', refreshNotifications);
        window.addEventListener('focus', refreshNotifications);
        // Recover automatically if the browser's socket drops or misses events.
        setInterval(() => {if (document.visibilityState !== 'hidden') return refreshNotifications();}, 15000);
        $(document).on('ajaxComplete.qcmcNotificationCount', (event, xhr, settings) => {
            const method = settings?.data?.method || settings?.url || '';
            if (/notification_log\.(mark_as_read|mark_all_as_read)/.test(method)) refreshCount();
        });
        document.addEventListener('click', async event => {
            const close = event.target.closest?.('.close-notification-dialogue');
            if (close) {
                // Native Frappe hides the whole container, including the desktop bell.
                event.preventDefault(); event.stopImmediatePropagation();
                closeNotifications(close);
                return;
            }
            const item = event.target.closest?.('a.notification-item[data-name]');
            if (!item || event.target.closest?.('.mark-as-read')) return;
            let url;
            try {url = new URL(item.getAttribute('href'), window.location.origin);}
            catch (error) {return;}
            const legacy = /^\/(desk|app)\/(announcements|email-queue)\//i.test(url.pathname) || /^\/desk\/Form\/(Announcements|Email%20Queue)\//i.test(url.pathname);
            if (!url.searchParams.has('qcmc_announcement') && !legacy) return;
            event.preventDefault(); event.stopImmediatePropagation();
            if (opening) return;
            opening = true;
            try {
                const response = await frappe.call({method: api + 'open_announcement_notification', args: {notification: item.dataset.name}, type: 'POST'});
                if (!response.message.announcement) {
                    window.location.assign(url.href);
                    return;
                }
                item.classList.remove('unread');
                // The modern sidebar uses a custom menu instead of Bootstrap.
                // Hide its notification list without toggling a second bell.
                closeNotifications(item);
                await frappe.qcmc_login_notices.open(response.message.announcement, response.message.comment || null);
                await refreshCount();
            } catch (error) {console.warn('Could not open announcement notification', error);}
            finally {opening = false;}
        }, true);
        await refreshNotifications();
    }
    $(document).on('app_ready', initialize);
    // App scripts can also be loaded after the one-shot app_ready event.
    if (frappe.boot && frappe.session?.user) initialize();
})();
