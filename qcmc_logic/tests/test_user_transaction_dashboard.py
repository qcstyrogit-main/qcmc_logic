"""Read-only checks, run with Bench against the development site."""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate


class TestUserTransactionDashboard(unittest.TestCase):
    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        from qcmc_logic.qcmc_logics.page.user_transaction_dashboard import user_transaction_dashboard
        self.dashboard = user_transaction_dashboard

    def tearDown(self):
        frappe.set_user(self.original_user)

    def test_requires_system_manager_before_reading_data(self):
        frappe.set_user("Guest")
        with patch.object(frappe, "get_all", side_effect=AssertionError("Unauthorized data read")):
            with self.assertRaises(frappe.PermissionError):
                self.dashboard.get_data("2026-10-01", "2026-10-30")

    def test_synced_page_loads_assets_and_enforces_page_access(self):
        from frappe.desk.desk_page import get

        page = get("user-transaction-dashboard")
        self.assertEqual(page.name, "user-transaction-dashboard")
        self.assertEqual([row.role for row in page.roles], ["System Manager"])
        self.assertTrue(page.script)
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            get("user-transaction-dashboard")

    def test_invalid_and_missing_dates_are_rejected(self):
        for start, end in [(None, None), ("2026-10-01", None),
                           (None, "2026-10-30"), ("2026-10-31", "2026-10-01"),
                           ("bad", "2026-10-30"), ("2026-10-01", "2026-02-30"),
                           ("0000-00-00", "2026-10-30")]:
            with self.subTest(start=start, end=end):
                with self.assertRaises(frappe.ValidationError):
                    self.dashboard.get_data(start, end)

    def test_matrix_matches_independent_sql_including_end_day_and_all_statuses(self):
        sample = frappe.db.sql("SELECT DATE(creation) FROM `tabPurchase Order` ORDER BY creation DESC LIMIT 1")
        day = str(sample[0][0]) if sample else str(getdate())
        for start, end in [("2000-01-01", "2100-01-01"), (day, day),
                           ("2999-01-01", "2999-01-01")]:
            with self.subTest(start=start, end=end):
                data = self.dashboard.get_data(start, end)
                users = set(frappe.get_all("User", pluck="name"))
                expected_types = frappe.get_all("DocType", filters={
                    "is_submittable": 1, "istable": 0, "issingle": 0, "is_virtual": 0,
                }, pluck="name", order_by="name")
                self.assertEqual(data["doctypes"], expected_types)
                self.assertEqual(set(data["doctype_modules"]), set(expected_types))
                self.assertEqual(data["doctype_modules"]["Purchase Order"],
                                 frappe.db.get_value("DocType", "Purchase Order", "module"))
                actual = {row["user"]: row for row in data["rows"]}
                self.assertTrue(users.issubset(actual))
                expected = {user: dict.fromkeys(expected_types, 0) for user in users}
                for dt in expected_types:
                    table = "`tab" + dt.replace("`", "``") + "`"
                    # Aggregate each status independently; the dashboard must include all.
                    stats = frappe.db.sql(
                        "SELECT owner, docstatus, COUNT(*) FROM " + table
                        + " WHERE creation >= %s AND creation < %s GROUP BY owner, docstatus",
                        (start, add_days(end, 1)),
                    )
                    for owner, status, count in stats:
                        expected.setdefault(owner, dict.fromkeys(expected_types, 0))[dt] += count
                self.assertEqual(set(actual), set(expected))
                for user in expected:
                    self.assertEqual(actual[user]["counts"], expected[user])
                    self.assertEqual(actual[user]["total"], sum(expected[user].values()))
                column_totals = {dt: sum(row[dt] for row in expected.values()) for dt in expected_types}
                self.assertEqual(data["totals"], {"counts": column_totals, "total": sum(column_totals.values())})
                self.assertEqual(data["summary"], {
                    "documents": sum(column_totals.values()),
                    "active_users": sum(any(row.values()) for row in expected.values()),
                    "active_doctypes": sum(bool(value) for value in column_totals.values()),
                })
                if start == "2999-01-01":
                    self.assertTrue(all(row["total"] == 0 for row in data["rows"]))

    def test_historical_documents_remain_counted_without_a_user_account(self):
        baseline = self.dashboard.get_data("2000-01-01", "2100-01-01")
        owner_row = next((row for row in baseline["rows"] if row["total"]), None)
        if owner_row is None:
            self.skipTest("No historical transactions on this site")
        owner = owner_row["user"]
        get_all = frappe.get_all

        def without_account(doctype, **kwargs):
            records = get_all(doctype, **kwargs)
            if doctype == "User":
                return [row for row in records if row.name != owner]
            if doctype == "Employee":
                return [row for row in records if row.user_id != owner]
            return records

        # Simulate missing account metadata while retaining real transaction queries.
        with patch.object(frappe, "get_all", side_effect=without_account):
            data = self.dashboard.get_data("2000-01-01", "2100-01-01")
        self.assertEqual(data["totals"], baseline["totals"])
        actual = next(row for row in data["rows"] if row["user"] == owner)
        self.assertEqual(actual["employee_name"], owner)
        self.assertEqual(actual["counts"], owner_row["counts"])

    def test_employee_labels_do_not_duplicate_users_and_have_fallbacks(self):
        fixtures = {
            "User": [frappe._dict(name="a@example.com", full_name="Same Name"),
                     frappe._dict(name="b@example.com", full_name="Same Name"),
                     frappe._dict(name="c@example.com", full_name="")],
            "Employee": [frappe._dict(user_id="a@example.com", employee_name="Employee A"),
                         frappe._dict(user_id="a@example.com", employee_name="Duplicate Employee")],
            "DocType": [],
        }
        with patch.object(frappe, "get_all", side_effect=lambda dt, **kwargs: fixtures[dt]):
            rows = self.dashboard.get_data("2026-10-01", "2026-10-30")["rows"]
        self.assertEqual(len(rows), 3)
        labels = {row["user"]: row["employee_name"] for row in rows}
        self.assertEqual(labels, {"a@example.com": "Employee A", "b@example.com": "Same Name", "c@example.com": "c@example.com"})


def run_tests():
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(TestUserTransactionDashboard)
    )
    if not result.wasSuccessful():
        raise AssertionError("User transaction dashboard tests failed")
    return {"tests_run": result.testsRun, "successful": True}


def smoke_check():
    from frappe.desk.desk_page import get

    page = get("user-transaction-dashboard")
    from qcmc_logic.qcmc_logics.page.user_transaction_dashboard.user_transaction_dashboard import get_data
    data = get_data("2026-10-01", "2026-10-30")
    return {"page": page.name, "script_loaded": bool(page.script),
            "users": len(data["rows"]), "doctypes": len(data["doctypes"]),
            "summary": data["summary"]}
