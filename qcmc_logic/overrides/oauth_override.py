import time

import frappe
from pydantic import BaseModel, HttpUrl, ValidationError
from werkzeug import Response
from werkzeug.exceptions import NotFound
from urllib.parse import urlencode
from frappe_assistant_core.utils.oauth_compat import (
    create_oauth_client,
    get_oauth_settings,
    validate_dynamic_client_metadata,
)

@frappe.whitelist(allow_guest=True)
def oauth_authorization_server():
    data = frappe.call("frappe_assistant_core.api.oauth_discovery.oauth_authorization_server")

    data["authorization_endpoint"] = (
        "https://erp.qcstyro.com/api/method/"
        "fac_oauth_patch.api.oauth_authorize.authorize_entry"
    )

    return data

@frappe.whitelist(allow_guest=True)
def authorize_entry(**kwargs):
    """
    Wrapper for Frappe OAuth authorize that preserves query parameters through login.
    """

    # Capture the original OAuth parameters
    params = dict(frappe.form_dict)

    # Remove frappe RPC command if present
    params.pop("cmd", None)

    # If user is not logged in, redirect to login preserving the full query
    if frappe.session.user == "Guest":
        redirect_url = "/api/method/fac_oauth_patch.api.oauth_authorize.authorize_entry?" + urlencode(params)

        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = f"/login?redirect-to={redirect_url}"
        return

    # User is logged in → forward to real OAuth authorize
    return frappe.call("frappe.integrations.oauth2.authorize", **params)


class OAuth2DynamicClientMetadata(BaseModel):
    redirect_uris: list[HttpUrl]
    token_endpoint_auth_method: str | None = "client_secret_basic"
    grant_types: list[str] | None = ["authorization_code"]
    response_types: list[str] | None = ["code"]

    client_name: str
    scope: str | None = None
    client_uri: HttpUrl | None = None
    logo_uri: HttpUrl | None = None
    contacts: list[str] | None = None
    tos_uri: HttpUrl | None = None
    policy_uri: HttpUrl | None = None
    software_id: str | None = None
    software_version: str | None = None
    jwks_uri: HttpUrl | None = None
    jwks: dict | None = None


@frappe.whitelist(allow_guest=True, methods=["POST"])
def register_client():
    settings = get_oauth_settings()
    if not settings.get("enable_dynamic_client_registration"):
        raise NotFound("Dynamic client registration is not enabled")

    response = Response()
    response.mimetype = "application/json"

    data = frappe.request.json
    if data is None:
        response.status_code = 400
        response.data = frappe.as_json({
            "error": "invalid_client_metadata",
            "error_description": "Request body is empty",
        })
        return response

    try:
        client = OAuth2DynamicClientMetadata.model_validate(data)
    except ValidationError as e:
        response.status_code = 400
        response.data = frappe.as_json({
            "error": "invalid_client_metadata",
            "error_description": str(e),
        })
        return response

    error = validate_dynamic_client_metadata(client)
    if error:
        response.status_code = 400
        response.data = frappe.as_json({
            "error": "invalid_client_metadata",
            "error_description": error,
        })
        return response

    try:
        response_data = create_oauth_client(client)
    except Exception as e:
        frappe.log_error(
            title="OAuth Client Registration Failed",
            message=frappe.get_traceback(),
        )
        response.status_code = 500
        response.data = frappe.as_json({
            "error": "server_error",
            "error_description": "Failed to create OAuth client. Please try again.",
        })
        return response

    auth_method = response_data.get("token_endpoint_auth_method") or "client_secret_basic"

    # Patch: public clients should not receive client_secret
    if auth_method == "none":
        response_data.pop("client_secret", None)
    else:
        response_data["client_secret_expires_at"] = 0

    response_data["client_id_issued_at"] = int(time.time())

    for key in list(response_data.keys()):
        if response_data[key] is None:
            del response_data[key]

    response.status_code = 201
    response.data = frappe.as_json(response_data)
    return response

@frappe.whitelist(allow_guest=True)
def protected_resource_metadata():
    base = frappe.utils.get_url()

    return {
        "resource": base + "/api/method/frappe_assistant_core.api.fac_endpoint.handle_mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "resource_name": "Frappe Assistant Core",
        "resource_documentation": "https://github.com/buildswithpaul/Frappe_Assistant_Core"
    }
