"""add role and groups

Revision ID: c0d1e2f3a4b5
Revises: a1b2c3d4e5f7
Create Date: 2026-05-06 00:00:00.000000

The ``role`` enum has to be created exactly once. ``op.add_column`` does
not emit ``CREATE TYPE``, so the type must be created explicitly before
``user.role`` is added — but ``op.create_table`` *does* emit it (with
``checkfirst=False``), so a plain ``sa.Enum`` on ``group.role`` used to
issue a second ``CREATE TYPE role`` and abort with
``DuplicateObjectError``. On PostgreSQL the column type is therefore
``postgresql.ENUM(..., create_type=False)``, which references the
already-created type without redeclaring it. SQLite has no standalone
enum types (``sa.Enum`` renders as ``VARCHAR`` plus a CHECK constraint
per table), so it keeps the generic type and the explicit ``create`` is a
no-op there.
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ROLE_ENUM_NAME = "role"
_ROLE_VALUES = ("READ_ONLY", "READ_WRITE", "ADMIN")


def _role_enum() -> sa.Enum:
    """Return the dialect-agnostic ``role`` enum used to create/drop the type."""
    return sa.Enum(*_ROLE_VALUES, name=_ROLE_ENUM_NAME)


def _role_column_type(bind: Connection) -> sa.types.TypeEngine:
    """Return the column type for ``role``, never re-creating the enum type."""
    if bind.dialect.name == "postgresql":
        return postgresql.ENUM(*_ROLE_VALUES, name=_ROLE_ENUM_NAME, create_type=False)
    return _role_enum()


def upgrade() -> None:
    bind = op.get_bind()
    _role_enum().create(bind, checkfirst=True)

    with op.batch_alter_table("user") as batch:
        batch.add_column(
            sa.Column(
                "role",
                _role_column_type(bind),
                nullable=False,
                server_default="READ_ONLY",
            )
        )

    op.create_table(
        "group",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_on",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_on",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "role",
            _role_column_type(bind),
            nullable=False,
            server_default="READ_ONLY",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "user_group",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["group.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "group_id"),
    )


def downgrade() -> None:
    op.drop_table("user_group")
    op.drop_table("group")
    with op.batch_alter_table("user") as batch:
        batch.drop_column("role")
    _role_enum().drop(op.get_bind(), checkfirst=True)
