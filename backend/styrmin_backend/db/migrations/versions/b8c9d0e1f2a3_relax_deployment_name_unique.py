"""relax deployment name uniqueness to live rows

Drops the global UNIQUE constraint on deployment.name and replaces it
with a partial unique index scoped to rows where deleted_at IS NULL,
so tombstoned deployments no longer reserve their name.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-04-21 00:00:01.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "ix_deployment_name_live"
# Postgres auto-names the column-level UNIQUE on deployment.name as
# "deployment_name_key"; see 4586e6747b1d_initial_schema.py.
_LEGACY_CONSTRAINT_NAME = "deployment_name_key"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint(_LEGACY_CONSTRAINT_NAME, "deployment", type_="unique")
        op.execute(
            f"CREATE UNIQUE INDEX {_INDEX_NAME} ON deployment (name) "
            "WHERE deleted_at IS NULL"
        )
    else:
        # SQLite / dev path: use batch_alter_table to drop the legacy
        # constraint and add a dialect-aware partial index.
        with op.batch_alter_table("deployment") as batch_op:
            batch_op.drop_constraint(_LEGACY_CONSTRAINT_NAME, type_="unique")
        op.create_index(
            _INDEX_NAME,
            "deployment",
            ["name"],
            unique=True,
            sqlite_where=sa.text("deleted_at IS NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
        op.create_unique_constraint(_LEGACY_CONSTRAINT_NAME, "deployment", ["name"])
    else:
        op.drop_index(_INDEX_NAME, table_name="deployment")
        with op.batch_alter_table("deployment") as batch_op:
            batch_op.create_unique_constraint(_LEGACY_CONSTRAINT_NAME, ["name"])
