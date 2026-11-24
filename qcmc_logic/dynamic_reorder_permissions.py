"""Fail-closed permissions until delegated QCMC roles are integration-tested."""
import frappe

def query(user=None):
    return "" if (user or frappe.session.user) == "Administrator" else "1=0"

def has_permission(doc, user=None, permission_type=None):
    return (user or frappe.session.user) == "Administrator"
