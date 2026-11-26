"""Guard test for the leads/imports dependency rule recorded in ARCHITECTURE.md (M2-0).

Needed because M2's two workstreams import each other in a controlled way: app/leads may use
only the data classes of app.imports.models, while app.imports may use app.leads.contracts and
(in wiring.py only) app.leads.ingest. Without a check, a stray import could create a cycle.
Uses only the standard library ast module; no database.
"""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
# The only app.imports module the leads package may import.
LEADS_MAY_IMPORT_FROM_IMPORTS = "app.imports.models"
# imports may use leads.contracts everywhere, and leads.ingest only in wiring.py.
IMPORTS_MAY_IMPORT_FROM_LEADS = {"app.leads.contracts", "app.leads.models"}
WIRING_FILE = "wiring.py"
WIRING_EXTRA_ALLOWED = "app.leads.ingest"


def _imported_modules(path: Path) -> set[str]:
    """Return the full dotted names of every app.* module imported by a Python file."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            modules.add(node.module)
            # "from app.imports import models" imports the module app.imports.models.
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            modules.update(a.name for a in node.names if a.name.startswith("app."))
    return modules


def _is_within(name: str, allowed: set[str]) -> bool:
    """True when name is an allowed module or something inside one (a symbol or submodule)."""
    return any(name == module or name.startswith(f"{module}.") for module in allowed)


def test_leads_imports_only_the_imports_models_module() -> None:
    """No app/leads file imports anything from app.imports except app.imports.models."""
    offenders: list[str] = []
    for path in (APP_DIR / "leads").glob("*.py"):
        for module in _imported_modules(path):
            # The bare package name appears for "from app.imports import models"; it is fine.
            if (
                module.startswith("app.imports")
                and module != "app.imports"
                and not _is_within(module, {LEADS_MAY_IMPORT_FROM_IMPORTS})
            ):
                offenders.append(f"{path.name} imports {module}")
    assert not offenders, offenders


def test_imports_reaches_leads_only_through_the_contract_and_wiring() -> None:
    """app/imports uses leads.contracts and leads.models; only wiring.py may use leads.ingest."""
    offenders: list[str] = []
    for path in (APP_DIR / "imports").glob("*.py"):
        allowed = set(IMPORTS_MAY_IMPORT_FROM_LEADS)
        if path.name == WIRING_FILE:
            allowed.add(WIRING_EXTRA_ALLOWED)
        for module in _imported_modules(path):
            if (
                module.startswith("app.leads")
                and module != "app.leads"
                and not _is_within(module, allowed)
            ):
                offenders.append(f"{path.name} imports {module}")
    assert not offenders, offenders
