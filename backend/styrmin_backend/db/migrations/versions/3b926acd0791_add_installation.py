"""add installation

Revision ID: 3b926acd0791
Revises: 69b12221e5df
Create Date: 2026-10-08 22:30:54.674391

The ``installation`` table holds the install ID that the daily telemetry report
carries (spec 020, issue #274). ``ck_installation_single_row`` keeps it to one
row with ``id = 1``. The revision creates no row; the server inserts it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3b926acd0791"
down_revision: Union[str, Sequence[str], None] = "69b12221e5df"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "installation",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("install_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_on",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_installation_single_row"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("installation")
