"""FastAPI application entry point: creates the app and mounts the routers.

Needed as the single object uvicorn serves (app.main:app); each module's router is
included here, so this file only wires routes and holds no business logic.
"""

from fastapi import FastAPI

from app.core.api import router as core_router
from app.core.errors import install_validation_error_openapi, register_error_handlers
from app.core.permissions import install_permission_openapi

app = FastAPI(title="Alphaleo BD API", version="0.0.1")
# Error bodies must never echo submitted values such as passwords (FastAPI's default 422
# does), so validation errors go through our own handler.
register_error_handlers(app)
app.include_router(core_router)
# Adds the 401/403 responses of permission-guarded routes to the OpenAPI schema; runs after
# the routers are mounted because it reads each route's declared guard.
install_permission_openapi(app)
# Documents the narrowed 422 body our handler really returns; wraps the schema built above.
install_validation_error_openapi(app)
