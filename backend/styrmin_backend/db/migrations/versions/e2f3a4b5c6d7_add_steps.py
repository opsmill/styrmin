"""add steps

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-06 12:30:00.000000

Steps for tasks, backups and restores (spec 019, issue #2): the ``step`` table,
``task.instance_id`` and ``task.started_by_step_id``.

``step.task_id`` and ``task.started_by_step_id`` reference each other, so
``step`` is created first and the ``task`` foreign key is added afterwards; the
downgrade removes the ``task`` columns before it drops ``step``. The enum types
are created once up front and dropped explicitly, as in ``c0d1e2f3a4b5``.
``ck_step_one_parent`` uses ``CASE`` instead of ``num_nonnulls`` for SQLite.
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STEP_STATUS = (
    "stepstatus",
    ("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "SUPERSEDED"),
)
_STEP_KIND = (
    "stepkind",
    (
        "PLAN",
        "HOOK",
        "RESOURCE_WRITE",
        "OPERATOR_PHASE",
        "COMMAND",
        "RESTORE",
        "BACKUP_COMPONENT",
    ),
)

#: Mirrors ``STEP_ONE_PARENT_CHECK`` in ``db/models.py``.
_ONE_PARENT_CHECK = (
    "(CASE WHEN task_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN backup_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN restore_id IS NULL THEN 0 ELSE 1 END) = 1"
)

_PARENT_COLUMNS = ("task_id", "backup_id", "restore_id")

_TASK_INSTANCE_FK = "task_instance_id_fkey"
_TASK_STARTED_BY_STEP_FK = "task_started_by_step_id_fkey"


def _enum(spec: tuple[str, tuple[str, ...]]) -> sa.Enum:
    name, values = spec
    return sa.Enum(*values, name=name)


def _enum_column_type(
    bind: Connection, spec: tuple[str, tuple[str, ...]]
) -> sa.types.TypeEngine:
    """Return the column type for an enum without re-creating the type."""
    if bind.dialect.name == "postgresql":
        name, values = spec
        return postgresql.ENUM(*values, name=name, create_type=False)
    return _enum(spec)


def upgrade() -> None:
    bind = op.get_bind()
    _enum(_STEP_STATUS).create(bind, checkfirst=True)
    _enum(_STEP_KIND).create(bind, checkfirst=True)

    op.create_table(
        "step",
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
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("backup_id", sa.Uuid(), nullable=True),
        sa.Column("restore_id", sa.Uuid(), nullable=True),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("kind", _enum_column_type(bind, _STEP_KIND), nullable=False),
        sa.Column("status", _enum_column_type(bind, _STEP_STATUS), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.Column("detail", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "rollback_message", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column(
            "output_truncated",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("superseded_by_task_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(_ONE_PARENT_CHECK, name="ck_step_one_parent"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name="step_task_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["backup_id"],
            ["backup.id"],
            name="step_backup_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["restore_id"],
            ["restore.id"],
            name="step_restore_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_task_id"],
            ["task.id"],
            name="step_superseded_by_task_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in _PARENT_COLUMNS:
        predicate = sa.text(f"{column} IS NOT NULL")
        op.create_index(
            f"uq_step_{column}_key",
            "step",
            [column, "key"],
            unique=True,
            postgresql_where=predicate,
            sqlite_where=predicate,
        )
    op.create_index("ix_step_superseded_by_task_id", "step", ["superseded_by_task_id"])

    with op.batch_alter_table("task") as batch_op:
        batch_op.add_column(sa.Column("instance_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("started_by_step_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            _TASK_INSTANCE_FK,
            "applicationinstance",
            ["instance_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            _TASK_STARTED_BY_STEP_FK,
            "step",
            ["started_by_step_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_task_instance_id", ["instance_id"])
        batch_op.create_index("ix_task_started_by_step_id", ["started_by_step_id"])


def downgrade() -> None:
    # Break the task <-> step cycle before dropping ``step``.
    with op.batch_alter_table("task") as batch_op:
        batch_op.drop_index("ix_task_started_by_step_id")
        batch_op.drop_index("ix_task_instance_id")
        batch_op.drop_constraint(_TASK_STARTED_BY_STEP_FK, type_="foreignkey")
        batch_op.drop_constraint(_TASK_INSTANCE_FK, type_="foreignkey")
        batch_op.drop_column("started_by_step_id")
        batch_op.drop_column("instance_id")

    op.drop_index("ix_step_superseded_by_task_id", table_name="step")
    for column in _PARENT_COLUMNS:
        op.drop_index(f"uq_step_{column}_key", table_name="step")
    op.drop_table("step")

    bind = op.get_bind()
    _enum(_STEP_KIND).drop(bind, checkfirst=True)
    _enum(_STEP_STATUS).drop(bind, checkfirst=True)
