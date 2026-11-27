"""FastAPI application entry point: creates the app and mounts the routers.

Needed as the single object uvicorn serves (app.main:app); each module's router is
included here, so this file only wires routes and holds no business logic.
"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.compliance.opt_outs_api import router as opt_outs_router
from app.config import get_settings
from app.core.api import router as core_router
from app.core.csrf import CSRF_HEADER_NAME, install_csrf_openapi, verify_csrf
from app.core.errors import install_validation_error_openapi, register_error_handlers
from app.core.permissions import install_permission_openapi
from app.imports.api import router as imports_router
from app.imports.profiles_api import router as source_profiles_router
from app.leads.companies_api import router as companies_router
from app.leads.duplicates_api import router as duplicates_router
from app.leads.mappings_api import router as reference_mappings_router
from app.leads.people_api import router as people_router
from app.leads.quarantine_api import router as quarantine_router
from app.leads.search_api import router as search_router
from app.leads.segments_api import router as segments_router

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
# M2 routers are mounted empty here once (M2-0) so no feature task edits main.py again; each
# one gains its endpoints in the task that owns it.
app.include_router(imports_router)
app.include_router(source_profiles_router)
app.include_router(quarantine_router)
app.include_router(duplicates_router)
app.include_router(reference_mappings_router)
# M3 routers are mounted empty here once (M3-0) so neither workstream edits main.py again.
# W1: search and segments. W2: people, companies and opt-outs.
app.include_router(search_router)
app.include_router(segments_router)
app.include_router(people_router)
app.include_router(companies_router)
app.include_router(opt_outs_router)
# Adds the 401/403 responses of permission-guarded routes to the OpenAPI schema; runs after
# the routers are mounted because it reads each route's declared guard.
install_permission_openapi(app)
# Adds the CSRF 403 to every state-changing operation; wraps the schema built above.
install_csrf_openapi(app)
# Documents the narrowed 422 body our handler really returns; wraps the schema built above.
install_validation_error_openapi(app)
