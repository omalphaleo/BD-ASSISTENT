"""Procrastinate app for the background worker process (M1: only the core sample job).

Needed so the PostgreSQL-backed job queue has an app object to run; the `worker` service
in docker-compose.yml applies the queue schema and then starts this app. Task modules are
listed in import_paths (currently app.core.tasks).

Start with:        procrastinate --app=app.worker.app worker
Apply queue schema: procrastinate --app=app.worker.app schema --apply
"""

import procrastinate

from app.config import get_settings

# get_settings() runs at import time, so the worker also fails fast without DATABASE_URL.
# Procrastinate needs a plain libpq URL, hence psycopg_conninfo instead of database_url.
# import_paths makes the worker import each tasks module so its tasks get registered. It is
# used instead of importing them here because tasks modules import `app` from this file.
app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().psycopg_conninfo),
    import_paths=["app.core.tasks"],
)
