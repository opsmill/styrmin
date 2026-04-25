"""add RESTORING to deploymentstate enum

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-25 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_VALUES = ("PENDING", "DEPLOYING", "RUNNING", "FAILED")
_NEW_VALUES = ("PENDING", "DEPLOYING", "RUNNING", "RESTORING", "FAILED")
_ENUM_NAME = "deploymentstate"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"ALTER TYPE {_ENUM_NAME} ADD VALUE IF NOT EXISTS 'RESTORING'")
    else:
        with op.batch_alter_table("deployment") as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=sa.Enum(*_OLD_VALUES, name=_ENUM_NAME),
                type_=sa.Enum(*_NEW_VALUES, name=_ENUM_NAME),
                existing_nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Postgres does not support removing enum values without recreating
        # the type. Rebuild the type to drop RESTORING.
        op.execute(f"ALTER TYPE {_ENUM_NAME} RENAME TO {_ENUM_NAME}_old")
        op.execute(
            f"CREATE TYPE {_ENUM_NAME} AS ENUM "
            "('PENDING', 'DEPLOYING', 'RUNNING', 'FAILED')"
        )
        op.execute(
            f"ALTER TABLE deployment ALTER COLUMN status TYPE {_ENUM_NAME} "
            f"USING status::text::{_ENUM_NAME}"
        )
        op.execute(f"DROP TYPE {_ENUM_NAME}_old")
    else:
        with op.batch_alter_table("deployment") as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=sa.Enum(*_NEW_VALUES, name=_ENUM_NAME),
                type_=sa.Enum(*_OLD_VALUES, name=_ENUM_NAME),
                existing_nullable=False,
            )
