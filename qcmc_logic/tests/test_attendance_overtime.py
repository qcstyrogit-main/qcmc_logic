from qcmc_logic.customs.attendance_overtime import calculate_overtime_hours


def test_overtime_starts_after_eight_actual_hours():
	assert calculate_overtime_hours(6) == 0
	assert calculate_overtime_hours(8) == 0
	assert calculate_overtime_hours(10) == 2
	assert calculate_overtime_hours(11) == 3
	assert calculate_overtime_hours(12) == 4
	assert calculate_overtime_hours(14) == 6
