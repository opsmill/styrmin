"""merge the backup size and cluster dedicated ingress heads

Revision ID: b85a36badfc6
Revises: c2ff6dba5ffd, f3a4b5c6d7e8
Create Date: 2026-10-09 07:07:34.752465

c2ff6dba5ffd and f3a4b5c6d7e8 both follow e2f3a4b5c6d7, so ``styrmin db
migrate`` failed with "Multiple head revisions". They change unrelated tables,
so this merge has no schema changes of its own.
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "b85a36badfc6"
down_revision: Union[str, Sequence[str], None] = ("c2ff6dba5ffd", "f3a4b5c6d7e8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
