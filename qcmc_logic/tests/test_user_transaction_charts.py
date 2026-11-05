"""Management chart API checks. Run with Bench on the development site."""

import json
import unittest
from unittest.mock import patch

import frappe

from qcmc_logic.qcmc_logics.page.user_transaction_dashboard import user_transaction_dashboard as dashboard


class TestUserTransactionCharts(unittest.TestCase):
    def setUp(self):
        self.user = frappe.session.user
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user(self.user)

    def test_trend_matches_independent_sql_and_zero_fills_days(self):
        trend = dashboard.get_creation_trend("2026-06-01", "2026-06-30", ["Purchase Order"], interval="day")
        self.assertEqual(len(trend["labels"]), 30)
        self.assertEqual(trend["labels"][0], "2026-06-01")
        self.assertEqual(trend["labels"][-1], "2026-06-30")
        expected = dict(frappe.db.sql(
            "SELECT DATE(creation), COUNT(*) FROM `tabPurchase Order` "
            "WHERE creation >= %s AND creation < %s GROUP BY DATE(creation)",
            ("2026-06-01", "2026-07-01"),
        ))
        self.assertEqual(trend["values"], [expected.get(frappe.utils.getdate(day), 0) for day in trend["labels"]])
        filtered = dashboard.get_creation_trend("2026-06-01", "2026-06-30", ["Purchase Order"], ["Administrator"], "month")
        count = frappe.db.sql("SELECT COUNT(*) FROM `tabPurchase Order` WHERE creation >= %s AND creation < %s AND owner=%s",
                              ("2026-06-01", "2026-07-01", "Administrator"))[0][0]
        self.assertEqual(filtered, {"labels": ["2026-06"], "values": [count]})
        self.assertEqual(dashboard.get_creation_trend("2026-01-01", "2026-03-01", [], interval="month"),
                         {"labels": ["2026-01", "2026-02", "2026-03"], "values": [0, 0, 0]})

    def test_trend_validates_scope_and_range(self):
        for kwargs in [dict(interval="year"), dict(doctypes=["User"]), dict(doctypes="not json"),
                       dict(users={"owner": "Administrator"}), dict(date_to="2025-01-01"),
                       dict(date_to="2028-01-01", interval="day"), dict(date_to="2040-01-01")]:
            args = dict(date_from="2026-01-01", date_to="2026-01-31", doctypes=[])
            args.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(frappe.ValidationError):
                dashboard.get_creation_trend(**args)

    def test_chart_layout_validation_and_compatible_metrics(self):
        chart = dict(id="chart_1", title="Adoption", type="donut", metric="adoption", group_by="overall", top_n=10)
        self.assertEqual(dashboard.validate_chart_layout([chart]), [chart])
        for change in [dict(type="script"), dict(metric="revenue"), dict(group_by="password"),
                       dict(type="line"), dict(metric="usage_rate"), dict(group_by="module"),
                       dict(top_n=-1), dict(title="x" * 121), dict(id='bad"id')]:
            with self.subTest(change=change), self.assertRaises(frappe.ValidationError):
                dashboard.validate_chart_layout([{**chart, **change}])
        with self.assertRaises(frappe.ValidationError):
            dashboard.validate_chart_layout([chart, chart])
        self.assertEqual(dashboard.validate_chart_layout([]), [])

    def test_personal_settings_preserve_empty_layout_and_native_settings(self):
        store = {"Administrator": {"other_setting": 42}}

        def get_settings(doctype):
            self.assertEqual(doctype, "Page")
            return json.dumps(store.get(frappe.session.user, {}))

        def update_settings(doctype, values):
            self.assertEqual(doctype, "Page")
            store.setdefault(frappe.session.user, {}).update(values)

        with patch("frappe.model.utils.user_settings.get_user_settings", side_effect=get_settings), patch(
            "frappe.model.utils.user_settings.update_user_settings", side_effect=update_settings
        ):
            self.assertEqual(dashboard.get_chart_layout(), {"charts": None})
            self.assertEqual(dashboard.save_chart_layout("[]"), {"charts": []})
            self.assertEqual(dashboard.get_chart_layout(), {"charts": []})
            self.assertEqual(store["Administrator"]["other_setting"], 42)
            self.assertEqual(set(store), {"Administrator"})

    def test_all_chart_endpoints_require_system_manager(self):
        frappe.set_user("Guest")
        for method, args in [(dashboard.get_chart_layout, ()), (dashboard.save_chart_layout, ([],)),
                             (dashboard.get_creation_trend, ("2026-01-01", "2026-01-31"))]:
            with self.subTest(method=method.__name__), self.assertRaises(frappe.PermissionError):
                method(*args)


def run_tests():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TestUserTransactionCharts))
    if not result.wasSuccessful():
        raise AssertionError("Management chart tests failed")
    return {"tests_run": result.testsRun, "successful": True}
