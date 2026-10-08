"""drop the empty dedicated_ingress default from cluster.config

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-10-08 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_cluster = sa.table(
    "cluster",
    sa.column("id", sa.Uuid()),
    sa.column("config", sa.JSON()),
    sa.column("capabilities", sa.JSON()),
)


def upgrade() -> None:
    """Remove ``dedicated_ingress: {}`` from every cluster's ``config`` JSON.

    ``create_cluster`` stored ``{}`` when the request had no ``dedicated_ingress``
    key (#409), and no dedicated ingress controller was ever deployed for it. An
    empty object now turns the controller on, so the key is removed to keep it off.
    Environments keep a stored ``{}`` because an operator set it.

    The stored ``ingress`` capability is dropped when the cluster has no
    ``ingress_class``, because the empty object was its only ingress source.
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_cluster.c.id, _cluster.c.config, _cluster.c.capabilities)
    ).fetchall()
    for row_id, config, capabilities in rows:
        if not isinstance(config, dict) or config.get("dedicated_ingress") != {}:
            continue
        new_config = {k: v for k, v in config.items() if k != "dedicated_ingress"}
        new_capabilities = capabilities
        if isinstance(capabilities, dict) and new_config.get("ingress_class") is None:
            new_capabilities = {
                k: v for k, v in capabilities.items() if k != "ingress"
            } or None
        bind.execute(
            sa.update(_cluster)
            .where(_cluster.c.id == row_id)
            .values(config=new_config, capabilities=new_capabilities)
        )


def downgrade() -> None:
    # A cluster without the key is valid for the previous code too: no
    # controller, and the Ingress uses the cluster ingress_class.
    pass
