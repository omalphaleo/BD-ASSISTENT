"""FastAPI application entry point: creates the app and mounts the routers.

Needed as the single object uvicorn serves (app.main:app); each module's router is
included here, so this file only wires routes and holds no business logic.
"""

from fastapi import FastAPI

from app.core.api import router as core_router
from app.core.errors import register_error_handlers

app = FastAPI(title="Alphaleo BD API", version="0.0.1")
# Error bodies must never echo submitted values such as passwords (FastAPI's default 422
# does), so validation errors go through our own handler.
register_error_handlers(app)
app.include_router(core_router)
