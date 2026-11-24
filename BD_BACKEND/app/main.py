"""FastAPI application entry point: creates the app and mounts the routers.

Needed as the single object uvicorn serves (app.main:app); each module's router is
included here, so this file only wires routes and holds no business logic.
"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.api import router as core_router
from app.core.csrf import CSRF_HEADER_NAME, install_csrf_openapi, verify_csrf
from app.core.errors import install_validation_error_openapi, register_error_handlers
from app.core.permissions import install_permission_openapi

# Methods and headers the frontend may use cross-origin; listed explicitly, never "*" (A8-5).
CORS_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
CORS_ALLOWED_HEADERS = ["Content-Type", CSRF_HEADER_NAME]

# verify_csrf is an app-level dependency so every route, present and future, gets the Origin
# and token checks without declaring them (a forgotten route cannot be left unprotected).
app = FastAPI(title="Alphaleo BD API", version="0.0.1", dependencies=[Depends(verify_csrf)])
# Only the frontend may call the API from a browser, with the session cookie. Added after
# the app exists and therefore outermost, so preflight (OPTIONS) requests are answered here
# and even a CSRF 403 carries the CORS headers the browser needs to read it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_credentials=True,
    allow_methods=CORS_ALLOWED_METHODS,
    allow_headers=CORS_ALLOWED_HEADERS,
)
# Error bodies must never echo submitted values such as passwords (FastAPI's default 422
# does), so validation errors go through our own handler.
register_error_handlers(app)
app.include_router(core_router)
# Adds the 401/403 responses of permission-guarded routes to the OpenAPI schema; runs after
# the routers are mounted because it reads each route's declared guard.
install_permission_openapi(app)
# Adds the CSRF 403 to every state-changing operation; wraps the schema built above.
install_csrf_openapi(app)
# Documents the narrowed 422 body our handler really returns; wraps the schema built above.
install_validation_error_openapi(app)
