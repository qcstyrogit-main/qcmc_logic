import time

import frappe
from pydantic import BaseModel, HttpUrl, ValidationError
from werkzeug import Response
from werkzeug.exceptions import NotFound

from frappe_assistant_core.utils.oauth_compat import (
    create_oauth_client,
    get_oauth_settings,
    validate_dynamic_client_metadata,
)


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