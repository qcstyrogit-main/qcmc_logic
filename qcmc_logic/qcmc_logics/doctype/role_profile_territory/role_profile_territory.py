import frappe
from frappe import _
from frappe.model.document import Document


class RoleProfileTerritory(Document):
    def validate(self):
        self.validate_allowed_territories()

    def validate_allowed_territories(self):
        rows = self.get("allowed_territories") or []
        if not rows:
            frappe.throw(_("At least one Allowed Territory is required."))

        if len(rows) == 1:
            rows[0].is_default = 1

        seen = set()
        defaults = []

        for row in rows:
            if not row.territory:
                frappe.throw(_("Territory is mandatory in row {0}.").format(row.idx))

            if row.territory in seen:
                frappe.throw(
                    _("Territory {0} is duplicated.").format(frappe.bold(row.territory))
                )
            seen.add(row.territory)

            if row.is_default:
                defaults.append(row.territory)

        if len(defaults) > 1:
            frappe.throw(_("Only one default Territory is allowed."))

