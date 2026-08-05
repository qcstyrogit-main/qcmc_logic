import frappe
from frappe.tests.utils import FrappeTestCase


class TestRoleProfileTerritory(FrappeTestCase):
    def make_doc(self, rows):
        doc = frappe.new_doc("Role Profile Territory")
        doc.role_profile = "Test Role Profile"
        for row in rows:
            doc.append("allowed_territories", row)
        return doc

    def test_requires_at_least_one_territory(self):
        with self.assertRaisesRegex(frappe.ValidationError, "At least one"):
            self.make_doc([]).validate()

    def test_single_territory_becomes_default(self):
        doc = self.make_doc([{"territory": "South Luzon"}])
        doc.validate()
        self.assertEqual(doc.allowed_territories[0].is_default, 1)

    def test_rejects_duplicate_territories(self):
        doc = self.make_doc(
            [
                {"territory": "South Luzon", "is_default": 1},
                {"territory": "South Luzon"},
            ]
        )
        with self.assertRaisesRegex(frappe.ValidationError, "duplicated"):
            doc.validate()

    def test_rejects_multiple_defaults(self):
        doc = self.make_doc(
            [
                {"territory": "South Luzon", "is_default": 1},
                {"territory": "Metro Manila", "is_default": 1},
            ]
        )
        with self.assertRaisesRegex(frappe.ValidationError, "Only one default"):
            doc.validate()

    def test_requires_territory_on_each_row(self):
        doc = self.make_doc([{"territory": "South Luzon"}, {}])
        with self.assertRaisesRegex(frappe.ValidationError, "mandatory"):
            doc.validate()

    def test_uses_same_role_profile_parent_shape_as_access_doctypes(self):
        meta = frappe.get_meta("Role Profile Territory")
        self.assertEqual(meta.get_field("role_profile").fieldtype, "Link")
        self.assertEqual(meta.get_field("role_profile").options, "Role Profile")
        self.assertTrue(meta.get_field("role_profile").unique)
        self.assertEqual(
            meta.get_field("allowed_territories").options,
            "Role Profile Territory Detail",
        )
