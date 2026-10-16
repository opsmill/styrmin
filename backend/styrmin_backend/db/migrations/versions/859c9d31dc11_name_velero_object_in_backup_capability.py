"""name the Velero object in the backup capability of environments

Revision ID: 859c9d31dc11
Revises: eac41bb71a65
Create Date: 2026-10-16 00:00:00.000000
"""

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "859c9d31dc11"
down_revision: Union[str, Sequence[str], None] = "eac41bb71a65"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_environment = sa.table(
    "environment",
    sa.column("id", sa.Uuid()),
    sa.column("capabilities", sa.JSON()),
    sa.column("backup_storage_location_id", sa.Uuid()),
)
_location = sa.table(
    "backupstoragelocation", sa.column("id", sa.Uuid()), sa.column("name", sa.String())
)


def _with_storage_location(capabilities: Any, storage_location: str) -> dict[str, Any]:
    rest = capabilities if isinstance(capabilities, dict) else {}
    return {**rest, "backup": {"velero": {"storage_location": storage_location}}}


def _rewrite(storage_location_of: Any) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(
            _environment.c.id,
            _environment.c.capabilities,
            _location.c.id,
            _location.c.name,
        ).join(_location, _environment.c.backup_storage_location_id == _location.c.id)
    ).fetchall()
    for environment_id, capabilities, location_id, location_name in rows:
        new_capabilities = _with_storage_location(
            capabilities, storage_location_of(location_id, location_name)
        )
        if new_capabilities != capabilities:
            bind.execute(
                sa.update(_environment)
                .where(_environment.c.id == environment_id)
                .values(capabilities=new_capabilities)
            )


def upgrade() -> None:
    """Set ``backup.velero.storage_location`` to the location's Velero object name (#509).

    The capability held the location's name, which no Velero object has. Since
    #488 the object is ``styrmin-bsl-<location id>``, which a rename does not change.
    """
    _rewrite(lambda location_id, _name: f"styrmin-bsl-{location_id}")


def downgrade() -> None:
    _rewrite(lambda _location_id, name: name)
