"""Tests for the OpenAPI export: committed file freshness, content and determinism.

Needed because the frontend client is generated from BD_BACKEND/openapi.json (m1.md task A1);
a stale file must fail the build instead of breaking the client later. No database is used:
building the schema only inspects the routes.
"""

import json
from pathlib import Path

from app.export_openapi import (
    OPENAPI_PATH,
    REGENERATE_COMMAND,
    build_schema_text,
    is_up_to_date,
    main,
)

EXPECTED_PATHS = {"/health", "/auth/login", "/auth/logout", "/auth/me"}


def test_committed_openapi_matches_the_app() -> None:
    """The committed openapi.json equals the generated schema; a stale file fails with the fix."""
    assert is_up_to_date(), f"openapi.json is stale or missing; run: {REGENERATE_COMMAND}"


def test_schema_lists_the_current_endpoints() -> None:
    """The generated schema is valid JSON and documents /health and the three /auth routes."""
    schema = json.loads(build_schema_text())
    assert EXPECTED_PATHS <= set(schema["paths"])


def test_schema_text_is_deterministic() -> None:
    """Two generations are byte-identical and end with one newline, so diffs stay stable."""
    first = build_schema_text()
    assert first == build_schema_text()
    assert first.endswith("}\n")


def test_is_up_to_date_detects_missing_and_changed_files(tmp_path: Path) -> None:
    """A missing file and a different file are both reported as stale."""
    assert not is_up_to_date(tmp_path / "missing.json")
    changed = tmp_path / "openapi.json"
    changed.write_text("{}\n", encoding="utf-8")
    assert not is_up_to_date(changed)


def test_main_check_succeeds_on_the_committed_file() -> None:
    """`--check` returns 0 when the committed file is current and never rewrites it."""
    before = OPENAPI_PATH.read_text(encoding="utf-8")
    assert main(["--check"]) == 0
    assert OPENAPI_PATH.read_text(encoding="utf-8") == before
