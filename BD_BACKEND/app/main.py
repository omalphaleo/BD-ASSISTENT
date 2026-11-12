"""FastAPI application entry point."""

from fastapi import FastAPI

from app.core.api import router as core_router

app = FastAPI(title="Alphaleo BD API", version="0.0.1")
app.include_router(core_router)
