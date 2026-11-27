"""backup description and a name unique per application instance (#39)

Revision ID: a2a102e37495
Revises: 859c9d31dc11
Create Date: 2026-11-27 00:00:00.000000

Backups can now be renamed and carry a description. The name of a backup's
Velero ``Backup`` object is built from the backup's id (``styrmin-<id>``), so a
rename does not change it. Rows that an earlier version created with a custom
name already have a Velero object with that name, so the upgrade stores it in
``metadata.velero_backup_name`` for those rows only.

Downgrade limit: the older code uses ``backup.name`` as the Velero object
name. After a downgrade, a backup that was created after the upgrade with a
custom name, or renamed after the upgrade, cannot be restored by the older
code, because its Velero object is ``styrmin-<id>``. The downgrade cannot
repair this.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from loguru import logger


revision: str = "a2a102e37495"
down_revision: Union[str, Sequence[str], None] = "859c9d31dc11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "ix_backup_instance_id_name"
_VELERO_NAME_KEY = "velero_backup_name"

#: PostgreSQL's implicit name for the unnamed ``UNIQUE (name)`` of the initial schema.
_POSTGRES_CONSTRAINT_NAME = "backup_name_key"

#: SQLite reflects the unnamed constraint with ``name=None``. Batch mode can only
#: drop a named constraint, so the reflected metadata gets this naming
#: convention, as in ``c9d0e1f2a3b4_deployment_name_scoped_uniqueness``.
_SQLITE_NAMING_CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
_SQLITE_DERIVED_CONSTRAINT_NAME = "uq_backup_name"

_backup = sa.table(
    "backup",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("metadata", sa.JSON()),
)


def _find_global_name_constraint(bind) -> tuple[bool, str | None]:
    """Return ``(present, name)`` of the UNIQUE constraint on exactly ``backup.name``."""
    for constraint in sa.inspect(bind).get_unique_constraints("backup"):
        if list(constraint["column_names"]) == ["name"]:
            return True, constraint["name"]
    return False, None


def _set_metadata(bind, backup_id, metadata) -> None:
    bind.execute(
        sa.update(_backup).where(_backup.c.id == backup_id).values(metadata=metadata)
    )


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column("backup", sa.Column("description", sa.Text(), nullable=True))

    # A Python loop rather than SQL JSON functions, so it runs on PostgreSQL and SQLite.
    updated = 0
    for backup_id, name, metadata in bind.execute(
        sa.select(_backup.c.id, _backup.c.name, _backup.c.metadata)
    ).all():
        if name == f"styrmin-{backup_id}":
            continue
        current = metadata if isinstance(metadata, dict) else {}
        _set_metadata(bind, backup_id, {**current, _VELERO_NAME_KEY: name})
        updated += 1
    logger.info(
        f"Stored {_VELERO_NAME_KEY} on {updated} backup(s) created with a custom name"
    )

    present, constraint_name = _find_global_name_constraint(bind)
    if not present:
        pass
    elif bind.dialect.name == "postgresql":
        op.drop_constraint(
            constraint_name or _POSTGRES_CONSTRAINT_NAME, "backup", type_="unique"
        )
    else:
        with op.batch_alter_table(
            "backup", naming_convention=_SQLITE_NAMING_CONVENTION
        ) as batch_op:
            batch_op.drop_constraint(
                constraint_name or _SQLITE_DERIVED_CONSTRAINT_NAME, type_="unique"
            )

    op.create_index(_INDEX_NAME, "backup", ["instance_id", "name"], unique=True)


def downgrade() -> None:
    """Restore ``UNIQUE (name)`` across all backups.

    See the module docstring: backups created or renamed after the upgrade with
    a custom name cannot be restored by the older code after this downgrade.
    """
    bind = op.get_bind()

    # Checked before any change, so a refused downgrade leaves the schema as it is.
    duplicates = bind.execute(
        sa.text(
            "SELECT name, COUNT(*) AS n FROM backup GROUP BY name HAVING COUNT(*) > 1"
        )
    ).all()
    if duplicates:
        offenders = ", ".join(f"{row.name!r} ({row.n} backups)" for row in duplicates)
        raise RuntimeError(
            "Refusing to downgrade: the older schema requires backup names to be "
            f"unique across all backups, and these names are used more than once: "
            f"{offenders}. Rename the backups before you downgrade."
        )

    op.drop_index(_INDEX_NAME, table_name="backup")

    for backup_id, metadata in bind.execute(
        sa.select(_backup.c.id, _backup.c.metadata)
    ).all():
        if isinstance(metadata, dict) and _VELERO_NAME_KEY in metadata:
            rest = {k: v for k, v in metadata.items() if k != _VELERO_NAME_KEY}
            _set_metadata(bind, backup_id, rest or None)

    if bind.dialect.name == "postgresql":
        op.create_unique_constraint(_POSTGRES_CONSTRAINT_NAME, "backup", ["name"])
        op.drop_column("backup", "description")
    else:
        with op.batch_alter_table("backup") as batch_op:
            batch_op.create_unique_constraint(_POSTGRES_CONSTRAINT_NAME, ["name"])
            batch_op.drop_column("description")
