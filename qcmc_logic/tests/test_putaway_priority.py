import unittest
from unittest.mock import patch

import frappe


def module():
    from qcmc_logic import putaway_priority
    return putaway_priority


class TestPutawayPriority(unittest.TestCase):
    def rule(self, **values):
        doc = frappe.get_doc({
            "doctype": "Putaway Rule", "name": "NEW", "company": "COMPANY", "warehouse": "WH",
            "item_code": "ITEM", "priority": 999, "custom_no_item_restriction": 0, **values,
        })
        return doc

    def test_new_rule_uses_highest_priority_including_disabled_positions(self):
        priority = module()
        rule = self.rule()
        with (
            patch.object(rule, "get_doc_before_save", return_value=None),
            patch.object(priority, "get_group_rows", return_value=[frappe._dict(priority=1), frappe._dict(priority=8, disable=1)]) as read,
        ):
            priority.assign_priority(rule)
        self.assertEqual(rule.priority, 9)
        read.assert_called_once_with(rule, for_update=True)

    def test_first_rule_starts_at_one(self):
        priority = module()
        rule = self.rule()
        with patch.object(rule, "get_doc_before_save", return_value=None), patch.object(priority, "get_group_rows", return_value=[]):
            priority.assign_priority(rule)
        self.assertEqual(rule.priority, 1)

    def test_existing_edit_preserves_saved_priority_and_ignores_manual_number(self):
        priority = module()
        rule = self.rule()
        previous = self.rule(priority=4)
        with patch.object(rule, "get_doc_before_save", return_value=previous), patch.object(priority, "get_group_rows") as read:
            priority.assign_priority(rule)
        self.assertEqual(rule.priority, 4)
        read.assert_not_called()

    def test_changing_item_appends_to_destination_group(self):
        priority = module()
        rule = self.rule(item_code="OTHER")
        with patch.object(rule, "get_doc_before_save", return_value=self.rule(priority=4)), patch.object(priority, "get_group_rows", return_value=[frappe._dict(priority=6)]):
            priority.assign_priority(rule)
        self.assertEqual(rule.priority, 7)

    def test_scope_separates_company_warehouse_item_and_unrestricted(self):
        priority = module()
        key = priority.group_key(self.rule())
        for values in [dict(company="OTHER"), dict(warehouse="OTHER"), dict(item_code="OTHER"), dict(custom_no_item_restriction=1)]:
            self.assertNotEqual(key, priority.group_key(self.rule(**values)))
        self.assertEqual(priority.group_key(self.rule(custom_no_item_restriction=1)), priority.group_key(self.rule(custom_no_item_restriction=1, item_code="")))

    def test_locks_both_warehouses_in_stable_order_before_document_lock(self):
        priority = module()
        rule = self.rule(warehouse="A")
        with patch.object(rule, "is_new", return_value=False), patch.object(frappe.db, "get_value", return_value="Z"), patch.object(frappe.db, "sql") as sql:
            priority.lock_rule_warehouses(rule)
        self.assertEqual([call.args[1] for call in sql.call_args_list], [("A",), ("Z",)])
        self.assertTrue(all("for update" in call.args[0].lower() for call in sql.call_args_list))

    def test_group_query_is_scoped_and_does_not_drop_disabled_rules(self):
        priority = module()
        with patch.object(frappe.db, "sql", return_value=[]) as sql:
            priority.get_group_rows(self.rule(), for_update=True)
        query, values = sql.call_args.args
        self.assertEqual((values["company"], values["warehouse"], values["item"]), ("COMPANY", "WH", "ITEM"))
        self.assertIn("for update", query.lower())
        self.assertNotIn("disable = 0", query.lower())

    def test_reorder_accepts_only_a_complete_unique_group(self):
        priority = module()
        rows = [frappe._dict(name="A"), frappe._dict(name="B")]
        self.assertEqual(priority.validate_order(["B", "A"], rows), ["B", "A"])
        for names in [["A"], ["A", "A"], ["A", "FOREIGN"]]:
            with self.assertRaises(frappe.ValidationError):
                priority.validate_order(names, rows)

    def test_group_version_changes_on_priority_or_membership_change(self):
        priority = module()
        rows = [dict(name="A", priority=1, modified="one")]
        version = priority.group_version(rows)
        self.assertNotEqual(version, priority.group_version([dict(name="A", priority=2, modified="one")]))
        self.assertNotEqual(version, priority.group_version(rows + [dict(name="B", priority=2)]))

    def test_save_reorders_only_priority_and_retains_disabled_rule(self):
        priority = module()
        rule = self.rule(name="A")
        rows = [frappe._dict(name="A", priority=1), frappe._dict(name="B", priority=2), frappe._dict(name="C", priority=3, disable=1)]
        with (
            patch.object(frappe, "get_doc", return_value=rule),
            patch.object(priority, "_check_access"), patch.object(priority, "_check_group_access"),
            patch.object(priority, "_lock_warehouses"),
            patch.object(priority, "get_group_rows", return_value=rows),
            patch.object(frappe.db, "set_value") as write,
            patch.object(frappe, "clear_document_cache"),
        ):
            priority.save_priority_order("A", ["B", "A", "C"], priority.group_version(rows))
        self.assertEqual([call.args for call in write.call_args_list], [
            ("Putaway Rule", "B", "priority", 1), ("Putaway Rule", "A", "priority", 2),
        ])

    def test_stale_order_cannot_overwrite_a_new_rule_or_other_user_order(self):
        priority = module()
        with (
            patch.object(frappe, "get_doc", return_value=self.rule()),
            patch.object(priority, "_check_access"), patch.object(priority, "_lock_warehouses"),
            patch.object(priority, "get_group_rows", return_value=[frappe._dict(name="A", priority=1)]),
            patch.object(frappe.db, "set_value") as write,
        ):
            with self.assertRaises(frappe.TimestampMismatchError):
                priority.save_priority_order("A", ["A"], "stale")
        write.assert_not_called()

    def test_reordering_requires_write_permission_on_every_group_member(self):
        priority = module()
        rows = [frappe._dict(name="A", priority=1)]
        with (
            patch.object(frappe, "get_doc", return_value=self.rule()),
            patch.object(priority, "_check_access"), patch.object(priority, "_lock_warehouses"),
            patch.object(priority, "get_group_rows", return_value=rows),
            patch.object(frappe, "has_permission", return_value=False),
            patch.object(frappe.db, "set_value") as write,
        ):
            with self.assertRaises(frappe.PermissionError):
                priority.save_priority_order("A", ["A"], priority.group_version(rows))
        write.assert_not_called()

    def test_controller_locks_warehouse_before_frappe_locks_the_rule(self):
        from qcmc_logic.overrides import putaway_rule
        order = []
        rule = self.rule()
        with (
            patch.object(putaway_rule, "lock_rule_warehouses", side_effect=lambda rule: order.append("warehouse")),
            patch.object(putaway_rule.PutawayRule, "check_if_latest", side_effect=lambda: order.append("rule")),
        ):
            rule.check_if_latest()
        self.assertEqual(order, ["warehouse", "rule"])


def run_tests():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TestPutawayPriority))
    if not result.wasSuccessful():
        raise AssertionError("Putaway priority tests failed")
    return {"tests_run": result.testsRun, "successful": True}
