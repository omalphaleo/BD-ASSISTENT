"""The key under which each cell of an uploaded row is stored in raw_rows.original_values.

Needed because two places must agree on it: the pipeline writes the untouched row keyed by
header (D-099), and the owner assignment (M2-A4) later reads one column back by the same key.
Keeping the rule here means they cannot drift apart.
"""

from collections.abc import Sequence

# Used for a column whose header is empty or repeats an earlier header; the position is one-based.
POSITION_KEY_FORMAT = "column_{position}"


def original_value_keys(headers: Sequence[str], width: int) -> list[str]:
    """Return one key per column: the header, or "column_N" when it is empty or repeated.

    Args:
        headers: The header texts of the file, in column order (may be shorter than width).
        width: How many columns to produce keys for (a row can be wider than the header row).
    """
    seen: set[str] = set()
    keys: list[str] = []
    for index in range(width):
        header = headers[index] if index < len(headers) else ""
        if header and header not in seen:
            key = header
        else:
            key = POSITION_KEY_FORMAT.format(position=index + 1)
        seen.add(key)
        keys.append(key)
    return keys
