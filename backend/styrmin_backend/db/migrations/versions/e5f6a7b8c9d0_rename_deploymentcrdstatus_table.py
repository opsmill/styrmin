"""rename deploymentcrdstatus table to deploymentstatus

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-19 00:00:01.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("deploymentcrdstatus", "deploymentstatus")


def downgrade() -> None:
    op.rename_table("deploymentstatus", "deploymentcrdstatus")
