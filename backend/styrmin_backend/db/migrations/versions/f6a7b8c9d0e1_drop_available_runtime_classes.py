"""drop available_runtime_classes from cluster.config

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-24 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Strip ``available_runtime_classes`` from every cluster's ``config`` JSON.

    The field was removed from ``ClusterConfig`` (Pydantic ``extra="forbid"``
    would raise on load otherwise). Runtime-class validation was removed at
    the same time — deployment-level runtime_class values now pass through
    without cluster-side allow-listing.

    Also drops the no-longer-derived ``runtime_class`` key from the
    ``capabilities`` JSON on the same rows. ``Capabilities.runtime_class``
    was removed from the Pydantic model in the same change, and the key is
    only written by ``compute_cluster_capabilities``; any stored value is
    stale cache from the prior behaviour.
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, config, capabilities FROM cluster")
    ).fetchall()
    for row_id, config, capabilities in rows:
        new_config = (
            {k: v for k, v in config.items() if k != "available_runtime_classes"}
            if isinstance(config, dict)
            else config
        )
        new_capabilities = (
            {k: v for k, v in capabilities.items() if k != "runtime_class"}
            if isinstance(capabilities, dict)
            else capabilities
        )
        config_changed = isinstance(config, dict) and new_config != config
        capabilities_changed = (
            isinstance(capabilities, dict) and new_capabilities != capabilities
        )
        if not config_changed and not capabilities_changed:
            continue
        bind.execute(
            sa.text(
                "UPDATE cluster SET config = :config, capabilities = :capabilities "
                "WHERE id = :id"
            ),
            {
                "config": new_config,
                "capabilities": new_capabilities,
                "id": row_id,
            },
        )


def downgrade() -> None:
    # The stripped data cannot be recovered from the database. Downgrading is
    # a schema-level no-op; if you need the old values you must restore from
    # a backup taken before the upgrade.
    pass
