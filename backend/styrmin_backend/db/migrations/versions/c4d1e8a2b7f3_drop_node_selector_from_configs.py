"""drop node_selector from stored cluster and deployment configs

Revision ID: c4d1e8a2b7f3
Revises: 7948e6057857
Create Date: 2026-10-15 00:00:00.000000
"""

from collections.abc import Callable
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c4d1e8a2b7f3"
down_revision: Union[str, Sequence[str], None] = "7948e6057857"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "node_selector"
_BATCH_SIZE = 500

_cluster = sa.table(
    "cluster", sa.column("id", sa.Uuid()), sa.column("config", sa.JSON())
)
_deployment = sa.table(
    "deployment", sa.column("id", sa.Uuid()), sa.column("config", sa.JSON())
)
_instance = sa.table(
    "applicationinstance", sa.column("id", sa.Uuid()), sa.column("context", sa.JSON())
)
_environment_backup = sa.table(
    "environmentbackup",
    sa.column("id", sa.Uuid()),
    sa.column("deployment_snapshots", sa.JSON()),
)


def _strip(config: Any) -> Any:
    if isinstance(config, dict) and _KEY in config:
        return {k: v for k, v in config.items() if k != _KEY}
    return config


def _strip_context(context: Any) -> Any:
    if not isinstance(context, dict):
        return context
    stripped = dict(context)
    for scope in ("cluster", "deployment", "instance"):
        section = stripped.get(scope)
        if isinstance(section, dict) and "config" in section:
            stripped[scope] = {**section, "config": _strip(section["config"])}
    return stripped


def _strip_snapshots(snapshots: Any) -> Any:
    if not isinstance(snapshots, list):
        return snapshots
    return [
        {**s, "config": _strip(s["config"])}
        if isinstance(s, dict) and "config" in s
        else s
        for s in snapshots
    ]


def _rewrite(
    table: sa.TableClause, column: str, transform: Callable[[Any], Any]
) -> None:
    # Instance contexts hold every config, so read only rows that name the key, in pages by id.
    bind = op.get_bind()
    query = (
        sa.select(table.c.id, table.c[column])
        .where(sa.cast(table.c[column], sa.Text).like(f'%"{_KEY}"%'))
        .order_by(table.c.id)
        .limit(_BATCH_SIZE)
    )
    rows = bind.execute(query).fetchall()
    while rows:
        for row_id, value in rows:
            new_value = transform(value)
            if new_value != value:
                bind.execute(
                    sa.update(table)
                    .where(table.c.id == row_id)
                    .values({column: new_value})
                )
        rows = bind.execute(query.where(table.c.id > rows[-1][0])).fetchall()


def upgrade() -> None:
    """Remove ``node_selector``, which no pod ever received (#472), from every stored config.

    ``ClusterConfig`` no longer has the field and forbids unknown keys, so stored values would fail to load.
    """
    _rewrite(_cluster, "config", _strip)
    _rewrite(_deployment, "config", _strip)
    _rewrite(_instance, "context", _strip_context)
    _rewrite(_environment_backup, "deployment_snapshots", _strip_snapshots)


def downgrade() -> None:
    # The removed values had no effect, and the previous code accepts configs without the key.
    pass
