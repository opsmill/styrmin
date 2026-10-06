"""widen backup.size_bytes to bigint

Revision ID: c2ff6dba5ffd
Revises: e2f3a4b5c6d7
Create Date: 2026-10-08 12:00:00.000000

``backup.size_bytes`` now records the bytes of volume data a backup read
(issue #136). A 32-bit INTEGER overflows at 2 GiB, so the column becomes
BIGINT. Widening keeps every existing value.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2ff6dba5ffd"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("backup") as batch:
        batch.alter_column(
            "size_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )


def downgrade() -> None:
    # Fails on PostgreSQL if a stored value no longer fits in INTEGER.
    with op.batch_alter_table("backup") as batch:
        batch.alter_column(
            "size_bytes",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
