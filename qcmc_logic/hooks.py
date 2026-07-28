app_name = "qcmc_logic"
app_title = "QCMC Logics"
app_publisher = "QCMC MIS Section"
app_description = "Company Business Rules and Logics"
app_email = "eguilalas@qcstyro.com"
app_license = "mit"

# Apps
# ------------------
override_whitelisted_methods = {}

doc_events = {
    "*": {
        "validate": [
            "qcmc_logic.customs.warehouse_access_permissions.validate_warehouse_access",
            "qcmc_logic.customs.warehouse_access_permissions.validate_warehouse_type_restriction",
            "qcmc_logic.customs.inventory_group_access_permissions.validate_inventory_group_access",
        ]
    },
    "Warehouse Transfer": {   # 👈 name of your GUI Doctype
        "validate": "qcmc_logic.customs.warehouse_transfer_events.validate_transfer_type_rules",
        "on_submit": "qcmc_logic.customs.warehouse_transfer_events.on_submit",
        "on_update_after_submit": "qcmc_logic.customs.warehouse_transfer_events.on_update_after_submit",
        "on_cancel": "qcmc_logic.customs.warehouse_transfer_events.on_cancel",
        "on_trash": "qcmc_logic.customs.warehouse_transfer_events.on_trash"
    },
    "Warehouse Access": {
        "validate": "qcmc_logic.doctype.warehouse_access.warehouse_access.validate_default_warehouse",
    },
    "Role Profile Warehouse Access": {
        "validate": "qcmc_logic.doctype.warehouse_access.warehouse_access.validate_role_profile_default_warehouse",
    },
    "Inventory Group Access": {
        "validate": "qcmc_logic.doctype.inventory_group_access.inventory_group_access.validate_default_inventory_group",
    },
    "Role Profile Inventory Group Access": {
        "validate": "qcmc_logic.doctype.inventory_group_access.inventory_group_access.validate_role_profile_default_inventory_group",
    },
    "Purchase Receipt": {
        "before_save": "qcmc_logic.overrides.wrr_override.validate"
    },
    "Sales Invoice": {
         "validate": "qcmc_logic.overrides.sales_invoice_override.validate"
    },
    "Sales Order": {
        "before_validate": "qcmc_logic.customs.sales_order.set_customer_account_manager",
        "on_submit": "qcmc_logic.customs.sales_order.update_customer_item_history_on_submit",
        "on_cancel": "qcmc_logic.customs.sales_order.update_customer_item_history_on_cancel",
    },
    "BOM": {
        "before_validate": [
            "qcmc_logic.customs.bom_numeric_fields.normalize_bom_numeric_fields",
            "qcmc_logic.customs.bom_soph.apply_bom_soph_and_operation_time",
            "qcmc_logic.customs.bom_roll_required_kg.apply_roll_required_kg",
            "qcmc_logic.customs.bom_rate.fetch_missing_component_rates",
            "qcmc_logic.customs.bom_formulation.apply_roll_formulation_rules",
        ]
    },
    "Work Order": {
        "validate": "qcmc_logic.customs.work_order_formulation.apply_roll_formulation_required_qty",
    },
    "File": {
        "after_insert": "qcmc_logic.customs.issue_kanban.sync_issue_kanban_image",
        "on_trash": "qcmc_logic.customs.issue_kanban.replace_deleted_issue_kanban_image",
    },
    "Stock Entry": {
        "before_submit": "qcmc_logic.customs.stock_entry.validate_final_job_card_time_log",
        "on_submit": "qcmc_logic.customs.stock_entry.update_final_job_card_time_log_on_submit",
        "on_cancel": "qcmc_logic.customs.stock_entry.update_final_job_card_time_log_on_cancel",
    },
    "Job Card": {
        "on_update": "qcmc_logic.customs.job_card.sync_non_final_operation_progress",
        "on_submit": "qcmc_logic.customs.job_card.sync_non_final_operation_progress",
        "on_cancel": "qcmc_logic.customs.job_card.sync_non_final_operation_progress",
        "on_update_after_submit": "qcmc_logic.customs.job_card.sync_non_final_operation_progress",
        "after_delete": "qcmc_logic.customs.job_card.sync_non_final_operation_progress",
    },
    "Salary Slip": {
        "validate": [
            "qcmc_logic.customs.salary_slip_attendance.apply_attendance_late",
            "qcmc_logic.customs.salary_slip_employer_contributions.apply_employer_contribution_rows",
            "qcmc_logic.customs.salary_slip_hmo.apply_hmo_deduction",
            "qcmc_logic.customs.salary_slip_income_tax.apply_declared_income_tax",
            "qcmc_logic.customs.salary_slip_loan_components.sync_loan_component_rows",
        ],
        "before_save": [
            "qcmc_logic.customs.salary_slip_hmo.apply_hmo_deduction",
            "qcmc_logic.customs.salary_slip_income_tax.apply_declared_income_tax",
        ],
        "before_submit": [
            "qcmc_logic.customs.salary_slip_hmo.apply_hmo_deduction",
            "qcmc_logic.customs.salary_slip_income_tax.apply_declared_income_tax",
        ],
    },
    "Overtime Slip": {
        "before_validate": "qcmc_logic.customs.overtime_slip.normalize_overtime_before_validate",
        "validate": "qcmc_logic.customs.overtime_slip.normalize_overtime_before_validate",
    },
    "Attendance": {
        "before_validate": "qcmc_logic.customs.attendance_overtime.apply_6_to_6_and_7_to_7_overtime",
    },
    "Batch Other Adjustment Entry": {
        "on_cancel": "qcmc_logic.api.batch_other_adjustment.cancel_batch_additional_salaries",
    },
    "Additional Salary": {
        "before_cancel": "qcmc_logic.api.batch_other_adjustment.allow_batch_additional_salary_cancel",
        "on_cancel": "qcmc_logic.api.batch_other_adjustment.update_batch_row_on_additional_salary_cancel",
    },
    "HMO Rate Plan": {
        "validate": "qcmc_logic.customs.hmo_rates.validate_rate_plan",
    },
    "Employee HMO Enrollment": {
        "validate": "qcmc_logic.customs.hmo_enrollment.validate_hmo_enrollment",
    },
    "Machine Shop Job Request": {
        "autoname": "qcmc_logic.customs.machine_shop_job_request.autoname",
        "validate": "qcmc_logic.customs.machine_shop_job_request.validate",
    },
    "Machine Shop Repairs and Project": {
        "validate": "qcmc_logic.customs.machine_shop_repairs_and_project.validate",
    },
    "Job Card Downtime": {
        "validate": "qcmc_logic.customs.job_card_downtime.validate",
    },
    "Job Card Downtime": {
        "validate": "qcmc_logic.customs.job_card_downtime.validate",
    },
}

