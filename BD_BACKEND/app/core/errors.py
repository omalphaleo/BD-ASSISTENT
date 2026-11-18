"""Exception handlers that shape error responses for the whole API.

Needed because FastAPI's default 422 body echoes each rejected value in "input", which would
return a submitted password to the client; app.main registers these handlers once.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# A literal, because Starlette renamed the HTTP_422_* constant between versions and the
# old name now emits a DeprecationWarning.
VALIDATION_ERROR_STATUS = 422

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


def register_error_handlers(app: FastAPI) -> None:
    """Install the API's exception handlers on the app."""
    app.add_exception_handler(RequestValidationError, validation_error_handler)
