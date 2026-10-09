"""The Alembic revision chain must end in exactly one head."""

from alembic.script import ScriptDirectory

from styrmin_backend.cli.db import _get_alembic_config


def test_migrations_have_a_single_head() -> None:
    """``styrmin db init`` and ``styrmin db migrate`` target ``head`` and fail on two.

    Two branches that each add a revision on the same parent leave two heads
    once both are merged; join them with a merge revision
    (see dev/guides/database-migrations.md).
    """
    heads = ScriptDirectory.from_config(_get_alembic_config()).get_heads()
    assert len(heads) == 1, f"Alembic has several heads: {sorted(heads)}"