before_request = [
    "qcmc_logic.patches.oauth_patch.ensure_fac_oauth_alias",
    "qcmc_logic.overrides.lms_inject.redirect_login_to_lms_login",
]

after_request = [
    "qcmc_logic.overrides.lms_inject.inject_lms_login_redirect",
]

doctype_js = {
    "BOM": "public/js/bom.js",
    "Item": "public/js/item.js",
    "Sales Order": "public/js/sales_order.js",
    "Stock Entry": "public/js/stock_entry.js",
    "Work Order": "public/js/work_order.js",
    "Material Request": "public/js/material_request.js",
    "Payment Entry": "public/js/payment_entry.js",
    "Warehouse Transfer": "public/js/warehouse_transfer.js",
    "Overtime Slip": "public/js/overtime_slip.js",
    "Batch Other Adjustment Entry": "public/js/batch_other_adjustment_entry.js",
    "Payroll Entry": "public/js/payroll_entry.js",
    "Salary Structure": "public/js/salary_structure.js",
    "Employee HMO Enrollment": "public/js/employee_hmo_enrollment.js",
    "HMO Rate Plan": "public/js/hmo_rate_plan.js",
    "HMO External Member": "public/js/hmo_external_member.js",
    "Bulk HMO Enrollment Creation": "public/js/bulk_hmo_enrollment_creation.js",
    "Bulk HMO Enrollment Renewal": "public/js/bulk_hmo_enrollment_renewal.js",
    "Mode of Payment": "public/js/mode_of_payment.js",
}

doctype_list_js = {
    "Issue": "public/js/issue_list.js",
}

# override_doctype_class = {
    
#    # ,"Stock Entry": "qcmc_logic.overrides.stock_entry_override.CustomStockEntry"
# }


# override_whitelisted_methods = {
#     "hrms.hr.doctype.staffing_plan.staffing_plan.get_designations": "qcmc_logic.overrides.staffing_plan.get_designations"
# }


override_whitelisted_methods = {
    "frappe.desk.printing.get_print_format": "qcmc_logic.overrides.POPrint_Override.get_po_print_format",
    "frappe.desk.query_report.run": "qcmc_logic.overrides.query_report_override.run",
    "lms.lms.utils.get_courses": "qcmc_logic.overrides.lms_overrides.get_courses",
    "frappe_assistant_core.api.oauth_discovery.protected_resource_metadata":"qcmc_logic.overrides.oauth_override.protected_resource_metadata",
    "frappe_assistant_core.api.oauth_registration.register_client":"qcmc_logic.overrides.oauth_override.register_client",
    "frappe_assistant_core.api.oauth_discovery.oauth_authorization_server":"qcmc_logic.overrides.oauth_override.oauth_authorization_server",
    "erpnext.stock.doctype.delivery_note.delivery_note.make_delivery_trip":"qcmc_logic.overrides.delivery_note_override.make_delivery_trip",
    "erpnext.stock.doctype.material_request.material_request.make_stock_entry": "qcmc_logic.utils.make_stock_entry_from_material_request",
    "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice": "qcmc_logic.overrides.purchase_receipt.make_purchase_invoice",
    "erpnext.manufacturing.doctype.work_order.work_order.get_default_warehouse": "qcmc_logic.overrides.work_order.get_default_warehouse",
}


