"""index the environment backup and restore links

Revision ID: 33b679d3d5dd
Revises: 9548830f81cd
Create Date: 2026-10-14 00:00:00.000000

The environment-level concurrency guard filters on the four foreign key columns
that ``c1d2e3f4a5b6`` added without an index (#455). PostgreSQL does not index
a foreign key column on its own, and ``backup`` and ``restore`` grow with every
deployment backup and restore, not only with environment-level ones.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "33b679d3d5dd"
down_revision: Union[str, Sequence[str], None] = "9548830f81cd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_environmentbackup_environment_id", "environmentbackup", ["environment_id"]
    )
    op.create_index(
        "ix_environmentrestore_environment_backup_id",
        "environmentrestore",
        ["environment_backup_id"],
    )
    op.create_index(
        "ix_backup_environment_backup_id", "backup", ["environment_backup_id"]
    )
    op.create_index(
        "ix_restore_environment_restore_id", "restore", ["environment_restore_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_restore_environment_restore_id", table_name="restore")
    op.drop_index("ix_backup_environment_backup_id", table_name="backup")
    op.drop_index(
        "ix_environmentrestore_environment_backup_id", table_name="environmentrestore"
    )
    op.drop_index("ix_environmentbackup_environment_id", table_name="environmentbackup")
