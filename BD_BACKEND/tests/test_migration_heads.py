"""Test that the Alembic revision history has exactly one head.

Needed because two developers add migrations in parallel (m1.md section 15, rule 4); a fork
in the chain would break `alembic upgrade head`, so this fails the build instead.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_alembic_has_single_head() -> None:
    """The migrations folder has one head revision; a forked chain fails this test."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"Alembic has multiple heads: {heads}"
