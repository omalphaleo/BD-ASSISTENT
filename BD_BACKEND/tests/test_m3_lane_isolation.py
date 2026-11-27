"""Guard test that the two M3 workstreams never import each other (M3-0).

Needed because M3 has no shared function (m3.md section 18): W1 (find and select leads) and W2
(lead records and compliance actions) meet only at database tables and URL paths. This reads
every file of each lane with the standard ast module and fails if one lane imports a module
owned by the other. No database is used.
"""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"

# Module names owned by each lane (m3.md section 17); a package entry covers everything inside.
W1_MODULES = {
    "app.leads.filters",
    "app.leads.search",
    "app.leads.segments",
    "app.leads.export",
    "app.leads.search_api",
    "app.leads.segments_api",
    "app.leads.search_schemas",
    "app.compliance.contracts",
    "app.compliance.eligibility",
    "app.ai",
}
W2_MODULES = {
    "app.leads.records",
    "app.leads.notes",
    "app.leads.flags",
    "app.leads.assignment",
    "app.leads.history",
    "app.leads.people_api",
    "app.leads.companies_api",
    "app.leads.record_schemas",
    "app.compliance.opt_outs",
    "app.compliance.opt_outs_api",
    "app.compliance.erasure",
    "app.compliance.compliance_schemas",
}


def _path_of(module: str) -> Path:
    """Return the file (or package folder) a dotted app.* module name refers to."""
    relative = Path(*module.split(".")[1:])
    folder = APP_DIR / relative
    return folder if folder.is_dir() else folder.with_suffix(".py")


def _files_of(modules: set[str]) -> list[Path]:
    """Return the existing Python files of a lane; modules not written yet are skipped."""
    files: list[Path] = []
    for module in sorted(modules):
        path = _path_of(module)
        if path.is_dir():
            files.extend(path.rglob("*.py"))
        elif path.exists():
            files.append(path)
    return files


def _imported_modules(path: Path) -> set[str]:
    """Return the full dotted names of every app.* module imported by a Python file."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
            modules.add(node.module)
            # "from app.leads import search" imports the module app.leads.search.
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            modules.update(a.name for a in node.names if a.name.startswith("app"))
    return modules


def _is_within(name: str, owned: set[str]) -> bool:
    """True when name is an owned module or something inside one (a symbol or submodule)."""
    return any(name == module or name.startswith(f"{module}.") for module in owned)


def _offenders(files: list[Path], forbidden: set[str]) -> list[str]:
    """List "file imports module" for every import of a forbidden module in the given files."""
    return [
        f"{path.name} imports {module}"
        for path in files
        for module in sorted(_imported_modules(path))
        if _is_within(module, forbidden)
    ]


def test_w1_files_do_not_import_w2_modules() -> None:
    """No search, segment, eligibility or AI file imports a W2 record or opt-out module."""
    assert not _offenders(_files_of(W1_MODULES), W2_MODULES)


def test_w2_files_do_not_import_w1_modules() -> None:
    """No record, opt-out or erase file imports a W1 search, eligibility or AI module."""
    assert not _offenders(_files_of(W2_MODULES), W1_MODULES)


def test_the_two_lane_lists_do_not_overlap() -> None:
    """No module is claimed by both lanes, so every file has one owner."""
    assert not W1_MODULES & W2_MODULES
