"""Audit package: the append-only audit log (model and record() service).

Needed so sensitive actions leave a tamper-resistant trail; it is a leaf module that any
other module may call and that itself imports only app.db and app.core.clock.
"""
