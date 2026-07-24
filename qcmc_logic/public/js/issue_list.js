(() => {
	const issue_list_settings = frappe.listview_settings["Issue"] || {};
	const original_onload = issue_list_settings.onload;
	issue_list_settings.onload = function (listview) {
		original_onload?.(listview);

		if (listview.view_name !== "Kanban") {
			frappe.set_route("List", "Issue", "Kanban", "Company Tickets");
		}
	};
	frappe.listview_settings["Issue"] = issue_list_settings;

	if (window.qcmc_issue_kanban_quick_entry_bound) {
		return;
	}
	window.qcmc_issue_kanban_quick_entry_bound = true;

	const hide_non_open_add_buttons = () => {
		if (window.cur_list?.doctype !== "Issue") {
			return;
		}

		document.querySelectorAll(".kanban-column").forEach((column) => {
			const can_add = column.dataset.columnValue === "Open";
			column.querySelector(":scope > .add-card")?.classList.toggle("d-none", !can_add);
			column
				.querySelector(":scope > .new-card-area")
				?.classList.toggle("d-none", !can_add);
		});
	};

	const board_observer = new MutationObserver(hide_non_open_add_buttons);
	board_observer.observe(document.body, { childList: true, subtree: true });
	frappe.after_ajax(hide_non_open_add_buttons);

	document.addEventListener(
		"click",
		(event) => {
			const add_button = event.target.closest(".kanban-column .add-card");
			if (!add_button || window.cur_list?.doctype !== "Issue") {
				return;
			}

			event.preventDefault();
			event.stopImmediatePropagation();

			const column = add_button.closest(".kanban-column");
			const status = column?.dataset.columnValue || "Open";
			const issue = frappe.model.get_new_doc("Issue", null, null, true);
			issue.status = status;

			frappe.ui.form.make_quick_entry(
				"Issue",
				() => window.cur_list?.refresh(),
				null,
				issue
			);
		},
		true
	);
})();
