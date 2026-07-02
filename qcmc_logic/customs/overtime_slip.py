from qcmc_logic.customs.overtime_policy import normalize_overtime_details


def normalize_overtime_before_validate(doc, method=None):
	normalize_overtime_details(doc)
