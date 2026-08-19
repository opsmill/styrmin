"""add environmentclone table

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-08-19 14:20:19.988688

Environment clone (issue #6). Adds the single ``environmentclone`` record that
tracks one clone operation end to end: the capture it is built from, the
environment it created, the selection/override it was asked for, the
per-source-deployment attribution list and the operation-level error entries.

The table has **no status column** — the clone's status is derived at read time
from the backing capture, ``created_environment_id``, the constituent restore
rows reachable through ``deployment_results[].restore_id`` and ``clone_errors``
(see ``services/backup/clone.py``). So **no new PostgreSQL enum types are
created here** and the enum ceremony documented in
``dev/guides/database-migrations.md`` does not apply.

Everything the clone points at is a *nullable* foreign key, because the record
is provenance that has to outlive its referents:

* ``source_environment_id`` — nulled when the source environment is deleted.
* ``environment_backup_id`` — nulled when the capture is cleaned up (TTL).
* ``created_environment_id`` — nulled when the created environment is
  discarded. This is the one FK that carries ``ON DELETE SET NULL`` as a
  belt-and-braces backstop; the app-level cascade is authoritative because it
  also writes the ``clone_errors`` marker the derivation keys on.
* ``created_by_user_id`` — nullable, unlike ``deployment.created_by_user_id``,
  so a clone record survives user deletion.

``name`` deliberately carries **no unique constraint**: a failed clone must not
block re-cloning under the same name (SC-005). Uniqueness of the target
environment name stays on ``environment (name, cluster_id)``.

Every foreign key is created with the name PostgreSQL would derive for it
(``<table>_<column>_fkey``), so one canonical name identifies each constraint on
both backends — a database built by ``metadata.create_all()`` on PostgreSQL and
one built by this revision agree, and ``op.batch_alter_table`` (which refuses
unnamed constraints on SQLite) can target them by name in any later revision.

``environmentclone`` is created after ``environment``, ``environmentbackup`` and
``user`` already exist, so PostgreSQL accepts every ``REFERENCES`` clause;
``downgrade`` drops the table, which takes its constraints with it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "environmentclone",
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
        sa.Column("source_environment_id", sa.Uuid(), nullable=True),
        sa.Column(
            "source_environment_name",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
        ),
        sa.Column("environment_backup_id", sa.Uuid(), nullable=True),
        sa.Column("created_environment_id", sa.Uuid(), nullable=True),
        sa.Column("requested_deployment_ids", sa.JSON(), nullable=True),
        sa.Column("config_override", sa.JSON(), nullable=True),
        sa.Column("cleared_config_fields", sa.JSON(), nullable=True),
        sa.Column("deployment_results", sa.JSON(), nullable=True),
        sa.Column("clone_errors", sa.JSON(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_environment_id"],
            ["environment.id"],
            name="environmentclone_source_environment_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["environment_backup_id"],
            ["environmentbackup.id"],
            name="environmentclone_environment_backup_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["created_environment_id"],
            ["environment.id"],
            name="environmentclone_created_environment_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user.id"],
            name="environmentclone_created_by_user_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("environmentclone")
