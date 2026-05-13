import frappe
from werkzeug.exceptions import HTTPException
from werkzeug.utils import redirect as werkzeug_redirect

SCRIPT_TAG = b'<script src="/assets/qcmc_logic/js/lms_login_redirect.js"></script>'


class _LMSLoginRedirect(HTTPException):
	def __init__(self, location):
		self._location = location
		super().__init__()

	def get_response(self, environ=None, scope=None):
		return werkzeug_redirect(self._location, 302)


def inject_lms_login_redirect(response, request):
	if not request.path.startswith("/lms"):
		return

	content_type = response.headers.get("Content-Type", "")
	if "text/html" not in content_type:
		return

	body = response.get_data()
	if b"</head>" not in body:
		return

	response.set_data(body.replace(b"</head>", SCRIPT_TAG + b"</head>", 1))


def redirect_login_to_lms_login():
	request = frappe.local.request
	if request.path != "/login":
		return

	referer = request.referrer or ""
	redirect_to = request.args.get("redirect-to", "")

	if "/lms" in referer or redirect_to.startswith("/lms"):
		location = "/lms-login"
		if redirect_to:
			import urllib.parse
			location += "?redirect-to=" + urllib.parse.quote(redirect_to)
		raise _LMSLoginRedirect(location)
