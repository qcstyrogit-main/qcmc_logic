import frappe
from frappe.rate_limiter import rate_limit
from lms.lms.utils import update_course_filters, get_course_fields, get_featured_courses, get_enrollment_details, get_course_card_details


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=50, seconds=60 * 60)
def get_courses(filters=None, start=0):
	# sanity check - log when override is triggered
	# create here a console log to confirm that the override is being triggered

	
    
	user = frappe.session.user
	roles = frappe.get_roles(user)
    

	if "Moderator" in roles or "Course Creator" in roles or "Batch Evaluator" in roles:
		if not filters:
			filters = {}

		filters, or_filters, show_featured = update_course_filters(filters)
		fields = get_course_fields()

		courses = frappe.get_all(
			"LMS Course",
			filters=filters,
			fields=fields,
			or_filters=or_filters,
			order_by="enrollments desc",
			start=start,
			page_length=30,
		)

		if show_featured:
			courses = get_featured_courses(filters, or_filters, fields) + courses

		courses = get_enrollment_details(courses)
		courses = get_course_card_details(courses)
		return courses

	else:
		enrolled_courses = frappe.get_all("LMS Enrollment", filters={"member": user}, pluck="course")

		if not enrolled_courses:
			return []

		if not filters:
			filters = {}

		filters["name"] = ["in", enrolled_courses]
		
		filters, or_filters, show_featured = update_course_filters(filters)
		fields = get_course_fields()

		courses = frappe.get_all(
			"LMS Course",
			filters=filters,
			fields=fields,
			or_filters=or_filters,
			order_by="enrollments desc",
			start=start,
			page_length=30,
		)

		if show_featured:
			courses = get_featured_courses(filters, or_filters, fields) + courses

		courses = get_enrollment_details(courses)
		courses = get_course_card_details(courses)
		return courses
