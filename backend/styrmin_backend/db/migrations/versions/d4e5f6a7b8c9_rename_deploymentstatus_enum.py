"""rename deploymentstatus enum to deploymentstate

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-19 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_VALUES = ("PENDING", "DEPLOYING", "RUNNING", "FAILED")
_OLD_NAME = "deploymentstatus"
_NEW_NAME = "deploymentstate"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"ALTER TYPE {_OLD_NAME} RENAME TO {_NEW_NAME}")
    else:
        with op.batch_alter_table("deployment") as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=sa.Enum(*_VALUES, name=_OLD_NAME),
                type_=sa.Enum(*_VALUES, name=_NEW_NAME),
                existing_nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"ALTER TYPE {_NEW_NAME} RENAME TO {_OLD_NAME}")
    else:
        with op.batch_alter_table("deployment") as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=sa.Enum(*_VALUES, name=_NEW_NAME),
                type_=sa.Enum(*_VALUES, name=_OLD_NAME),
                existing_nullable=False,
            )
