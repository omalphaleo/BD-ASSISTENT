"""Procrastinate app for the worker process. No tasks are registered yet (M1 no-op worker).

Start with:        procrastinate --app=app.worker.app worker
Apply queue schema: procrastinate --app=app.worker.app schema --apply
"""

import procrastinate

from app.config import get_settings

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().psycopg_conninfo),
)
