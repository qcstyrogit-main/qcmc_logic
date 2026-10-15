/* Announcement discussions reuse Frappe Comment storage and mention controls. */
(() => {
    const api = "qcmc_logic.api.announcement_comments.";
    const eventName = "qcmc_announcement_comments_changed";
    const listeners = new Set();
    let realtimeBound = false;
    let styled = false;

    function subscribe(callback) {
        listeners.add(callback);
        if (!realtimeBound && frappe.realtime?.on) {
            const dispatch = message => listeners.forEach(listener => listener(message));
            frappe.realtime.on(eventName, dispatch);
            frappe.realtime.on("connect", () => dispatch({reconnected: true}));
            globalThis.window?.addEventListener?.("focus", () => dispatch({reconnected: true}));
            realtimeBound = true;
        }
        return () => listeners.delete(callback);
    }

    function attach({parent, composerParent, announcement, targetComment, onCount}) {
        if (!parent) return {refresh: async () => {}, destroy() {}};
        if (!styled) {
            const style = document.createElement("style");
            style.textContent = `
                .qcmc-announcement-comments{border-top:1px solid var(--border-color,#e7eaf0);margin-top:22px;padding-top:16px;font-size:13px}
                .qcmc-comment-header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px;flex-wrap:wrap}
                .qcmc-comment-header h4{font-size:13px;margin:0;font-weight:600;color:var(--text-muted)}
                .qcmc-comment-sort{border:0;background:none;padding:0;font-size:12px;font-weight:600;color:var(--text-muted);cursor:pointer}
                .qcmc-comment{display:flex;gap:9px;padding:0 0 14px;overflow-wrap:anywhere}
                .qcmc-comment-avatar{position:relative;width:34px;height:34px;flex:0 0 34px;border-radius:50%;display:grid;place-items:center;background:#e8edf7;color:#52628a;font-size:12px;font-weight:600;overflow:hidden}
                .qcmc-comment-avatar img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
                .qcmc-comment-main{min-width:0;flex:1}
                .qcmc-comment-bubble-row{display:flex;gap:5px;align-items:flex-start}
                .qcmc-comment-bubble{background:var(--control-bg,#f0f2f5);border-radius:16px;padding:8px 12px;max-width:100%;min-width:0}
                .qcmc-comment-author{font-size:12px;font-weight:650;line-height:1.4;display:block;margin-bottom:2px;color:var(--heading-color)}
                .qcmc-comment-meta{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;margin:3px 0 0 12px;line-height:1.5}
                .qcmc-comment-meta time,.qcmc-comment-meta small{font-size:11px;color:var(--text-muted,#667085)}
                .qcmc-comment-body{line-height:1.65}
                .qcmc-comment-body p{margin:0}
                .qcmc-comment-body img{max-width:100%;height:auto}
                .qcmc-comment-highlight .qcmc-comment-bubble{animation:qcmc-mention-focus 3.5s ease-out}
                @keyframes qcmc-mention-focus{0%,35%{background:var(--blue-100,#dbeafe);box-shadow:0 0 0 2px var(--blue-400,#60a5fa)}100%{background:var(--control-bg,#f0f2f5);box-shadow:0 0 0 0 transparent}}
                @media(prefers-reduced-motion:reduce){.qcmc-comment-highlight .qcmc-comment-bubble{animation:none;background:var(--blue-100,#dbeafe)}}
                :is(.qcmc-comment-body,.qcmc-inline-editor,.qcmc-comment-composer) .mention{background:var(--blue-100,#dbeafe)!important;color:var(--blue-600,#1674df)!important;border:0!important;border-radius:4px;padding:2px 5px;font-weight:500;text-decoration:none!important}
                :is(.qcmc-comment-body,.qcmc-inline-editor,.qcmc-comment-composer) .mention :is(a,span){color:inherit!important;background:transparent!important;text-decoration:none!important;border:0!important;box-shadow:none!important}
                :is(.qcmc-comment-body,.qcmc-inline-editor,.qcmc-comment-composer) .mention>span{margin:0}
                :is(.qcmc-comment-body,.qcmc-inline-editor,.qcmc-comment-composer) .ql-mention-denotation-char{display:none}
                .qcmc-comment-body .mention[data-id]:not([data-is-group="true"]){cursor:pointer}
                .qcmc-comment-meta button{background:none;border:0;padding:0;font-size:11px;font-weight:600;color:var(--text-muted,#667085);cursor:pointer}
                .qcmc-comment-meta button:hover{text-decoration:underline}
                .qcmc-comment-menu{position:relative;flex-shrink:0;margin-top:4px}
                .qcmc-comment-menu summary{list-style:none;width:26px;height:26px;display:grid;place-items:center;border-radius:50%;cursor:pointer;color:var(--text-muted)}
                .qcmc-comment-menu summary::-webkit-details-marker{display:none}
                .qcmc-comment-menu summary:hover{background:var(--control-bg,#f0f2f5)}
                .qcmc-comment-menu>div{position:absolute;inset-inline-end:0;top:28px;min-width:110px;padding:5px;background:var(--card-bg,#fff);border:1px solid var(--border-color);border-radius:9px;box-shadow:0 5px 18px #0002;z-index:5}
                .qcmc-comment-menu button{display:block;width:100%;text-align:start;border:0;background:none;padding:6px 9px;font-size:12px;border-radius:5px;color:var(--text-color);cursor:pointer}
                .qcmc-comment-menu button:hover{background:var(--control-bg)}
                .qcmc-comment-context,.qcmc-comment-empty{font-size:12px;color:var(--text-muted,#667085)}
                .qcmc-comment-context{margin:0 0 5px 10px}
                .qcmc-comment-empty{padding:10px 0 18px}
                .qcmc-comment-composer .ql-editor{min-height:130px}
                .qcmc-comment-composer .modal-content{border-radius:14px}
                .qcmc-inline-composer{display:flex;gap:9px;padding:14px 0 0;border-top:1px solid var(--border-color,#e7eaf0);background:var(--card-bg,#fff);font-size:12px}
                .qcmc-inline-frame{min-width:0;flex:1;border-radius:18px;background:var(--control-bg,#f0f2f5);padding:9px 12px}
                .qcmc-inline-context{display:flex;gap:8px;justify-content:space-between;color:var(--text-muted);padding-bottom:7px;font-size:11px}
                .qcmc-inline-context[hidden],.qcmc-inline-emojis[hidden]{display:none!important}
                .qcmc-inline-context button{background:none;border:0;color:var(--primary);padding:0;cursor:pointer}
                .qcmc-inline-editor .frappe-control{margin:0!important;padding:0!important}
                .qcmc-inline-editor .ql-container{border:0;background:transparent;font-family:inherit;font-size:13px}
                .qcmc-inline-editor .ql-editor{min-height:38px;max-height:100px;overflow-y:auto;padding:0;border:0;background:transparent}
                .qcmc-inline-editor .ql-editor.ql-blank::before{inset-inline-start:0;inset-inline-end:0;font-style:normal;font-size:13px;color:var(--text-muted)}
                .qcmc-inline-tools{display:flex;gap:8px;align-items:center;justify-content:space-between;margin-top:5px}
                .qcmc-inline-tools>div{display:flex;align-items:center;gap:7px;min-width:0}
                .qcmc-inline-hint{font-size:10px;color:var(--text-muted)}
                .qcmc-inline-tools button,.qcmc-inline-emojis button{border:0;background:none;padding:3px;border-radius:50%;display:grid;place-items:center;color:var(--text-muted);cursor:pointer}
                .qcmc-inline-tools button:hover{background:var(--fg-color,#fff);color:var(--primary)}
                .qcmc-inline-tools button:disabled{opacity:.35;cursor:default}
                .qcmc-inline-tools button[data-editing="true"]{border-radius:7px;padding:4px 10px;background:var(--primary);color:var(--neutral,#fff);font-size:12px;font-weight:600}
                .qcmc-inline-tools svg{width:18px;height:18px}
                .qcmc-inline-emojis{display:flex;gap:8px;padding-top:8px;flex-wrap:wrap}
                .qcmc-inline-emojis button{font-size:20px}
                .qcmc-profile-modal .modal-dialog{display:flex;align-items:center;min-height:calc(100% - 3.5rem);margin:1.75rem auto;padding:0 12px;max-width:420px}
                .qcmc-profile-modal .modal-content{width:100%;border-radius:18px;box-shadow:0 18px 60px #0003;overflow:hidden}
                .qcmc-profile-modal .modal-header{border-bottom:0;padding-bottom:0}
                .qcmc-profile-modal .modal-body{padding:8px 24px 24px}
                .qcmc-profile-card{text-align:center;color:var(--text-color);font-size:13px}
                .qcmc-profile-card>.qcmc-comment-avatar{width:64px;height:64px;margin:0 auto 12px;font-size:22px;background:var(--blue-100,#dbeafe);color:var(--blue-600,#1674df)}
                .qcmc-profile-name{font-size:18px;font-weight:650;margin:4px 0 20px;overflow-wrap:anywhere}
                .qcmc-profile-label{font-size:11px;font-weight:500;color:var(--text-muted);margin-bottom:5px;display:block}
                .qcmc-profile-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:12px}
                .qcmc-profile-facts>div{padding:13px 8px;background:var(--control-bg,#f0f2f5);border-radius:10px;overflow-wrap:anywhere}
                .qcmc-profile-email{border-top:1px solid var(--border-color);padding-top:15px}
                .qcmc-profile-email-value{display:flex;gap:8px;justify-content:center;align-items:center}
                .qcmc-profile-email-value>span{min-width:0;overflow-wrap:anywhere}
                .qcmc-profile-copy{border:0;background:var(--control-bg,#f0f2f5);border-radius:7px;padding:6px;display:grid;place-items:center;color:var(--text-muted);cursor:pointer;flex-shrink:0}
                .qcmc-profile-copy:hover{color:var(--primary);background:var(--blue-100,#dbeafe)}
                .qcmc-profile-copy svg{width:15px;height:15px}
                @media(max-width:576px){.qcmc-comment{margin-inline-start:min(20px,var(--reply-indent))!important}.qcmc-inline-hint{display:none}}
            `;
            document.head.appendChild(style); styled = true;
        }
        const host = document.createElement("section");
        host.className = "qcmc-announcement-comments";
        host.setAttribute("aria-label", __("Announcement comments"));
        parent.appendChild(host);
        const escape = value => frappe.utils.escape_html(String(value ?? ""));
        let rows = [], alive = true, sequence = 0, deleting = false, updateTimer = null, newestFirst = true;
        let pendingFocus = targetComment || null, stopBannerFocus = null;
        const request = (method, args, mutate = false) => frappe.call({method: api + method, args, ...(mutate ? {type: "POST"} : {silent: true})});
        const avatar = (name, image) => {
            const words = String(name || "?").trim().split(/\s+/);
            const initials = ((words[0]?.[0] || "?") + (words.length > 1 ? words.at(-1)[0] : "")).toUpperCase();
            const validImage = /^(https?:\/\/|\/(?![\/\\]))/i.test(image || "");
            return `<span class="qcmc-comment-avatar" aria-hidden="true"><span>${escape(initials)}</span>${validImage ? `<img src="${escape(image)}" alt="" loading="lazy">` : ""}</span>`;
        };

        function render(error = false) {
            const byId = new Map(rows.map(row => [row.name, row]));
            const children = new Map(), ordered = [], visited = new Set();
            rows.forEach(row => {
                const parentId = byId.has(row.parent) ? row.parent : null;
                if (!children.has(parentId)) children.set(parentId, []);
                children.get(parentId).push(row);
            });
            function walk(row, depth) {
                if (visited.has(row.name)) return;
                visited.add(row.name); ordered.push({row, depth: Math.min(depth, 3)});
                (children.get(row.name) || []).forEach(child => walk(child, depth + 1));
            }
            const roots = [...(children.get(null) || [])];
            if (newestFirst) roots.reverse();
            roots.forEach(row => walk(row, 0));
            rows.forEach(row => walk(row, 0)); // Defensive against malformed historical cycles.
            host.innerHTML = `<header class="qcmc-comment-header"><h4>${escape(__("Comments"))} <span class="text-muted">(${rows.length})</span></h4>
                <button type="button" class="qcmc-comment-sort" data-action="sort">${escape(__(newestFirst ? "Newest first" : "Oldest first"))} <span aria-hidden="true">⌄</span></button></header>
                <div class="qcmc-comment-list" aria-live="polite">${error ? `<p class="qcmc-comment-empty">${escape(__("Could not load comments."))} <button type="button" class="btn btn-default btn-xs" data-action="retry">${escape(__("Retry"))}</button></p>` : ordered.length ? ordered.map(({row, depth}) => {
                    const index = rows.indexOf(row);
                    const date = frappe.datetime?.prettyDate?.(row.creation, true) || frappe.datetime?.str_to_user?.(row.creation) || row.creation || "";
                    const parentRow = byId.get(row.parent);
                    return `<article class="qcmc-comment" data-comment-index="${index}" style="--reply-indent:${depth * 34}px;margin-inline-start:${depth * 34}px">
                        ${avatar(row.author_name, row.author_image)}<div class="qcmc-comment-main">
                        ${row.parent ? `<div class="qcmc-comment-context">${escape(parentRow ? __("Reply to {0}", [parentRow.author_name]) : __("Reply to a deleted comment"))}</div>` : ""}
                        <div class="qcmc-comment-bubble-row"><div class="qcmc-comment-bubble"><strong class="qcmc-comment-author">${escape(row.author_name)}</strong><div class="qcmc-comment-body">${row.content || ""}</div></div>
                        ${row.can_manage ? `<details class="qcmc-comment-menu"><summary aria-label="${escape(__("Comment actions"))}">···</summary><div><button type="button" data-action="edit" data-index="${index}">${escape(__("Edit"))}</button><button type="button" data-action="delete" data-index="${index}">${escape(__("Delete"))}</button></div></details>` : ""}</div>
                        <div class="qcmc-comment-meta"><time>${escape(date)}</time><button type="button" data-action="reply" data-index="${index}">${escape(__("Reply"))}</button>${row.modified !== row.creation ? `<small>${escape(__("Edited"))}</small>` : ""}</div>
                    </div></article>`;
                }).join("") : `<p class="qcmc-comment-empty">${escape(__("No comments yet. Start the conversation."))}</p>`}</div>`;
        }

        function focusComment(name, focus = true) {
            const index = rows.findIndex(row => row.name === name);
            if (index < 0 || !alive) return false;
            const node = host.querySelector(`[data-comment-index="${index}"]`);
            if (!node) return false;
            node.classList.remove('qcmc-comment-highlight');
            void node.offsetWidth;
            node.classList.add('qcmc-comment-highlight');
            node.setAttribute('tabindex', '-1');
            if (focus) node.focus({preventScroll: true});
            const reduced = globalThis.window?.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
            node.scrollIntoView({behavior: reduced ? 'auto' : 'smooth', block: 'center'});
            return true;
        }

        async function refresh() {
            if (!alive) return;
            if (updateTimer !== null) {clearTimeout(updateTimer); updateTimer = null;}
            const current = ++sequence;
            try {
                const response = await request("get_comments", {name: announcement});
                if (!alive || current !== sequence) return;
                rows = response.message.comments || [];
                onCount?.(Number(response.message.count) || 0);
                render();
                if (pendingFocus && focusComment(pendingFocus)) {
                    const name = pendingFocus; pendingFocus = null;
                    // A large announcement image may load after the comments.
                    const banner = parent.querySelector(':scope > img');
                    if (banner && !banner.complete) {
                        const onLoad = () => focusComment(name, false);
                        banner.addEventListener('load', onLoad, {once: true});
                        stopBannerFocus = () => banner.removeEventListener('load', onLoad);
                    }
                }
            } catch (error) {
                if (!alive || current !== sequence) return;
                console.warn("Could not load announcement comments", error);
                render(true);
            }
        }

        const inline = document.createElement("div");
        inline.className = "qcmc-inline-composer";
        const user = frappe.user_info?.(frappe.session.user) || {};
        inline.innerHTML = `${avatar(user.fullname || frappe.session.user, user.image)}<div class="qcmc-inline-frame">
            <div class="qcmc-inline-context" hidden><span></span><button type="button" data-action="cancel-reply">${escape(__("Cancel"))}</button></div>
            <div class="qcmc-inline-editor"></div><div class="qcmc-inline-tools"><div>
            <button type="button" data-action="emoji" aria-label="${escape(__("Choose emoji"))}" aria-expanded="false">☺</button>
            <span class="qcmc-inline-hint">${escape(__("@ mention · Ctrl+Enter to post"))}</span></div>
            <button type="button" data-action="post" aria-label="${escape(__("Post comment"))}" disabled><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M3 3.5a1 1 0 0 1 1.4-.9l16 8.5a1 1 0 0 1 0 1.8l-16 8.5A1 1 0 0 1 3 20.5L5 13l9-1-9-1z"/></svg></button></div>
            <div class="qcmc-inline-emojis" hidden>${["😊", "🎉", "❤️", "👏", "🎂", "👍"].map(emoji => `<button type="button" data-action="insert-emoji" data-emoji="${emoji}" aria-label="${emoji}">${emoji}</button>`).join("")}</div></div>`;
        (composerParent || parent).appendChild(inline);
        const replyContext = inline.querySelector(".qcmc-inline-context");
        const sendButton = inline.querySelector('[data-action="post"]');
        const emojiPalette = inline.querySelector(".qcmc-inline-emojis");
        let replyTarget = null, posting = false, autoMention = null, editing = null, savedDraft = null;
        const sendIcon = sendButton.innerHTML;
        const hint = inline.querySelector('.qcmc-inline-hint');
        function updateContext() {
            replyContext.hidden = !editing && !replyTarget;
            replyContext.querySelector('span').textContent = editing ? __('Editing comment') : replyTarget ? __('Replying to {0}', [replyTarget.author_name]) : '';
            sendButton.setAttribute('aria-label', __(editing ? 'Save changes' : 'Post comment'));
            sendButton.setAttribute('data-editing', String(!!editing));
            if (editing) sendButton.textContent = __('Save');
            else sendButton.innerHTML = sendIcon;
            hint.textContent = __(editing ? '@ mention · Ctrl+Enter to save' : '@ mention · Ctrl+Enter to post');
        }
        function finishEdit() {
            const draft = savedDraft;
            editing = null; savedDraft = null;
            if (draft) {
                control.set_formatted_input(draft.content);
                replyTarget = draft.replyTarget; autoMention = draft.autoMention;
            }
            updateContext(); updateSend();
        }
        const hasText = value => !!frappe.utils.html2text(value || "").trim();
        const control = frappe.ui.form.make_control({
            parent: inline.querySelector(".qcmc-inline-editor"),
            df: {fieldtype: "Comment", fieldname: "announcement_comment", label: __("Comment"), enable_mentions: 1},
            enable_mentions: true, render_input: true, only_input: true, no_wrapper: true,
            on_submit: value => post(value),
        });
        control.quill.root.setAttribute("data-placeholder", __("Comment as {0}", [user.fullname || frappe.session.user]));
        control.quill.root.setAttribute("aria-label", __("Comment"));
        const updateSend = () => {sendButton.disabled = posting || !hasText(control.get_value());};
        control.quill.on("text-change", updateSend);
        function setReply(row) {
            // Replace only the automatic leading mention. Keep the user's draft
            // and any manually added mentions when switching or cancelling replies.
            const quill = control.quill;
            const first = quill.getContents().ops[0]?.insert?.mention;
            if (autoMention && first?.id === autoMention && first.denotationChar === "") {
                quill.deleteText(0, 1, "api");
                if (quill.getText?.(0, 1) === " ") quill.deleteText(0, 1, "api");
            }
            autoMention = null;
            replyTarget = row || null;
            updateContext();
            if (row?.author) {
                // Native mention embeds retain the user ID used by notifications.
                // MentionBlot renders value as HTML, so escape the display name.
                quill.insertEmbed(0, "mention", {id: row.author, value: escape(row.author_name), denotationChar: "", isGroup: "false"}, "api");
                quill.insertText(1, " ", "api");
                autoMention = row.author;
                quill.setSelection(2, 0, "api");
            }
        }
        async function post(value = control.get_value()) {
            if (!alive || posting || !hasText(value)) return;
            posting = true; control.disable(); updateSend();
            try {
                const response = await request(editing ? "update_comment" : "add_comment", editing
                    ? {comment: editing.name, content: value}
                    : {name: announcement, content: value, parent: replyTarget?.name || null}, true);
                if (!alive) return;
                if (editing) finishEdit();
                else {control.clear(); setReply(null);}
                onCount?.(Number(response.message.count) || 0);
                await refresh();
            } catch (error) {console.warn("Could not post announcement comment", error);}
            finally {posting = false; if (alive) {control.enable(); updateSend();}}
        }
        inline.addEventListener("click", event => {
            const button = event.target.closest("[data-action]");
            if (!button || !alive || posting) return;
            const action = button.dataset.action;
            if (action === "post") return post();
            if (action === "cancel-reply") {
                if (editing) finishEdit(); else setReply(null);
                control.set_focus();
            }
            if (action === "emoji") {
                emojiPalette.hidden = !emojiPalette.hidden;
                button.setAttribute("aria-expanded", String(!emojiPalette.hidden));
            }
            if (action === "insert-emoji") {
                const index = control.quill.getSelection()?.index ?? Math.max(0, control.quill.getLength() - 1);
                control.quill.insertText(index, button.dataset.emoji, "user");
                emojiPalette.hidden = true;
                inline.querySelector('[data-action="emoji"]').setAttribute("aria-expanded", "false");
                control.set_focus();
            }
        });
        const hideBrokenAvatar = event => {
            if (event.target?.tagName === "IMG" && event.target.parentElement?.classList.contains("qcmc-comment-avatar")) event.target.hidden = true;
        };
        host.addEventListener("error", hideBrokenAvatar, true);
        inline.addEventListener("error", hideBrokenAvatar, true);

        function editComment(row) {
            if (posting) return;
            if (!editing) savedDraft = {content: control.get_value(), replyTarget, autoMention};
            editing = {name: row.name};
            replyTarget = null; autoMention = null;
            control.set_formatted_input(row.content);
            updateContext(); updateSend(); control.set_focus();
        }

        // Native details elements do not dismiss themselves on outside clicks.
        function closeMenus(except = null) {
            host.querySelectorAll(".qcmc-comment-menu[open]").forEach(menu => {
                if (menu !== except) menu.open = false;
            });
        }
        const dismissMenus = event => closeMenus(event.target.closest?.(".qcmc-comment-menu"));
        const dismissMenusOnEscape = event => {if (event.key === "Escape") closeMenus();};
        document.addEventListener("click", dismissMenus, true);
        document.addEventListener("keydown", dismissMenusOnEscape, true);
        let profileLoading = false;
        async function showProfile(mention) {
            if (profileLoading || !alive) return;
            profileLoading = true;
            closeMenus();
            try {
                const response = await request("get_mention_profile", {name: announcement, user: mention.dataset.id});
                if (!alive) return;
                const profile = response.message;
                const copyEmail = event => {
                    if (!event.target.closest("[data-copy-email]")) return;
                    event.preventDefault();
                    frappe.utils.copy_to_clipboard(profile.email, __("Email copied"));
                };
                const popup = new frappe.ui.Dialog({title: __("Profile"), size: "small",
                    fields: [{fieldtype: "HTML", fieldname: "profile", options:
                        `<div class="qcmc-profile-card">${avatar(profile.name)}<span class="qcmc-profile-label">${escape(__("Name"))}</span><div class="qcmc-profile-name">${escape(profile.name || "—")}</div>
                        <div class="qcmc-profile-facts">${[["Department", profile.department], ["Position", profile.position]].map(([label, value]) => `<div><span class="qcmc-profile-label">${escape(__(label))}</span>${escape(value || "—")}</div>`).join("")}</div>
                        <div class="qcmc-profile-email"><span class="qcmc-profile-label">${escape(__("Email"))}</span><div class="qcmc-profile-email-value"><span>${escape(profile.email || "—")}</span>${profile.email ? `<button type="button" class="qcmc-profile-copy" data-copy-email aria-label="${escape(__("Copy email"))}" title="${escape(__("Copy email"))}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg></button>` : ""}</div></div></div>`}],
                    onhide: () => popup.$wrapper[0].removeEventListener("click", copyEmail),
                });
                popup.$wrapper.addClass("qcmc-profile-modal");
                popup.$wrapper[0].addEventListener("click", copyEmail);
                popup.show();
            } catch (error) {console.warn("Could not load mentioned profile", error);}
            finally {profileLoading = false;}
        }
        host.addEventListener("click", event => {
            const mention = event.target.closest('.mention[data-id]:not([data-is-group="true"])');
            if (mention?.dataset.id) {
                event.preventDefault(); event.stopPropagation();
                return showProfile(mention);
            }
            const button = event.target.closest("[data-action]");
            if (!button || !alive) return;
            closeMenus();
            const action = button.dataset.action;
            if (action === "retry") return refresh();
            if (action === "sort") {newestFirst = !newestFirst; return render();}
            const row = rows[Number(button.dataset.index)];
            if (!row) return;
            if (action === "reply" && !posting) {
                if (editing) finishEdit();
                setReply(row); return control.set_focus();
            }
            if (action === "edit" && row.can_manage) return editComment(row);
            if (action === "delete" && row.can_manage && !deleting) {
                deleting = true;
                return frappe.confirm(__("Delete this comment? Replies will remain."), async () => {
                    try {
                        const response = await request("delete_comment", {comment: row.name}, true);
                        if (alive) onCount?.(Number(response.message.count) || 0);
                        await refresh();
                    } catch (error) {console.warn("Could not delete announcement comment", error);}
                    finally {deleting = false;}
                }, () => {deleting = false;});
            }
        });
        host.innerHTML = `<p class="qcmc-comment-empty">${escape(__("Loading comments…"))}</p>`;
        const unsubscribe = subscribe(message => {
            if (!alive || (!message?.reconnected && message?.announcement !== announcement) || updateTimer !== null) return;
            updateTimer = setTimeout(() => {updateTimer = null; refresh();}, 120);
        });
        refresh();
        return {refresh, destroy() {
            alive = false; sequence++; unsubscribe();
            stopBannerFocus?.();
            document.removeEventListener("click", dismissMenus, true);
            document.removeEventListener("keydown", dismissMenusOnEscape, true);
            if (updateTimer !== null) clearTimeout(updateTimer);
        }};
    }

    frappe.qcmc_announcement_comments = {attach, subscribe};
})();