override_doctype_class = {
    # (Optional, only if overriding full controller)
    "Appraisal": "qcmc_logic.overrides.appraisal_override.CustomAppraisal",
    "Appraisal Cycle": "qcmc_logic.overrides.appraisalcycle_override.CustomAppraisalCycle",
    "Asset": "qcmc_logic.overrides.asset_override.CustomAsset",
    "Job Requisition": "qcmc_logic.overrides.MRFApprovers.MRFApproverSetCustomFields",
    "Staffing Plan": "qcmc_logic.overrides.StaffingPlanOverrides.CustomStaffingPlan",
    "Payment Entry": "qcmc_logic.overrides.payment_entry.CustomPaymentEntry",
    "Payroll Entry": "qcmc_logic.overrides.payroll_entry.CustomPayrollEntry",
    "Job Opening": "qcmc_logic.overrides.jobopening_overrides.CustomJobOpening",
    "Material Request":"qcmc_logic.overrides.material_request_override.CustomMaterialRequest",
    "Stock Reconciliation": "qcmc_logic.overrides.stock_reconciliation.CustomStockReconciliation",
    "Bulk Salary Structure Assignment": "qcmc_logic.overrides.bulk_salary_structure_assignment.CustomBulkSalaryStructureAssignment",
    "Salary Structure Assignment": "qcmc_logic.overrides.salary_structure_assignment.CustomSalaryStructureAssignment",
}
permission_query_conditions = {
     "Appraisal": "qcmc_logic.customs.permissions.appraisal_permission_query",
     "Job Requisition": "qcmc_logic.customs.staffingplan_permission.mrf_permission_query_condition",
     "Delivery Note": "qcmc_logic.customs.permissions.delivery_note_permission_query",
     "Machine Shop Job Request": "qcmc_logic.customs.machine_shop_job_request.msjr_permission_query",
     "Machine Shop Repairs and Project": "qcmc_logic.customs.machine_shop_repairs_and_project.msrp_permission_query",
     "Material Request": "qcmc_logic.customs.permissions.material_request_permission_query",
     "Pick List": "qcmc_logic.customs.permissions.pick_list_permission_query",
     "POS Invoice": "qcmc_logic.customs.permissions.pos_invoice_permission_query",
     "Purchase Invoice": "qcmc_logic.customs.permissions.purchase_invoice_permission_query",
     "Purchase Order": "qcmc_logic.customs.permissions.purchase_order_permission_query",
     "Purchase Receipt": "qcmc_logic.customs.permissions.purchase_receipt_permission_query",
    "Sales Invoice": "qcmc_logic.customs.permissions.sales_invoice_permission_query",
    "Sales Order": "qcmc_logic.customs.permissions.sales_order_permission_query",
    "Salary Structure Assignment": "qcmc_logic.customs.permissions.salary_structure_assignment_permission_query",
    "Salary Structure": "qcmc_logic.customs.permissions.salary_structure_permission_query",
     "Stock Entry": "qcmc_logic.customs.permissions.stock_entry_permission_query",
     "Stock Reconciliation": "qcmc_logic.customs.permissions.stock_reconciliation_permission_query",
     "Subcontracting Order": "qcmc_logic.customs.permissions.subcontracting_order_permission_query",
     "Subcontracting Receipt": "qcmc_logic.customs.permissions.subcontracting_receipt_permission_query",
     "Warehouse Transfer": "qcmc_logic.customs.permissions.warehouse_transfer_permission_query",
}

has_permission = {
    "Delivery Note": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "Machine Shop Job Request": "qcmc_logic.customs.machine_shop_job_request.msjr_has_permission",
    "Machine Shop Repairs and Project": "qcmc_logic.customs.machine_shop_repairs_and_project.msrp_has_permission",
    "Material Request": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "Pick List": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "POS Invoice": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "Purchase Invoice": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "Purchase Order": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "Purchase Receipt": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "Sales Invoice": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "Sales Order": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "Salary Structure Assignment": "qcmc_logic.customs.permissions.salary_structure_assignment_has_permission",
    "Salary Structure": "qcmc_logic.customs.permissions.salary_structure_has_permission",
    "Stock Entry": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "Stock Reconciliation": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "Subcontracting Order": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "Subcontracting Receipt": "qcmc_logic.customs.permissions.warehouse_transaction_has_permission",
    "Warehouse Transfer": "qcmc_logic.customs.permissions.warehouse_transfer_has_permission",
}
override_print_format = {
    "Purchase Order": "qcmc_logic.overrides.POPrint_Override.get_po_print_format"
}

