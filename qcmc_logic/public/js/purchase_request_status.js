// Keep Frappe's separate draft/submitted cancellation paths, but present one
// cancellation label in forms, workflow indicators, and list views.
frappe._messages = frappe._messages || {};
frappe._messages["Cancelled Before Submission"] = "Cancelled";
frappe._messages["Cancelled Before Submission:Material Request"] = "Cancelled";
