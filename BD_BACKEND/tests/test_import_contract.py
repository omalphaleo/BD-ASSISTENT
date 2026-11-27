"""Contract test: every field key W2 reads from a row must exist in the W1 field registry.

Needed because the two workstreams meet only through SourceRow.values, whose keys are the
TARGET_FIELDS of leads/contracts.py (what the mapping step can produce). If W2's ingest code
reads a key the registry does not have, that value is silently never filled and no other test
notices. This reads W2's source without changing it and fails the moment the two drift.
"""

import ast
import inspect
from types import ModuleType

import pytest

from app.leads import quarantine, row_fields
from app.leads.contracts import TARGET_FIELDS_BY_KEY

# row_fields.py helpers that take (values, "key"): the second argument is a SourceRow key.
VALUE_READERS = frozenset({"_text", "_flag", "_integer", "_money", "_tags", "_moment"})
# Module-level constants that hold SourceRow keys, per module that defines them.
KEY_CONSTANTS = {
    row_fields: ("LAST_NAME_FIELD", "COMPANY_NAME_FIELD", "COMPANY_WEBSITE_FIELD"),
    quarantine: ("FIRST_NAME_FIELD", "EMAIL_STATUS_FIELD", "EMAIL_FIELDS"),
}


def _literal_keys_read(module: ModuleType) -> set[str]:
    """Keys passed as a string literal to a value reader, e.g. _text(values, "title")."""
    keys: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in VALUE_READERS
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            keys.add(node.args[1].value)
    return keys


def _constant_keys(module: ModuleType) -> set[str]:
    """Keys held by the module's named constants (a string or a tuple of strings)."""
    keys: set[str] = set()
    for name in KEY_CONSTANTS[module]:
        value = getattr(module, name)
        keys.update([value] if isinstance(value, str) else value)
    return keys


def test_the_scan_finds_keys_so_an_empty_result_cannot_pass_silently() -> None:
    """Sanity check: the scan sees many literal keys and the known constants (not vacuous)."""
    assert len(_literal_keys_read(row_fields)) > 15
    assert {"first_name", "email", "last_name"} <= _constant_keys(row_fields) | _constant_keys(
        quarantine
    )


# Known drift, agreed with the user (Decision 1): W2 wrote row_fields.py before the registry
# existed. strict=True makes this test FAIL as soon as B's fix lands, which is the signal to
# delete the marker, so the expected failure can never be forgotten.
ROW_FIELDS_DRIFT = pytest.mark.xfail(
    strict=True, reason="row_fields.py still reads keys the registry lacks; B updates it (M2-A7)"
)


@pytest.mark.parametrize("module", [pytest.param(row_fields, marks=ROW_FIELDS_DRIFT), quarantine])
def test_every_key_w2_reads_exists_in_the_field_registry(module: ModuleType) -> None:
    """A key read by W2 but missing from TARGET_FIELDS fails, naming it, so no data is dropped."""
    read = _constant_keys(module)
    if module is row_fields:
        read |= _literal_keys_read(module)

    missing = sorted(read - TARGET_FIELDS_BY_KEY.keys())

    assert missing == [], f"{module.__name__} reads keys the registry cannot produce: {missing}"
