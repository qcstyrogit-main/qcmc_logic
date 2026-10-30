"""Integration checks for a development site with the report synced."""

import unittest

import frappe
from frappe.desk.query_report import run
from frappe.utils import add_days, getdate

from .user_transaction_activity import execute


class TestUserTransactionActivity(unittest.TestCase):
    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user(self.original_user)

    def test_runner_matches_independent_database_totals(self):
        users = set(frappe.get_all("User", pluck="name"))
        doctypes = frappe.get_all(
            "DocType",
            filters={"is_submittable": 1, "istable": 0, "issingle": 0, "is_virtual": 0},
            pluck="name",
        )
        today = str(getdate())
        sample = frappe.db.sql(
            "SELECT DATE(creation) FROM `tabWarehouse Transfer` ORDER BY creation DESC LIMIT 1"
        )
        sample_day = str(sample[0][0]) if sample else today
        cases = [
            {},
            {"created_from": sample_day, "created_to": sample_day},
            {"created_from": today},
            {"created_to": today},
            {"created_from": today, "created_to": today},
            {"created_from": "2999-01-01", "created_to": "2999-01-01"},
        ]
        for filters in cases:
            with self.subTest(filters=filters):
                result = run(
                    "User Transaction Activity", filters=filters, ignore_prepared_report=True
                )["result"]
                actual = {row["user"]: row for row in result}
                self.assertEqual(set(actual), users)
                expected = self.database_totals(users, doctypes, filters)
                for user, row in actual.items():
                    self.assertEqual(
                        row["total_transactions"],
                        row["draft"] + row["submitted"] + row["cancelled"],
                    )
                    for key, value in expected[user].items():
                        self.assertEqual(row[key], value, (user, key, filters))
                if filters.get("created_from") == "2999-01-01":
                    self.assertTrue(all(r["total_transactions"] == 0 for r in result))
                print(
                    "PASS", filters, "users", len(actual), "zero activity",
                    sum(not r["total_transactions"] for r in result), "total",
                    sum(r["total_transactions"] for r in result),
                )

    @staticmethod
    def database_totals(users, doctypes, filters):
        expected = {
            user: dict(
                draft=0, submitted=0, cancelled=0, total_transactions=0,
                transaction_types=0, last_transaction_creation=None,
            )
            for user in users
        }
        clauses, values = [], {}
        if filters.get("created_from"):
            clauses.append("creation >= %(start)s")
            values["start"] = getdate(filters["created_from"])
        if filters.get("created_to"):
            clauses.append("creation < %(end)s")
            values["end"] = add_days(getdate(filters["created_to"]), 1)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        for doctype in doctypes:
            # Identifiers originate in DocType metadata; escape identifier delimiters.
            table = "`tab" + doctype.replace("`", "``") + "`"
            stats = frappe.db.sql(
                "SELECT owner, docstatus, COUNT(*), MAX(creation) FROM "
                + table + where + " GROUP BY owner, docstatus", values,
            )
            seen = set()
            for owner, status, count, last in stats:
                if owner not in expected:
                    continue
                row = expected[owner]
                row[{0: "draft", 1: "submitted", 2: "cancelled"}[status]] += count
                row["total_transactions"] += count
                if row["last_transaction_creation"] is None or last > row["last_transaction_creation"]:
                    row["last_transaction_creation"] = last
                seen.add(owner)
            for owner in seen:
                expected[owner]["transaction_types"] += 1
        return expected

    def test_inverted_dates(self):
        with self.assertRaises(frappe.ValidationError):
            execute({"created_from": "2026-10-17", "created_to": "2026-10-16"})

    def test_system_manager_only(self):
        report = frappe.get_doc("Report", "User Transaction Activity")
        self.assertEqual([row.role for row in report.roles], ["System Manager"])
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            execute({})
        with self.assertRaises(frappe.PermissionError):
            run("User Transaction Activity", filters={})

    def test_user_details_and_profiles(self):
        rows = {r["user"]: r for r in execute({})[1]}
        for user in frappe.get_all("User", pluck="name"):
            doc = frappe.get_doc("User", user)
            row = rows[user]
            self.assertEqual(row["full_name"], doc.full_name)
            self.assertEqual(row["enabled"], doc.enabled)
            self.assertEqual(row["user_type"], doc.user_type)
            profiles = {p.role_profile for p in doc.role_profiles if p.role_profile}
            if doc.role_profile_name:
                profiles.add(doc.role_profile_name)
            self.assertEqual(row["role_profiles"], ", ".join(sorted(profiles)))
