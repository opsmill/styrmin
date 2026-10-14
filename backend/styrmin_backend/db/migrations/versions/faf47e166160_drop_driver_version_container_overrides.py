"""drop applicationdriverversion container_overrides

Revision ID: faf47e166160
Revises: 9548830f81cd
Create Date: 2026-10-14 11:47:46.441109

Spec 022 (issue #457) removes ``spec.container_overrides`` from the driver
specification file: the component container now says which components accept a
``command`` or ``args`` override, so the stored copy of the block has no reader.
The downgrade restores an empty column; the dropped data is not recovered.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "faf47e166160"
down_revision: Union[str, Sequence[str], None] = "9548830f81cd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("applicationdriverversion", "container_overrides")


def downgrade() -> None:
    op.add_column(
        "applicationdriverversion",
        sa.Column("container_overrides", sa.JSON(), nullable=True),
    )
