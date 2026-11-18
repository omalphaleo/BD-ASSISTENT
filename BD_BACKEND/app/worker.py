"""Procrastinate app for the background worker process (M1 no-op: no tasks registered yet).

Needed so the PostgreSQL-backed job queue has an app object to run; the `worker` service
in docker-compose.yml applies the queue schema and then starts this app.

Start with:        procrastinate --app=app.worker.app worker
Apply queue schema: procrastinate --app=app.worker.app schema --apply
"""

import procrastinate

from app.config import get_settings

# get_settings() runs at import time, so the worker also fails fast without DATABASE_URL.
# Procrastinate needs a plain libpq URL, hence psycopg_conninfo instead of database_url.
app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().psycopg_conninfo),
)
