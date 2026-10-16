"""drop scheduling from stored cluster configs

Revision ID: eac41bb71a65
Revises: c4d1e8a2b7f3
Create Date: 2026-10-16 00:00:00.000000
"""

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "eac41bb71a65"
down_revision: Union[str, Sequence[str], None] = "c4d1e8a2b7f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "scheduling"

_cluster = sa.table(
    "cluster", sa.column("id", sa.Uuid()), sa.column("config", sa.JSON())
)
_instance = sa.table(
    "applicationinstance", sa.column("id", sa.Uuid()), sa.column("context", sa.JSON())
)


def _strip(config: Any) -> Any:
    if isinstance(config, dict) and _KEY in config:
        return {k: v for k, v in config.items() if k != _KEY}
    return config


def _strip_cluster_context(context: Any) -> Any:
    if not isinstance(context, dict):
        return context
    cluster = context.get("cluster")
    if not isinstance(cluster, dict) or "config" not in cluster:
        return context
    return {**context, "cluster": {**cluster, "config": _strip(cluster["config"])}}


def _rewrite(table: sa.TableClause, column: str, transform: Any) -> None:
    bind = op.get_bind()
    for row_id, value in bind.execute(
        sa.select(table.c.id, table.c[column])
    ).fetchall():
        new_value = transform(value)
        if new_value != value:
            bind.execute(
                sa.update(table).where(table.c.id == row_id).values({column: new_value})
            )


def upgrade() -> None:
    """Remove ``scheduling``, which no pod ever got (#482), from every stored cluster config.

    ``ClusterConfig`` now rejects the key, so a stored value would fail to load.
    Only the cluster config of an instance context is changed: its deployment and
    instance configs take ``scheduling`` from the environment and the deployment.
    """
    _rewrite(_cluster, "config", _strip)
    _rewrite(_instance, "context", _strip_cluster_context)


def downgrade() -> None:
    # The removed values had no effect, and the previous code accepts configs without the key.
    pass
