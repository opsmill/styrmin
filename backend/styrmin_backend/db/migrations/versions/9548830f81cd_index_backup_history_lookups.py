"""index the backup history lookups

Revision ID: 9548830f81cd
Revises: 7af6824e820d
Create Date: 2026-10-12 00:00:00.000000

The Backups tab lists a deployment's backups, then each backup's restores,
every 10 seconds (#427). ``backup.instance_id`` and ``restore.backup_id`` had
no index, and PostgreSQL does not index a foreign key column on its own.
``applicationinstance.deployment_id`` needs no index of its own: the index of
``uq_applicationinstance_deployment_sequence`` leads with it.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "9548830f81cd"
down_revision: Union[str, Sequence[str], None] = "7af6824e820d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_backup_instance_id", "backup", ["instance_id"])
    op.create_index("ix_restore_backup_id", "restore", ["backup_id"])


def downgrade() -> None:
    op.drop_index("ix_restore_backup_id", table_name="restore")
    op.drop_index("ix_backup_instance_id", table_name="backup")
