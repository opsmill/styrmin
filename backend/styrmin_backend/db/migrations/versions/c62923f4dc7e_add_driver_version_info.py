"""add applicationdriverversion icon, description and links

Revision ID: c62923f4dc7e
Revises: 3b926acd0791
Create Date: 2026-10-08 00:00:00.000000

Spec 020 (issue #272) stores the driver specification file's ``spec.info.icon``,
``spec.info.description`` and ``spec.info.links`` on each driver version, so the
driver pages can show the application's logo, description and links.
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "c62923f4dc7e"
down_revision: Union[str, Sequence[str], None] = "3b926acd0791"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the three spec 020 columns.

    All three are nullable with no default, matching the model declarations
    (``icon: str | None``, ``description: str | None``, ``links: list | None``
    on a plain ``Column(JSON)``), so the adds are safe on a populated table:
    existing rows get NULL until the driver is loaded again.
    """
    op.add_column(
        "applicationdriverversion",
        sa.Column("icon", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "applicationdriverversion",
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "applicationdriverversion",
        sa.Column("links", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("applicationdriverversion", "links")
    op.drop_column("applicationdriverversion", "description")
    op.drop_column("applicationdriverversion", "icon")
