(function () {
    const PRINT_FORMAT_RULES = {
        "Material Request": function (frm) {
            return frm.doc.material_request_type === "Material Issue"
                ? "Issuance to Production"
                : "PR_Form_Jinja";
        },

        "Purchase Order": function (frm) {
            // change this condition/format names
            return frm.doc.naming_series === ".Q.X.#" || 
            frm.doc.naming_series === ".M.X.#" || 
            frm.doc.naming_series === ".MCY.#"
                ? "PO_APEX"
                : "PO";
        }

        // "Sales Invoice": function (frm) {
        //     // change this condition/format names
        //     return frm.doc.is_return
        //         ? "Sales Return Format"
        //         : "Sales Invoice";
        // }
    };

    function get_dynamic_print_format(frm) {
        const rule = PRINT_FORMAT_RULES[frm.doctype];
        return rule ? rule(frm) : null;
    }

    function open_dynamic_print(frm) {
        const print_format = get_dynamic_print_format(frm);

        if (!print_format) {
            frm.print_doc();
            return;
        }

        const url =
            `/printview?doctype=${encodeURIComponent(frm.doc.doctype)}` +
            `&name=${encodeURIComponent(frm.doc.name)}` +
            `&trigger_print=1` +
            `&format=${encodeURIComponent(print_format)}` +
            `&no_letterhead=0`;

        window.open(url, "_blank");
    }

    frappe.ui.form.on(Object.keys(PRINT_FORMAT_RULES), {
        refresh(frm) {
            frm.page.set_primary_action(__("Print"), function () {
                open_dynamic_print(frm);
            });
        }
    });
})();