"""add env_vars JSON column to applicationdriverversion

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-05-06 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ``env_vars`` JSON column to ``applicationdriverversion``.

    Persists the doc-only :class:`DriverEnvVarDoc` declarations parsed from
    a driver's ``spec.env_vars`` block (008-deployment-env-vars / US4).
    The column is nullable; existing rows pre-dating the feature carry
    NULL and the GraphQL ``ApplicationDriverVersion.envVars`` resolver
    coerces NULL to an empty list.
    """
    op.add_column(
        "applicationdriverversion",
        sa.Column("env_vars", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("applicationdriverversion", "env_vars")
