"""merge the backup size and dedicated ingress heads

Revision ID: 69b12221e5df
Revises: c2ff6dba5ffd, f3a4b5c6d7e8
Create Date: 2026-10-09 07:07:46.985166

c2ff6dba5ffd and f3a4b5c6d7e8 both revise e2f3a4b5c6d7, so `styrmin db
migrate` stopped at "Multiple head revisions are present". This revision
joins them and changes no schema.
"""

from typing import Sequence, Union

revision: str = "69b12221e5df"
down_revision: Union[str, Sequence[str], None] = ("c2ff6dba5ffd", "f3a4b5c6d7e8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
