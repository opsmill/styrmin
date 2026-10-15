"""merge the container overrides drop and environment backup index heads

Revision ID: 7948e6057857
Revises: 33b679d3d5dd, faf47e166160
Create Date: 2026-10-15 05:57:55.398286

33b679d3d5dd and faf47e166160 both revise 9548830f81cd, so `styrmin db
migrate` stopped at "Multiple head revisions are present". This revision
joins them and changes no schema.
"""

from typing import Sequence, Union

revision: str = "7948e6057857"
down_revision: Union[str, Sequence[str], None] = ("33b679d3d5dd", "faf47e166160")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
