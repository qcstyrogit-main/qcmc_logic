/* Company notices appear once per ERP login, including across page refreshes. */
(() => {
    let started = false;
    let opening = false;
    let noticeDialog = null;

    async function openNotices(manual = false) {
        if (!frappe.session || frappe.session.user === "Guest" || opening || (!manual && started)) return;
        if (manual && noticeDialog) {
            noticeDialog.show();
            return;
        }
        const session = frappe.boot.qcmc_login_notice_session;
        if (!session) return;
        started = true;
        const storageKey = `qcmc-login-notices:${frappe.session.user}`;
        try {
            if (!manual && window.localStorage.getItem(storageKey) === session) return;
        } catch (error) {
            // Restricted storage must not prevent the login popup from opening.
        }

        opening = true;
        try {
            const response = await frappe.call({
                method: "qcmc_logic.api.login_notices.get_login_notices",
                // Loading notices must not block the ERP workspace.
                silent: true,
            });
            const data = response.message;
            if (!data) return;
            const escape = value => frappe.utils.escape_html(String(value ?? ""));
            const month = new Date(data.year, data.month - 1, 1).toLocaleString(
                frappe.boot.lang || "en", {month: "long"}
            );
            const icon = name => {
                const paths = {
                    announcements: '<path d="m3 10 13-5v14L3 14z"/><path d="M7 15v5h4l-1-4M20 8v8"/>',
                    anniversary: '<circle cx="12" cy="9" r="5"/><path d="m8 13-2 8 6-3 6 3-2-8"/>',
                    birthdays: '<path d="M4 12h16v9H4zM4 16c2 3 4-3 6 0s4-3 6 0 4 0 4 0M8 12V8m4 4V8m4 4V8M8 5v1m4-3v3m4-1v1"/>',
                };
                return `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`;
            };
            const empty = (type, title, subtitle) => `<div class="qcmc-empty">
                <span class="qcmc-empty-icon">${icon(type)}</span>
                <strong>${escape(__(title))}</strong><p>${escape(__(subtitle))}</p>
            </div>`;
            const people = (rows, anniversary) => rows.map((row, index) => {
                const words = (row.employee_name || "").trim().split(/\s+/);
                const initials = (words[0]?.[0] || "") + (words.length > 1 ? words[words.length - 1][0] : "");
                const greetingAction = data.can_greet && row.user_id && row.user_id !== frappe.session.user
                    ? `<button type="button" class="qcmc-greet" data-greet-kind="${anniversary ? "anniversary" : "birthdays"}" data-greet-index="${index}" aria-label="${escape(__("Send greeting to {0} in Tweet", [row.employee_name]))}">${escape(__("Send greeting"))}</button>`
                    : (data.can_greet && !row.user_id ? `<span class="qcmc-no-tweet">${escape(__("No Tweet account"))}</span>` : "");
                return `<article class="qcmc-person">
                    <span class="qcmc-avatar ${anniversary ? "qcmc-avatar-gold" : ""}" aria-hidden="true">${escape(initials)}</span>
                    <div class="qcmc-person-details"><strong>${escape(row.employee_name)}</strong>
                        ${row.department ? `<span>${escape(row.department)}</span>` : ""}
                    </div>
                    <div class="qcmc-person-date"><span>${escape(month)} ${escape(row.day)}</span>
                        ${anniversary ? `<span class="qcmc-service">${escape(__(row.years === 1 ? "{0} year" : "{0} years", [row.years]))}</span>` : ""}
                        ${greetingAction}
                    </div>
                </article>`;
            }).join("");
            const announcementImage = row => /^(https?:\/\/|\/(?![\/\\]))/i.test(row.image || "")
                ? `<img src="${escape(row.image)}" alt="${escape(row.title || __("Announcement"))}" loading="lazy">` : "";
            const announcements = data.announcements.map((row, index) => {
                const preview = frappe.utils.html2text(row.announcement || "").replace(/\s+/g, " ").trim();
                return `<article class="qcmc-announcement">
                    <div class="qcmc-announcement-cover">${announcementImage(row) || icon("announcements")}</div>
                    <div class="qcmc-announcement-body"><h4>${escape(row.title || __("Announcement"))}</h4>
                    <p>${escape(preview.slice(0, 160))}${preview.length > 160 ? "…" : ""}</p>
                    <button type="button" class="qcmc-read-more" data-announcement-index="${index}">${escape(__("Read more"))} <span aria-hidden="true">→</span></button></div>
                </article>`;
            }).join("");
            const categories = [
                {id: "announcements", label: __("Announcements"), count: data.announcements.length,
                    heading: __("Company announcements"), description: __("The latest news and updates for our team."),
                    body: announcements ? `<div class="qcmc-announcement-grid">${announcements}</div>` : empty("announcements", "No announcements at the moment.", "You're all caught up. Check back for company updates.")},
                {id: "anniversary", label: __("Anniversary"), count: data.anniversaries.length,
                    heading: __("Celebrating years together"), description: __("Recognizing our team's work anniversaries this month."),
                    body: people(data.anniversaries, true) || empty("anniversary", "No work anniversaries this month.", "Here's to the milestones still to come.")},
                {id: "birthdays", label: __("Birthdays"), count: data.birthdays.length,
                    heading: __("Birthday wishes for our team"), description: __("A little reminder to make someone's day this month."),
                    body: people(data.birthdays, false) || empty("birthdays", "No birthdays this month.", "We'll celebrate the next round of birthdays here.")},
            ];
            const dialog = new frappe.ui.Dialog({
                title: __("Announcements & Celebrations"),
                size: "large",
                fields: [{fieldname: "content", fieldtype: "HTML"}],
                primary_action_label: __("Close"),
                primary_action: () => dialog.hide(),
            });
            dialog.$wrapper.addClass("qcmc-notices-modal");
            dialog.fields_dict.content.$wrapper.html(`
                <style>
                    .qcmc-greeting-modal .modal-content{border-radius:16px;overflow:hidden}
                    .qcmc-greeting-modal .modal-header,.qcmc-greeting-modal .modal-footer{padding:18px 24px}
                    .qcmc-greeting-modal textarea{min-height:160px;line-height:1.7;resize:vertical}
                    .qcmc-greeting-modal .btn{border-radius:8px}
                    .qcmc-notices-modal .modal-content{border:0;border-radius:18px;overflow:hidden;box-shadow:0 24px 80px #11182733}
                    .qcmc-notices-modal .modal-header{padding:18px 24px;border-bottom:1px solid var(--border-color,#e7eaf0)}
                    .qcmc-notices-modal .modal-title{font-size:15px;font-weight:600}
                    .qcmc-notices-modal .modal-body{padding:0}
                    .qcmc-notices-modal .form-section,.qcmc-notices-modal .form-column{padding:0!important}
                    .qcmc-notices-modal .frappe-control{margin:0!important}
                    .qcmc-notices-modal .modal-footer{padding:14px 24px;border-top:1px solid var(--border-color,#e7eaf0)}
                    .qcmc-notices-modal .modal-footer .btn-primary{border-radius:9px;padding:8px 24px}
                    .qcmc-notices{color:var(--text-color,#1e293b);background:var(--fg-color,#fff)}
                    .qcmc-notices *{box-sizing:border-box}
                    .qcmc-notices [hidden]{display:none!important}
                    .qcmc-notices .qcmc-hero{padding:26px 26px 24px;background:linear-gradient(120deg,#172e52,#304b76);color:#fff;display:flex;justify-content:space-between;gap:20px;align-items:center}
                    .qcmc-notices .qcmc-eyebrow{font-size:10px;font-weight:700;letter-spacing:1.8px;color:#b5c8e5;margin-bottom:9px}
                    .qcmc-notices .qcmc-hero h2{font-size:25px;letter-spacing:-.6px;margin:0 0 7px;color:#fff;font-weight:650}
                    .qcmc-notices .qcmc-hero p{font-size:12px;color:#d0dded;margin:0;line-height:1.6}
                    .qcmc-notices .qcmc-period{padding:10px 14px;border:1px solid #ffffff30;background:#ffffff0d;border-radius:12px;text-align:center;flex-shrink:0}
                    .qcmc-notices .qcmc-period strong{display:block;font-size:15px;color:#fff}
                    .qcmc-notices .qcmc-period span{font-size:12px;color:#d0dded}
                    .qcmc-notices .qcmc-tabs{display:flex;gap:6px;padding:14px 22px 0;border-bottom:1px solid var(--border-color,#e7eaf0);overflow-x:auto}
                    .qcmc-notices .qcmc-tab{display:flex;align-items:center;justify-content:center;gap:8px;flex:1;border:0;border-bottom:3px solid transparent;background:transparent;color:var(--text-muted,#667085);padding:12px 8px 14px;cursor:pointer;font-size:12px;font-weight:600;white-space:nowrap;transition:background .15s,color .15s}
                    .qcmc-notices .qcmc-tab svg{width:17px;height:17px;flex-shrink:0}
                    .qcmc-notices .qcmc-tab:hover{background:var(--control-bg,#f6f8fc);border-radius:8px 8px 0 0}
                    .qcmc-notices .qcmc-tab[aria-selected=true]{color:var(--primary,#3462b5);border-bottom-color:var(--primary,#3462b5)}
                    .qcmc-notices .qcmc-tab:focus-visible{outline:2px solid var(--primary,#3462b5);outline-offset:-3px}
                    .qcmc-notices .qcmc-count{background:var(--control-bg,#f0f3f9);border-radius:6px;padding:2px 7px;font-size:10px;line-height:1.5}
                    .qcmc-notices .qcmc-panel{padding:22px 26px 10px}
                    .qcmc-notices .qcmc-panel h3{font-size:15px;font-weight:650;margin:0 0 5px;color:var(--heading-color,#1e293b)}
                    .qcmc-notices .qcmc-panel-description{font-size:12px;color:var(--text-muted,#667085);margin:0 0 18px;line-height:1.6}
                    .qcmc-notices .qcmc-list{max-height: min(42vh,360px);min-height:200px;overflow-y:auto;overscroll-behavior:contain;padding-right:5px;scrollbar-width:thin}
                    .qcmc-notices .qcmc-person{display:flex;align-items:center;gap:12px;padding:14px 0;border-bottom:1px solid var(--border-color,#edf0f5)}
                    .qcmc-notices .qcmc-person:last-child{border-bottom:0}
                    .qcmc-notices .qcmc-avatar{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;flex-shrink:0;background:#eef2ff;color:#5365a7;font-size:12px;font-weight:700}
                    .qcmc-notices .qcmc-avatar-gold{background:#fff4de;color:#9f7623}
                    .qcmc-notices .qcmc-person-details{flex:1;min-width:0}
                    .qcmc-notices .qcmc-person-details strong{display:block;font-size:12px;font-weight:600;line-height:1.5;overflow-wrap:anywhere}
                    .qcmc-notices .qcmc-person-details>span{display:block;font-size:11px;color:var(--text-muted,#667085);margin-top:3px}
                    .qcmc-notices .qcmc-person-date{display:flex;align-items:flex-end;flex-direction:column;gap:5px;flex-shrink:0;font-size:11px;color:var(--text-muted,#667085)}
                    .qcmc-notices .qcmc-greet{border:1px solid var(--border-color,#dce3ed);background:var(--fg-color,#fff);color:var(--primary,#3462b5);font-size:10px;font-weight:600;padding:4px 8px;border-radius:6px;cursor:pointer}
                    .qcmc-notices .qcmc-greet:hover{background:var(--control-bg,#eef2ff)}
                    .qcmc-notices .qcmc-greet:disabled{opacity:.5;cursor:wait}
                    .qcmc-notices .qcmc-no-tweet{font-size:10px;opacity:.8}
                    .qcmc-notices .qcmc-service{background:#fff4de;color:#8b661e;padding:3px 8px;border-radius:6px;font-size:10px;font-weight:600}
                    .qcmc-notices .qcmc-empty{min-height:200px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:24px 16px;border:1px dashed var(--border-color,#dce3ed);border-radius:14px;background:var(--control-bg,#f8fafc)}
                    .qcmc-notices .qcmc-empty-icon{display:grid;place-items:center;width:48px;height:48px;border-radius:15px;background:var(--fg-color,#fff);color:#6f83ab;margin-bottom:14px;box-shadow:0 3px 12px #243c6410}
                    .qcmc-notices .qcmc-empty strong{font-size:13px;font-weight:600}
                    .qcmc-notices .qcmc-empty p{font-size:12px;color:var(--text-muted,#667085);margin:7px 0 0;line-height:1.6}
                    .qcmc-notices .qcmc-announcement-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;padding-bottom:12px}
                    .qcmc-notices .qcmc-announcement{border:1px solid var(--border-color,#e7eaf0);border-radius:12px;overflow:hidden;display:flex;flex-direction:column;background:var(--fg-color,#fff);min-width:0}
                    .qcmc-notices .qcmc-announcement-cover{height:120px;flex-shrink:0;display:grid;place-items:center;background:var(--control-bg,#edf2fa);color:#6f83ab;overflow:hidden}
                    .qcmc-notices .qcmc-announcement-cover img{width:100%;height:100%;object-fit:cover}
                    .qcmc-notices .qcmc-announcement-body{padding:14px;display:flex;flex-direction:column;flex:1;gap:10px;overflow-wrap:anywhere}
                    .qcmc-notices .qcmc-announcement h4{font-size:13px;font-weight:600;line-height:1.5;margin:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
                    .qcmc-notices .qcmc-announcement p{font-size:12px;line-height:1.6;color:var(--text-muted,#667085);margin:0;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
                    .qcmc-notices .qcmc-read-more{border:0;background:transparent;color:var(--primary,#3462b5);font-size:12px;font-weight:600;padding:6px 0;text-align:left;cursor:pointer;margin-top:auto}
                    .qcmc-notices .qcmc-read-more:hover{text-decoration:underline}
                    @media(max-width:767px){.qcmc-notices .qcmc-announcement-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
                    @media(max-width:576px){.qcmc-notices .qcmc-announcement-grid{grid-template-columns:minmax(0,1fr)}}
                    @media(max-width:576px){.qcmc-notices .qcmc-hero{padding:22px 18px;gap:12px}.qcmc-notices .qcmc-hero h2{font-size:21px}.qcmc-notices .qcmc-period{padding:8px 10px}.qcmc-notices .qcmc-tabs{padding:8px 10px 0;gap:0}.qcmc-notices .qcmc-tab{font-size:11px;gap:5px;padding:12px 6px}.qcmc-notices .qcmc-tab svg{display:none}.qcmc-notices .qcmc-panel{padding:20px 18px 8px}.qcmc-notices .qcmc-person{gap:9px}.qcmc-notices .qcmc-avatar{width:32px;height:32px;border-radius:10px}.qcmc-notices .qcmc-person-details strong{font-size:11px}}
                </style>
                <div class="qcmc-notices">
                    <header class="qcmc-hero"><div>
                        <div class="qcmc-eyebrow">${escape(__("OUR PEOPLE · OUR NEWS"))}</div>
                        <h2>${escape(__("News & celebrations"))}</h2>
                        <p>${escape(__("Stay connected. Celebrate the people who make it happen."))}</p>
                    </div><div class="qcmc-period"><strong>${escape(month)}</strong><span>${escape(data.year)}</span></div></header>
                    <nav class="qcmc-tabs" role="tablist" aria-label="${escape(__("Company updates"))}">
                        ${categories.map((item, index) => `<button type="button" class="qcmc-tab" data-notice-tab="${item.id}" id="qcmc-tab-${item.id}" role="tab" aria-controls="qcmc-panel-${item.id}" aria-selected="${index === 0}" tabindex="${index === 0 ? 0 : -1}">${icon(item.id)}<span>${escape(item.label)}</span><span class="qcmc-count">${item.count}</span></button>`).join("")}
                    </nav>
                    ${categories.map((item, index) => `<section class="qcmc-panel" id="qcmc-panel-${item.id}" role="tabpanel" aria-labelledby="qcmc-tab-${item.id}" ${index ? "hidden" : ""} tabindex="0"><h3>${escape(item.heading)}</h3><p class="qcmc-panel-description">${escape(item.description)}</p><div class="qcmc-list">${item.body}</div></section>`).join("")}
                </div>`);
            const root = dialog.fields_dict.content.$wrapper[0].querySelector(".qcmc-notices");
            const tabs = Array.from(root.querySelectorAll("[data-notice-tab]"));
            const panels = Array.from(root.querySelectorAll('[role="tabpanel"]'));
            const selectTab = (tab, focus = false) => {
                tabs.forEach(button => {
                    const selected = button === tab;
                    button.setAttribute("aria-selected", String(selected));
                    button.tabIndex = selected ? 0 : -1;
                });
                panels.forEach(panel => { panel.hidden = panel.id !== tab.getAttribute("aria-controls"); });
                if (focus) tab.focus();
            };
            tabs.forEach((tab, index) => {
                tab.addEventListener("click", () => selectTab(tab));
                tab.addEventListener("keydown", event => {
                    const next = {ArrowRight: (index + 1) % tabs.length, ArrowLeft: (index + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1}[event.key];
                    if (next !== undefined) {
                        event.preventDefault();
                        selectTab(tabs[next], true);
                    }
                });
            });
            root.querySelectorAll("[data-announcement-index]").forEach(button => {
                button.addEventListener("click", () => {
                    const row = data.announcements[Number(button.dataset.announcementIndex)];
                    if (!row) return;
                    const detail = new frappe.ui.Dialog({
                        title: escape(row.title || __("Announcement")),
                        size: "large",
                        fields: [{fieldname: "announcement_detail", fieldtype: "HTML"}],
                        primary_action_label: __("Back to announcements"),
                        primary_action: () => detail.hide(),
                        onhide: () => { dialog.show(); button.focus(); },
                    });
                    detail.$wrapper.addClass("qcmc-announcement-detail-modal");
                    // Full HTML comes from the server's sanitized announcement API.
                    detail.fields_dict.announcement_detail.$wrapper.html(`<style>
                        .qcmc-announcement-detail-modal .modal-content{border-radius:16px;overflow:hidden}
                        .qcmc-announcement-detail{max-height:65vh;overflow:auto;overflow-wrap:anywhere;line-height:1.7}
                        .qcmc-announcement-detail img{max-width:100%;height:auto}
                        .qcmc-announcement-detail>img{display:block;margin:0 auto 20px}
                        .qcmc-announcement-detail table{max-width:100%;display:block;overflow:auto}
                    </style><article class="qcmc-announcement-detail">${announcementImage(row)}<div>${row.announcement || ""}</div></article>`);
                    dialog.hide();
                    detail.show();
                });
            });
            root.querySelectorAll("[data-greet-kind]").forEach(button => {
                button.addEventListener("click", async () => {
                    const anniversary = button.dataset.greetKind === "anniversary";
                    const row = (anniversary ? data.anniversaries : data.birthdays)[Number(button.dataset.greetIndex)];
                    if (!row?.user_id || !data.can_greet) return;
                    const greeting = anniversary
                        ? __("Happy {0}-year work anniversary, {1}!\n\nThank you for being part of our team. Wishing you continued success!", [row.years, row.employee_name])
                        : __("Happy birthday, {0}!\n\nWishing you a wonderful day and a fantastic year ahead!", [row.employee_name]);
                    let sending = false;
                    let conversation = null;
                    const composer = new frappe.ui.Dialog({
                        title: __("Send message"),
                        fields: [
                            {fieldname: "recipient", fieldtype: "Data", label: __("To"), default: row.employee_name, read_only: 1},
                            {fieldname: "message", fieldtype: "Small Text", label: __("Message"), reqd: 1, default: greeting, description: __("Send a private greeting through Tweet.")},
                        ],
                        primary_action_label: __("Send"),
                        secondary_action_label: __("Cancel"),
                        secondary_action: () => composer.hide(),
                        onhide: () => dialog.show(),
                        primary_action: async values => {
                            if (sending) return;
                            const content = String(values?.message || "").trim();
                            if (!content) {
                                frappe.msgprint(__("Write a message before sending."));
                                return;
                            }
                            if (content.length > 10000) {
                                frappe.msgprint(__("Message must be 10,000 characters or fewer."));
                                return;
                            }
                            sending = true;
                            composer.get_primary_btn().prop("disabled", true).text(__("Sending…"));
                            try {
                                if (!conversation) {
                                    const result = await frappe.call({
                                        method: "company_messenger.api.create_conversation",
                                        args: {users: [row.user_id]},
                                        silent: true,
                                    });
                                    conversation = result.message;
                                    if (!conversation) throw new Error("Tweet conversation was not returned");
                                }
                                const result = await frappe.call({
                                    method: "company_messenger.api.send_message",
                                    args: {conversation, content},
                                    silent: true,
                                });
                                if (!result.message?.name) throw new Error("Tweet did not confirm the message");
                                composer.hide();
                                frappe.show_alert({message: escape(__("Greeting sent to {0}.", [row.employee_name])), indicator: "green"});
                            } catch (error) {
                                console.warn("Could not send Tweet greeting", error);
                                frappe.msgprint(__("Could not send the message. Your text is still here; please try again."));
                            } finally {
                                sending = false;
                                composer.get_primary_btn().prop("disabled", false).text(__("Send"));
                            }
                        },
                    });
                    composer.$wrapper.addClass("qcmc-greeting-modal");
                    dialog.hide();
                    composer.show();
                });
            });
            noticeDialog = dialog;
            const showOnce = () => {
                // Another tab may have shown the popup during the API request.
                try {
                    if (!manual && window.localStorage.getItem(storageKey) === session) return;
                } catch (error) {
                    // Continue when browser storage is unavailable.
                }
                dialog.show();
                try {
                    window.localStorage.setItem(storageKey, session);
                } catch (error) {
                    // The popup still works when the browser disables storage.
                }
            };
            if (!manual && typeof navigator !== "undefined" && navigator.locks) {
                await navigator.locks.request(storageKey, showOnce);
            } else {
                showOnce();
            }
        } catch (error) {
            console.warn("Could not load company notices", error);
            started = false;
        } finally {
            opening = false;
        }
    }

    function addReopenButton() {
        if (!frappe.session || frappe.session.user === "Guest" || document.getElementById("qcmc-open-notices")) return;
        const navbar = document.querySelector(".navbar-right, .navbar .navbar-nav.ml-auto, .navbar .navbar-nav:last-child");
        const button = document.createElement("button");
        button.id = "qcmc-open-notices";
        button.type = "button";
        button.className = "btn btn-default btn-sm";
        button.textContent = __("News & Celebrations");
        button.title = __("Reopen announcements, anniversaries and birthdays");
        button.setAttribute("aria-haspopup", "dialog");
        button.style.cssText = "font-size:11px;border-radius:8px;white-space:nowrap;margin-right:8px";
        button.addEventListener("click", () => openNotices(true));
        if (navbar) {
            const item = document.createElement("li");
            item.className = "nav-item";
            item.appendChild(button);
            navbar.prepend(item);
        } else {
            // Some Desk layouts omit the standard toolbar, especially on mobile.
            button.style.cssText += ";position:fixed;bottom:20px;left:20px;z-index:1030;box-shadow:0 3px 14px #11182722";
            document.body.appendChild(button);
        }
    }

    frappe.qcmc_login_notices = {open: () => openNotices(true)};
    $(document).on("app_ready", async () => {
        addReopenButton();
        await openNotices();
    });
})();
