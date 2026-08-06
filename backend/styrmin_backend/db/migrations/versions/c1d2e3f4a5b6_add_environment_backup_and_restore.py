"""add environmentbackup and environmentrestore tables

Revision ID: c1d2e3f4a5b6
Revises: b9c0d1e2f3a4
Create Date: 2026-08-06 00:00:00.000000

Environment-level backup and restore (issue #7). Adds the two parent records
that group per-instance constituents:

* ``environmentbackup`` — captured environment config, per-deployment declared
  state and per-constituent creation errors, all as JSON.
* ``environmentrestore`` — the classified skip list for one coordinated
  in-place restore, as JSON.

Neither table has a status column: the parent status is derived at read time
from the constituent rows (see ``services/backup/environment.py``), so **no new
PostgreSQL enum types are created here** and the enum ceremony documented in
``dev/guides/database-migrations.md`` does not apply.

The constituents are linked by two new *nullable* foreign keys —
``backup.environment_backup_id`` and ``restore.environment_restore_id`` —
mirroring the existing ``backup.schedule_id`` precedent: null means the
backup/restore is a standalone per-instance operation.

Tables are created in FK-dependency order (``environmentbackup`` references
``environment``; ``environmentrestore`` references ``environmentbackup``) so
PostgreSQL accepts the ``REFERENCES`` clauses. The two ``ADD COLUMN`` steps run
inside ``op.batch_alter_table`` with explicitly named constraints so SQLite
(which cannot ``ALTER TABLE ... ADD CONSTRAINT``) rebuilds the table instead,
and so ``downgrade`` can drop the constraints by name on both backends.
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BACKUP_FK = "fk_backup_environment_backup_id_environmentbackup"
RESTORE_FK = "fk_restore_environment_restore_id_environmentrestore"


def upgrade() -> None:
    op.create_table(
        "environmentbackup",
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
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("environment_config", sa.JSON(), nullable=True),
        sa.Column("deployment_snapshots", sa.JSON(), nullable=True),
        sa.Column("constituent_errors", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "environmentrestore",
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
        sa.Column("environment_backup_id", sa.Uuid(), nullable=False),
        sa.Column("skipped_constituents", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["environment_backup_id"], ["environmentbackup.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("backup") as batch:
        batch.add_column(sa.Column("environment_backup_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            BACKUP_FK,
            "environmentbackup",
            ["environment_backup_id"],
            ["id"],
        )

    with op.batch_alter_table("restore") as batch:
        batch.add_column(sa.Column("environment_restore_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            RESTORE_FK,
            "environmentrestore",
            ["environment_restore_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("restore") as batch:
        batch.drop_constraint(RESTORE_FK, type_="foreignkey")
        batch.drop_column("environment_restore_id")

    with op.batch_alter_table("backup") as batch:
        batch.drop_constraint(BACKUP_FK, type_="foreignkey")
        batch.drop_column("environment_backup_id")

    op.drop_table("environmentrestore")
    op.drop_table("environmentbackup")
