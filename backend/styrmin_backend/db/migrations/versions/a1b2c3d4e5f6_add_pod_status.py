"""add pod status

Revision ID: a1b2c3d4e5f6
Revises: 4586e6747b1d
Create Date: 2026-04-12 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "4586e6747b1d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Enum type created implicitly by ``CREATE TABLE podstatus``. ``op.drop_table``
#: builds a bare ``Table`` with no columns, so it never emits the matching
#: ``DROP TYPE``; leaving the type behind makes the next upgrade fail with
#: ``DuplicateObjectError``. ``Enum.drop`` is a no-op on SQLite, which has no
#: standalone enum types.
_POD_PHASE_ENUM = sa.Enum(
    "PENDING", "RUNNING", "SUCCEEDED", "FAILED", "UNKNOWN", name="podphase"
)


def upgrade() -> None:
    op.create_table(
        "podstatus",
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
        sa.Column("pod_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("namespace", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "phase",
            sa.Enum(
                "PENDING", "RUNNING", "SUCCEEDED", "FAILED", "UNKNOWN", name="podphase"
            ),
            nullable=False,
        ),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.Column("restart_count", sa.Integer(), nullable=False),
        sa.Column("container_statuses", sa.JSON(), nullable=True),
        sa.Column("node_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_polled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("deployment_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["deployment.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deployment_id", "pod_name"),
    )


def downgrade() -> None:
    op.drop_table("podstatus")
    _POD_PHASE_ENUM.drop(op.get_bind(), checkfirst=True)
