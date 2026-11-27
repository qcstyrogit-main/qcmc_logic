/* Global draft cancellation. Server permissions and settings are authoritative. */
(function () {
    const AVAILABILITY = "qcmc_logic.customs.transaction_cancellation.get_draft_cancel_availability";
    const MARKER = "data-qcmc-draft-cancel";

    function key(frm) {
        return [frm.doctype, frm.doc.name, frm.doc.modified].join("|");
    }

    function saved_draft(frm) {
        return Boolean(frm?.doc && !frm.is_new() && Number(frm.doc.docstatus) === 0
            && (frm.meta?.is_submittable || frappe.model.is_submittable(frm.doctype)));
    }

    function prompt_reason(frm, submit) {
        if (!saved_draft(frm) || frm.is_dirty()) {
            frappe.msgprint(__("Reload or save the document before cancelling. Unsaved changes cannot be cancelled."));
            return;
        }
        const documentKey = key(frm);
        const dialog = new frappe.ui.Dialog({
            title: __("Cancel Transaction"),
            fields: [
                {fieldtype: "HTML", options: "<p>" + frappe.utils.escape_html(__("This saved draft will be cancelled without submitting it. No inventory or accounting entries will be posted by submission.")) + "</p>"},
                {fieldname: "reason", label: __("Cancellation Reason"), fieldtype: "Small Text", reqd: 1}
            ],
            primary_action_label: __("Confirm Cancellation"),
            async primary_action(values) {
                const reason = String(values.reason || "").trim();
                if (!reason || reason.length > 2000) {
                    frappe.msgprint(__("Enter a cancellation reason (1 to 2000 characters)."));
                    return;
                }
                if (!saved_draft(frm) || frm.is_dirty() || key(frm) !== documentKey
                    || (window.cur_frm && window.cur_frm !== frm)) {
                    dialog.hide();
                    frappe.msgprint(__("Reload the document before cancelling."));
                    return;
                }
                dialog.disable_primary_action();
                try {
                    await submit(reason);
                    dialog.hide();
                    await frm.reload_doc();
                    frappe.show_alert({message: __("Cancelled"), indicator: "red"});
                } finally {
                    dialog.enable_primary_action();
                }
            }
        });
        dialog.show();
    }

    function render_action(frm) {
        const menu = frm.page?.actions;
        if (!menu?.length || (window.cur_frm && window.cur_frm !== frm)) return;
        const own = menu.find("a[" + MARKER + "]");
        const eligible = saved_draft(frm) && !frm.is_dirty()
            && frm.__qcmc_cancel_available === key(frm);
        if (!eligible) {
            own.closest("li").remove();
            return;
        }
        if (own.length) return;
        // Do not replace a separately registered workflow or native action.
        const existing = menu.find("li > a.dropdown-item .menu-item-label").filter(function () {
            return jQuery(this).text().trim() === __("Cancel");
        });
        if (existing.length) return;
        const link = frm.page.add_action_item(__("Cancel"), () => prompt_reason(frm, reason =>
            frappe.xcall("frappe.desk.form.save.discard", {
                doctype: frm.doctype, name: frm.doc.name,
                modified: frm.doc.modified, reason
            })), true);
        link?.attr(MARKER, "1");
    }

    function watch_menu(frm) {
        const node = frm.page?.actions?.[0];
        if (!node || frm.__qcmc_cancel_menu_node === node) return;
        frm.__qcmc_cancel_menu_observer?.disconnect();
        const observer = new MutationObserver(() => render_action(frm));
        observer.observe(node, {childList: true, subtree: true});
        frm.__qcmc_cancel_menu_observer = observer;
        frm.__qcmc_cancel_menu_node = node;
        jQuery(frm.wrapper).off("dirty.qcmc_draft_cancel").on("dirty.qcmc_draft_cancel", () => render_action(frm));
    }

    async function refresh_action(frm) {
        if (!frm?.doc || (window.cur_frm && window.cur_frm !== frm)) return;
        watch_menu(frm);
        const token = (frm.__qcmc_cancel_request || 0) + 1;
        frm.__qcmc_cancel_request = token;
        frm.__qcmc_cancel_available = null;
        render_action(frm);
        if (!saved_draft(frm) || frm.is_dirty()) return;
        // Workflow forms already obtain eligibility from get_transitions.
        if (frappe.model.has_workflow(frm.doctype)) return;
        const documentKey = key(frm);
        try {
            const result = await frappe.xcall(AVAILABILITY, {doctype: frm.doctype, name: frm.doc.name});
            if (token !== frm.__qcmc_cancel_request || !saved_draft(frm)
                || documentKey !== key(frm) || (window.cur_frm && window.cur_frm !== frm)) return;
            frm.__qcmc_cancel_available = result?.available ? documentKey : null;
            render_action(frm);
        } catch (error) {
            console.warn("Draft cancellation eligibility check failed", error);
        }
    }

    function install() {
        const Toolbar = frappe.ui?.form?.Toolbar;
        const States = frappe.ui?.form?.States;
        if (!Toolbar || !States) return false;
        if (Toolbar.prototype.__qcmc_draft_cancel_actions_installed) return true;
        Toolbar.prototype.__qcmc_draft_cancel_actions_installed = true;
        // Replace the native three-dot Discard entry with the common Actions menu.
        Toolbar.prototype.add_discard = function () {};
        const originalRefresh = Toolbar.prototype.refresh;
        Toolbar.prototype.refresh = function () {
            const result = originalRefresh.apply(this, arguments);
            const frm = this.frm;
            setTimeout(() => refresh_action(frm), 0);
            return result;
        };
        const originalWorkflowAction = States.prototype.handle_workflow_action;
        States.prototype.handle_workflow_action = function (transition) {
            if (!transition._qcmc_draft_cancel) return originalWorkflowAction.apply(this, arguments);
            const frm = this.frm;
            return prompt_reason(frm, reason => frappe.xcall("frappe.model.workflow.apply_workflow", {
                doc: {doctype: frm.doctype, name: frm.doc.name, modified: frm.doc.modified,
                    docstatus: frm.doc.docstatus, _qcmc_draft_cancel_reason: reason},
                action: transition.action
            }));
        };
        if (window.cur_frm) refresh_action(window.cur_frm);
        return true;
    }

    // Form classes may be lazy-loaded long after the Desk boots.
    if (!install()) {
        const timer = setInterval(() => {
            if (install()) clearInterval(timer);
        }, 500);
    }
})();
