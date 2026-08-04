"""deployment name uniqueness: scope to (environment_id, name) and ignore tombstones

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-05-02 09:30:00.000000

The original schema declared ``Deployment.name`` as globally unique,
which after spec 008 (soft-delete) means a tombstoned deployment still
occupies its name slot — operators cannot recreate ``ansible`` after
deleting ``ansible``. The fix is a partial unique index on
``(environment_id, name)`` predicated on ``deleted_at IS NULL``: name
uniqueness is scoped per environment AND tombstoned rows do not count.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: PostgreSQL's implicit name for an unnamed ``UniqueConstraint("name")``.
_POSTGRES_CONSTRAINT_NAME = "deployment_name_key"

#: SQLite emits the same constraint as a bare ``UNIQUE (name)``, so it reflects
#: with ``name=None``. Batch mode can only drop a *named* constraint, so the
#: reflected metadata is given this naming convention and the derived name is
#: dropped instead. See the Alembic cookbook, "Working with constraint names".
_SQLITE_NAMING_CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
_SQLITE_DERIVED_CONSTRAINT_NAME = "uq_deployment_name"


def _find_global_name_constraint(bind) -> tuple[bool, str | None]:
    """Locate the UNIQUE constraint covering exactly ``deployment.name``.

    Returns ``(present, name)``. ``name`` is ``None`` when the backend
    reflects the constraint without one (SQLite). Inspecting the live schema
    rather than assuming a name keeps the migration portable and lets it
    no-op on a database that never had the constraint.
    """
    for constraint in sa.inspect(bind).get_unique_constraints("deployment"):
        if list(constraint["column_names"]) == ["name"]:
            return True, constraint["name"]
    return False, None


def _assert_no_active_collisions(bind) -> None:
    """Pre-flight: refuse the migration if any pair of ACTIVE deployments
    already share ``(environment_id, name)``. Under the prior global
    constraint this should be impossible, but verifying it explicitly
    means a corrupt input cannot silently produce a corrupt index.
    Tombstoned rows (``deleted_at IS NOT NULL``) may collide freely
    after this migration — that's the whole point.
    """
    result = bind.execute(
        sa.text(
            "SELECT environment_id, name, COUNT(*) AS n "
            "FROM deployment "
            "WHERE deleted_at IS NULL "
            "GROUP BY environment_id, name "
            "HAVING COUNT(*) > 1"
        )
    ).all()
    if result:
        offenders = ", ".join(
            f"(env={row.environment_id}, name={row.name!r}, count={row.n})"
            for row in result
        )
        raise RuntimeError(
            "Refusing to apply uq_deployment_env_name_active: existing "
            f"active deployments collide on (environment_id, name): {offenders}. "
            "Resolve the duplicates manually before re-running the migration."
        )


def upgrade() -> None:
    bind = op.get_bind()
    _assert_no_active_collisions(bind)

    # 1. Drop the global unique constraint on Deployment.name. It was created
    #    unnamed, so each backend reports it differently — PostgreSQL derives
    #    `deployment_name_key`, SQLite reflects no name at all. Look it up in
    #    the live schema instead of assuming, and skip when it is absent.
    present, constraint_name = _find_global_name_constraint(bind)
    if not present:
        pass
    elif bind.dialect.name == "postgresql":
        op.drop_constraint(
            constraint_name or _POSTGRES_CONSTRAINT_NAME, "deployment", type_="unique"
        )
    else:
        # batch_alter_table rebuilds the table without the constraint; the
        # naming convention supplies a name for the unnamed reflected
        # constraint so it can be targeted.
        with op.batch_alter_table(
            "deployment", naming_convention=_SQLITE_NAMING_CONVENTION
        ) as batch_op:
            batch_op.drop_constraint(
                constraint_name or _SQLITE_DERIVED_CONSTRAINT_NAME, type_="unique"
            )

    # 2. Add the partial unique index on (environment_id, name) WHERE
    #    deleted_at IS NULL. Both Postgres and SQLite support partial
    #    indexes; the kwargs are mutually exclusive (the dialect picks
    #    the one it understands).
    op.create_index(
        "uq_deployment_env_name_active",
        "deployment",
        ["environment_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("uq_deployment_env_name_active", table_name="deployment")

    # Recreate the global unique constraint. If active rows currently
    # collide globally on `name` (across envs), this will fail —
    # legitimate, since the downgrade target requires global uniqueness.
    if bind.dialect.name == "postgresql":
        op.create_unique_constraint(_POSTGRES_CONSTRAINT_NAME, "deployment", ["name"])
    else:
        with op.batch_alter_table("deployment") as batch_op:
            batch_op.create_unique_constraint(_POSTGRES_CONSTRAINT_NAME, ["name"])
