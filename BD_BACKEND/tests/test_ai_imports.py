"""Guard test for who may import app.ai and the Gemini SDK (M3-A6).

Needed because the ai-adapter rule says only app/ai/gemini.py touches the provider SDK, and
ARCHITECTURE.md allows exactly one upward import: leads/search_api.py uses the NL search task
(main.py is frozen after M3-0, so the route cannot live in app/ai). Everything else under
app/ must stay clear of app.ai. Uses only the standard library ast module; no database.
"""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
# The only file outside app/ai allowed to import it, and the app.ai modules it may use.
LEADS_ROUTE_FILE = APP_DIR / "leads" / "search_api.py"
ROUTE_MAY_IMPORT = {"app.ai.nl_search", "app.ai.adapter"}
# The only file that may import the Gemini SDK.
SDK_FILE = APP_DIR / "ai" / "gemini.py"
SDK_PACKAGES = ("google.genai", "google")


def _imports(path: Path) -> set[str]:
    """Return every dotted module name a Python file imports (app.* and others)."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_only_the_nl_route_imports_app_ai_from_outside() -> None:
    """No file outside app/ai imports app.ai, except search_api.py and only nl_search/adapter."""
    offenders: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        if path.is_relative_to(APP_DIR / "ai"):
            continue
        for module in _imports(path):
            if module == "app.ai" or not module.startswith("app.ai."):
                continue
            # "from app.ai.adapter import X" also yields app.ai.adapter.X, so match by prefix.
            allowed = path == LEADS_ROUTE_FILE and any(
                module == ok or module.startswith(f"{ok}.") for ok in ROUTE_MAY_IMPORT
            )
            if not allowed:
                offenders.append(f"{path.relative_to(APP_DIR)} imports {module}")
    assert not offenders, offenders


def test_only_gemini_py_imports_the_sdk() -> None:
    """The google-genai SDK is imported by app/ai/gemini.py and by nothing else."""
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if path != SDK_FILE
        and any(m == "google" or m.startswith("google.") for m in _imports(path))
    ]
    assert not offenders, offenders
    assert any(m.startswith("google.genai") for m in _imports(SDK_FILE))
