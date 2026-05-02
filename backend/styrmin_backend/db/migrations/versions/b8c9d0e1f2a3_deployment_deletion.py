"""deployment deletion: deleted_at column + DELETING/DELETED states + DELETE_DEPLOYMENT task type

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2, a7b8c9d0e1f3
Create Date: 2026-05-01 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = ("a7b8c9d0e1f2", "a7b8c9d0e1f3")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "deployment",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_deployment_deleted_at",
        "deployment",
        ["deleted_at"],
    )

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE deploymentstate ADD VALUE IF NOT EXISTS 'DELETING'")
        op.execute("ALTER TYPE deploymentstate ADD VALUE IF NOT EXISTS 'DELETED'")
        op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'DELETE_DEPLOYMENT'")
    else:
        # SQLite (test harness) — recreate the columns with the expanded enums.
        with op.batch_alter_table("deployment") as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=sa.Enum(
                    "PENDING",
                    "DEPLOYING",
                    "RUNNING",
                    "RESTORING",
                    "FAILED",
                    name="deploymentstate",
                ),
                type_=sa.Enum(
                    "PENDING",
                    "DEPLOYING",
                    "RUNNING",
                    "RESTORING",
                    "FAILED",
                    "DELETING",
                    "DELETED",
                    name="deploymentstate",
                ),
                existing_nullable=False,
            )
        with op.batch_alter_table("task") as batch_op:
            batch_op.alter_column(
                "type",
                existing_type=sa.Enum(
                    "NOOP",
                    "CREATE_INSTANCE",
                    "DELETE_INSTANCE",
                    "UPDATE_INSTANCE",
                    "UPGRADE_INSTANCE",
                    "STOP_COMPONENTS",
                    "START_COMPONENTS",
                    "RUN_JOB",
                    name="tasktype",
                ),
                type_=sa.Enum(
                    "NOOP",
                    "CREATE_INSTANCE",
                    "DELETE_INSTANCE",
                    "UPDATE_INSTANCE",
                    "UPGRADE_INSTANCE",
                    "STOP_COMPONENTS",
                    "START_COMPONENTS",
                    "RUN_JOB",
                    "DELETE_DEPLOYMENT",
                    name="tasktype",
                ),
                existing_nullable=False,
            )


def downgrade() -> None:
    op.drop_index("ix_deployment_deleted_at", table_name="deployment")
    op.drop_column("deployment", "deleted_at")
    # Postgres ALTER TYPE ADD VALUE has no reversal. Downgrade leaves the
    # enum values in place; they are safe no-ops on rows that never used them.