fixtures = [
    {
        "doctype": "Custom Field",
        "filters": [
            ["fieldname", "not in", ["workflow_state"]],
            [
                "name",
                "not in",
                [
                    "User-hide_private",
                    "User-hide_my_private_information_from_others",
                    "Purchase Invoice Item-to_room",
                    "Employee-from_bin",
                    "Employee-from_room",
                    "Delivery Note Item-to_room",
                    "Purchase Receipt Item-from_bin",
                    "Purchase Receipt Item-from_room",
                ],
            ],
        ],
    },
    {"doctype": "Client Script"},
    {"doctype": "Server Script"},
    {"doctype": "List View Settings"},
    {"doctype": "Workflow"},
    {"doctype": "Workflow State"},
    {"doctype": "Report"},
    {"doctype": "Workflow Action Master"},
    {"doctype": "Email Template"},
    {"doctype": "Letter Head"},
    # {"doctype": "User Permission"},
    # {"doctype": "Account"},
    {"doctype": "Module Def"},
    #{"doctype": "Module Profile"},
    {"doctype": "Translation"},  # Added for translations

    {"doctype": "Property Setter"},
    {
        "doctype": "DocType",
        "filters": [
            ["custom", "=", 1],
            [
                "module",
                "in",
                [
                    "Accounts",
                    "Assets",
                    "Buying",
                    "Custom",
                    "HR",
                    "Payroll",
                    "QCMC Logics",
                    "Stock",
                ],
            ],
        ],
    },    
    {
        "doctype": "Print Format"
    },
    "Letter Head",
    {
        "doctype": "Role",
        "filters": [["is_custom", "=", 1]]
    },
    {
        "doctype": "Role Profile",
        "filters": [
            [
                "name",
                "not in",
                ["Accounts", "HR", "Inventory", "Manufacturing", "Purchase", "Sales"],
            ]
        ],
    },
    {"doctype": "Downtime Reason"},
    {"doctype": "Job Card Downtime"},
]
before_migrate = [
    "qcmc_logic.migrate.run_role_profile_updates_inline",
]
after_migrate = [
    "qcmc_logic.customs.machine_shop_job_request.ensure_msjr_permissions",
    "qcmc_logic.customs.machine_shop_repairs_and_project.ensure_msrp_permissions",
    "qcmc_logic.customs.issue_kanban.ensure_company_ticket_kanban",
    "qcmc_logic.customs.work_order_print_format.ensure_job_order_print_formats_use_a5",
]

# # Or ensure it loads at boot
# app_include = [
#     "qcmc_logic.patches.monkey_patches"
# ]
# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "qcmc_logic",
# 		"logo": "/assets/qcmc_logic/logo.png",
# 		"title": "QCMC Logics",
# 		"route": "/qcmc_logic",
# 		"has_permission": "qcmc_logic.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/qcmc_logic/css/qcmc_logic.css"
app_include_js = [
    "/assets/qcmc_logic/js/hide_print_selection.js",
    "/assets/qcmc_logic/js/warehouse_access.js",
    "/assets/qcmc_logic/js/inventory_group_access.js",
    "/assets/qcmc_logic/js/warehouse_transfer.js"
]


# include js, css files in header of web template
# web_include_css = "/assets/qcmc_logic/css/qcmc_logic.css"
# web_include_js = "/assets/qcmc_logic/js/qcmc_logic.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "qcmc_logic/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "qcmc_logic/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
jinja = {
    "methods": [
        "qcmc_logic.api.hmo_print.get_hmo_plan_year_history",
    ],
}

# Installation
# ------------

# before_install = "qcmc_logic.install.before_install"
# after_install = "qcmc_logic.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "qcmc_logic.uninstall.before_uninstall"
# after_uninstall = "qcmc_logic.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "qcmc_logic.utils.before_app_install"
# after_app_install = "qcmc_logic.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "qcmc_logic.utils.before_app_uninstall"
# after_app_uninstall = "qcmc_logic.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "qcmc_logic.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

scheduler_events = {
    "cron": {
        "*/30 * * * *": [
            "qcmc_logic.api.zkteco.fetch_and_insert_attendance_logs"
        ]
    }
}

# Testing
# -------

# before_tests = "qcmc_logic.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "qcmc_logic.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "qcmc_logic.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["qcmc_logic.utils.before_request"]
# after_request = ["qcmc_logic.utils.after_request"]

# Job Events
# ----------
# before_job = ["qcmc_logic.utils.before_job"]
# after_job = ["qcmc_logic.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"qcmc_logic.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

