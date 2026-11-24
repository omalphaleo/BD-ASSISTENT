"""Exception handlers that shape error responses for the whole API.

Needed because FastAPI's default 422 body echoes each rejected value in "input", which would
return a submitted password to the client, and so a permission failure raised in a guard or
a service becomes the fixed 403 body; app.main registers these handlers once.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.permissions import PERMISSION_DENIED_DETAIL, PermissionDeniedError
from app.core.schemas import ValidationErrorResponse

VALIDATION_RESPONSE_NAME = "ValidationErrorResponse"

# A literal, because Starlette renamed the HTTP_422_* constant between versions and the
# old name now emits a DeprecationWarning.
VALIDATION_ERROR_STATUS = 422
PERMISSION_DENIED_STATUS = 403

# The only keys of a validation error that are safe to return. "input" holds the submitted
# value, "ctx" can embed it, and "url" is documentation noise.
SAFE_ERROR_KEYS = ("type", "loc", "msg")


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return a 422 whose errors keep only type, loc and msg (never the submitted values).

    Args:
        request: The failed request; unused, required by the handler signature.
        exc: The validation error raised by FastAPI.

    Returns:
        A JSON response with status 422 and body {"detail": [{"type", "loc", "msg"}, ...]}.
    """
    detail = [{key: error[key] for key in SAFE_ERROR_KEYS} for error in exc.errors()]
    return JSONResponse(status_code=VALIDATION_ERROR_STATUS, content={"detail": detail})


async def permission_denied_handler(request: Request, exc: PermissionDeniedError) -> JSONResponse:
    """Return a 403 with the fixed body, whatever capability or owner check failed (A6-5).

    Args:
        request: The denied request; unused, required by the handler signature.
        exc: The denial raised by a guard or a service; unused, its details stay server-side.

    Returns:
        A JSON response with status 403 and body {"detail": "Not permitted"}.
    """
    return JSONResponse(
        status_code=PERMISSION_DENIED_STATUS, content={"detail": PERMISSION_DENIED_DETAIL}
    )


def install_validation_error_openapi(app: FastAPI) -> None:
    """Document the real 422 body (type, loc, msg) in the OpenAPI schema.

    FastAPI documents its default HTTPValidationError, which allows "input" and "ctx"; our
    handler never returns them, so the schema is narrowed to what is actually sent. Wraps
    app.openapi, so call it after install_permission_openapi and after the routers exist.
    """
    build_previous_schema = app.openapi

    def openapi_with_validation_errors() -> dict[str, Any]:
        schema = build_previous_schema()
        schemas = schema.setdefault("components", {}).setdefault("schemas", {})
        if VALIDATION_RESPONSE_NAME in schemas:  # already rewritten; FastAPI caches the schema
            return schema
        # Nested models are emitted under $defs; OpenAPI wants them in components/schemas.
        model_schema = ValidationErrorResponse.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        schemas.update(model_schema.pop("$defs", {}))
        schemas[VALIDATION_RESPONSE_NAME] = model_schema
        # The default schemas are no longer referenced once every 422 points at ours.
        schemas.pop("HTTPValidationError", None)
        schemas.pop("ValidationError", None)
        response = {
            "description": "Validation error",
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{VALIDATION_RESPONSE_NAME}"}
                }
            },
        }
        for path_item in schema["paths"].values():
            for operation in path_item.values():
                if "422" in operation.get("responses", {}):
                    operation["responses"]["422"] = response
        return schema

    app.openapi = openapi_with_validation_errors  # type: ignore[method-assign]


def register_error_handlers(app: FastAPI) -> None:
    """Install the API's exception handlers on the app."""
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(PermissionDeniedError, permission_denied_handler)
