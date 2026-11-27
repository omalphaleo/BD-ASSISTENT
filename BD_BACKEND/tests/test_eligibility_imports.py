"""Guard test for the compliance/leads import link recorded in ARCHITECTURE.md (M3-A1).

Needed because eligibility (compliance) reads lead tables while search (leads) calls the
eligibility service, so the two packages import each other in a controlled way. Without a check
a stray import could create a cycle. Uses only the standard library ast module; no database.
"""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
# compliance may use only these leads modules (data classes, and the cooling-off reader).
COMPLIANCE_MAY_IMPORT_FROM_LEADS = {"app.leads.models", "app.leads.engagement"}
# leads may use only these compliance modules.
LEADS_MAY_IMPORT_FROM_COMPLIANCE = {
    "app.compliance.models",
    "app.compliance.contracts",
    "app.compliance.eligibility",
}


def _imported_modules(path: Path) -> set[str]:
    """Return the full dotted names of every app.* module imported by a Python file."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            modules.update(a.name for a in node.names if a.name.startswith("app."))
    return modules


def _offenders(folder: str, other: str, allowed: set[str]) -> list[str]:
    """List imports in app/<folder> of app.<other> modules outside the allowed set."""
    found: list[str] = []
    for path in (APP_DIR / folder).glob("*.py"):
        for module in _imported_modules(path):
            if module == f"app.{other}" or not module.startswith(f"app.{other}."):
                continue
            if not any(module == ok or module.startswith(f"{ok}.") for ok in allowed):
                found.append(f"{path.name} imports {module}")
    return found


def test_compliance_imports_only_allowed_leads_modules() -> None:
    """No app/compliance file imports a leads module other than models and engagement."""
    assert not _offenders("compliance", "leads", COMPLIANCE_MAY_IMPORT_FROM_LEADS)


def test_leads_imports_only_allowed_compliance_modules() -> None:
    """No app/leads file imports a compliance module other than models, contracts, eligibility."""
    assert not _offenders("leads", "compliance", LEADS_MAY_IMPORT_FROM_COMPLIANCE)
