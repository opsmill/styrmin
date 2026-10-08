"""number each deployment's instances in the order they were created

Revision ID: 7af6824e820d
Revises: c62923f4dc7e
Create Date: 2026-10-10 00:00:00.000000

The flows write the StyrminDeployment with ``applicationinstance.sequence``,
and a flow leaves a StyrminDeployment that holds a higher sequence unchanged
(#386). ``deployment.last_instance_sequence`` is the counter that the
repository increments, under the deployment row lock, for each new instance.

Existing instances are numbered by ``created_on``, then ``id``.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "7af6824e820d"
down_revision: Union[str, Sequence[str], None] = "c62923f4dc7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNIQUE_SEQUENCE = "uq_applicationinstance_deployment_sequence"


def upgrade() -> None:
    with op.batch_alter_table("applicationinstance") as batch:
        batch.add_column(sa.Column("sequence", sa.Integer(), nullable=True))
    with op.batch_alter_table("deployment") as batch:
        batch.add_column(
            sa.Column(
                "last_instance_sequence",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )

    op.execute(
        "UPDATE applicationinstance SET sequence = ("
        "SELECT COUNT(*) FROM applicationinstance AS earlier "
        "WHERE earlier.deployment_id = applicationinstance.deployment_id "
        "AND (earlier.created_on < applicationinstance.created_on "
        "OR (earlier.created_on = applicationinstance.created_on "
        "AND earlier.id <= applicationinstance.id)))"
    )
    op.execute(
        "UPDATE deployment SET last_instance_sequence = ("
        "SELECT COALESCE(MAX(sequence), 0) FROM applicationinstance "
        "WHERE applicationinstance.deployment_id = deployment.id)"
    )

    with op.batch_alter_table("applicationinstance") as batch:
        batch.alter_column("sequence", existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint(UNIQUE_SEQUENCE, ["deployment_id", "sequence"])


def downgrade() -> None:
    with op.batch_alter_table("applicationinstance") as batch:
        batch.drop_constraint(UNIQUE_SEQUENCE, type_="unique")
        batch.drop_column("sequence")
    with op.batch_alter_table("deployment") as batch:
        batch.drop_column("last_instance_sequence")
