async function process_card_qa_context(frm) {
	const name = frm.doc.qcmc_process_card;
	const sequence = (frm._qa_context_request || 0) + 1;
	frm._qa_context_request = sequence;
	if (!name) return;
	const card = await frappe.db.get_doc("Process Card", name);
	if (sequence !== frm._qa_context_request || frm.doc.qcmc_process_card !== name) return;
	const names = (card.jobs || []).map(row => row.job_card).filter(Boolean);
	frm.set_query("reference_name", () => ({
		filters: {name: ["in", names.length ? names : [""]], company: card.company},
	}));
	if (frm.doc.docstatus !== 0) return;
	await frm.set_value({inspection_type: "In Process", reference_type: "Job Card", company: card.company});
	if (names.length === 1 && !frm.doc.reference_name) {
		await frm.set_value("reference_name", names[0]);
	}
}

frappe.ui.form.on("Quality Inspection", {
	refresh: process_card_qa_context,
	qcmc_process_card: process_card_qa_context,
	async reference_name(frm) {
		if (!frm.doc.qcmc_process_card || frm.doc.reference_type !== "Job Card" || !frm.doc.reference_name) return;
		const name = frm.doc.reference_name;
		const job = await frappe.db.get_doc("Job Card", name);
		if (frm.doc.reference_name !== name) return;
		await frm.set_value({item_code: job.production_item, qcmc_work_order: job.work_order});
	},
});
