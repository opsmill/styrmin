"""The migration chain must end in one head, or `styrmin db migrate` fails."""

from alembic.script import ScriptDirectory

from styrmin_backend.cli.db import _get_alembic_config


def test_migrations_have_a_single_head() -> None:
    heads = ScriptDirectory.from_config(_get_alembic_config()).get_heads()
    assert len(heads) == 1, (
        f"migration heads {sorted(heads)}: add a merge revision, see "
        "dev/guides/database-migrations.md#multi-head-resolution"
    )
