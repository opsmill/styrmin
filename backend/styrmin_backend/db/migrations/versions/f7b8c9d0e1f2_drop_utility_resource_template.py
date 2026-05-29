"""drop utility.resource_template column

Revision ID: f7b8c9d0e1f2
Revises: e6a7b8c9d0e2
Create Date: 2026-05-29 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f7b8c9d0e1f2"
down_revision: Union[str, None] = "e6a7b8c9d0e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the dead ``resource_template`` column from ``utility``.

    The column was written at startup by ``services/utilities/utilities.py``
    from a Jinja template, but nothing in the codebase ever read it back.
    Ingress resources are rendered at deployment time from a separate
    template loaded by ``IngressUtility`` via a Jinja ``PackageLoader``
    (``agent/service/kubernetes/resources/utilities/``), bypassing the DB
    entirely.
    """
    op.drop_column("utility", "resource_template")


def downgrade() -> None:
    op.add_column(
        "utility",
        sa.Column(
            "resource_template",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="",
        ),
    )
