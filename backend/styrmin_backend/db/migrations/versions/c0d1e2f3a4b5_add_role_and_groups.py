"""add role and groups

Revision ID: c0d1e2f3a4b5
Revises: a1b2c3d4e5f7
Create Date: 2026-05-06 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ROLE_ENUM = sa.Enum("READ_ONLY", "READ_WRITE", "ADMIN", name="role")


def upgrade() -> None:
    _ROLE_ENUM.create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table("user") as batch:
        batch.add_column(
            sa.Column(
                "role",
                _ROLE_ENUM,
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
        sa.Column("role", _ROLE_ENUM, nullable=False, server_default="READ_ONLY"),
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
    _ROLE_ENUM.drop(op.get_bind(), checkfirst=True)
