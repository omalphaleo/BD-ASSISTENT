"""Writes (or checks) the committed OpenAPI contract, BD_BACKEND/openapi.json.

Needed so the frontend generates its typed client from one stable file instead of a running
server (m1.md task A1); tests/test_openapi_export.py fails when the file is out of date, so
a changed endpoint can never silently break the generated client.

Usage (from BD_BACKEND/): `python -m app.export_openapi` writes the file;
`python -m app.export_openapi --check` exits 1 if the committed file is stale.
"""

import argparse
import json
import sys
from pathlib import Path

from app.main import app

OPENAPI_PATH = Path(__file__).resolve().parent.parent / "openapi.json"
JSON_INDENT = 2
STALE_EXIT_CODE = 1
REGENERATE_COMMAND = "python -m app.export_openapi"


def build_schema_text() -> str:
    """Render the app's OpenAPI schema as stable, reviewable JSON text.

    Keys are sorted and the indent is fixed so the same API always yields byte-identical
    output and Git diffs show only real contract changes.

    Returns:
        The schema as JSON ending in a single newline.
    """
    return json.dumps(app.openapi(), indent=JSON_INDENT, sort_keys=True) + "\n"


def is_up_to_date(path: Path = OPENAPI_PATH) -> bool:
    """Tell whether the file at `path` equals the schema generated from the current app.

    Args:
        path: The committed schema file to compare.

    Returns:
        True if the file exists and matches exactly; False if it is missing or different.
    """
    return path.is_file() and path.read_text(encoding="utf-8") == build_schema_text()


def main(argv: list[str] | None = None) -> int:
    """Write the schema file, or with --check only verify it.

    Args:
        argv: Command-line arguments; defaults to sys.argv[1:].

    Returns:
        0 on success; STALE_EXIT_CODE if --check finds the file missing or out of date.
    """
    parser = argparse.ArgumentParser(description="Write or check BD_BACKEND/openapi.json.")
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if the committed file is stale"
    )
    args = parser.parse_args(argv)

    if args.check:
        if is_up_to_date():
            return 0
        message = f"{OPENAPI_PATH.name} is stale or missing; run: {REGENERATE_COMMAND}"
        print(message, file=sys.stderr)
        return STALE_EXIT_CODE

    OPENAPI_PATH.write_text(build_schema_text(), encoding="utf-8")
    print(f"Wrote {OPENAPI_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
