"""align deploymentstatus/podstatus/deployment constraints with the models

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-08-04 00:00:00.000000

Every live Styrmin database is a ``metadata.create_all()`` product — the
migration chain only started applying cleanly end-to-end today — so where
the chain and the models disagree it is the **models** that describe real
behaviour and the chain that describes an intent never realised. This
revision retires four such disagreements so a migrated database and a
freshly created one are byte-identical at the constraint level.

1. ``deploymentstatus`` still carries the constraint names PostgreSQL
   derived when the table was called ``deploymentcrdstatus``
   (``deploymentcrdstatus_pkey``, ``..._deployment_id_key``,
   ``..._deployment_id_fkey``). ``e5f6a7b8c9d0`` renamed the table with
   ``ALTER TABLE ... RENAME TO``, which leaves constraint names untouched.
   They are renamed to the ``deploymentstatus_*`` names ``create_all()``
   produces. On PostgreSQL ``RENAME CONSTRAINT`` also renames the index
   backing a PRIMARY KEY / UNIQUE constraint, so no separate index rename
   is needed.

2/3. ``deploymentstatus.deployment_id`` and ``podstatus.deployment_id``
   were created with ``ON DELETE CASCADE``; the models declare neither.
   The cascade is dropped rather than added to the models because it has
   never been in effect anywhere and is not the delete path: both rows are
   governed by SQLAlchemy ``delete-orphan`` on ``Deployment.pod_statuses``
   and ``Deployment.crd_status``, and deployment deletion is soft
   (``deleted_at``), so no ``DELETE FROM deployment`` ever reaches the
   database for the cascade to act on. Dropping it removes a divergence
   without removing a delete path.

4. ``deployment.created_by_user_id``'s foreign key is named
   ``fk_deployment_created_by_user_id_user`` by ``e6a7b8c9d0e2``, which has
   to name it explicitly so its SQLite batch downgrade can drop it. The
   name is kept explicit but switched to PostgreSQL's own convention,
   ``deployment_created_by_user_id_fkey``, which is what ``create_all()``
   yields — so migrated and fresh databases agree.

Portability: SQLite can neither rename a constraint nor alter a foreign key
in place, so its side of items 2, 3 and 4 goes through
``op.batch_alter_table`` (table rebuild). Item 1's PRIMARY KEY and UNIQUE
renames have no SQLite counterpart — SQLite emits both anonymously, so there
is no name to correct — and the rebuilds give the foreign keys the same names
PostgreSQL uses, because batch mode refuses to create an unnamed constraint.
One canonical name therefore identifies each of these constraints on both
backends, which is what a later revision needs in order to drop one by name.
A migrated SQLite database consequently names three foreign keys that
``create_all()`` leaves anonymous there; that asymmetry is inherent to batch
mode and predates this revision (``4586e6747b1d`` already leaves
``deployment_active_application_instance_id_fkey`` named for the same
reason). It is invisible to autogenerate, which compares foreign keys
structurally rather than by name, and SQLite is a development backend only —
tests build their schema with ``create_all()`` per ADR-001.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Names PostgreSQL derived for ``deploymentcrdstatus`` before
#: ``e5f6a7b8c9d0`` renamed the table, and the ``deploymentstatus_*`` names
#: ``create_all()`` derives today. Hardcoding is safe inside the PostgreSQL
#: branch: these are server-generated names produced deterministically by
#: ``b2c3d4e5f6a7``'s ``CREATE TABLE``.
_STALE_PK = "deploymentcrdstatus_pkey"
_STALE_UQ = "deploymentcrdstatus_deployment_id_key"
_STALE_FK = "deploymentcrdstatus_deployment_id_fkey"
_CURRENT_PK = "deploymentstatus_pkey"
_CURRENT_UQ = "deploymentstatus_deployment_id_key"
_CURRENT_FK = "deploymentstatus_deployment_id_fkey"

#: ``podstatus``'s foreign key already carries PostgreSQL's conventional
#: name; only its ``ON DELETE CASCADE`` has to go.
_POD_FK = "podstatus_deployment_id_fkey"

#: ``deployment.created_by_user_id``: the name ``e6a7b8c9d0e2`` assigned, and
#: PostgreSQL's own convention that replaces it.
_DEPLOYMENT_FK_OLD = "fk_deployment_created_by_user_id_user"
_DEPLOYMENT_FK_NEW = "deployment_created_by_user_id_fkey"

#: SQLite reflects an anonymous ``FOREIGN KEY`` with ``name=None``, and batch
#: mode can only drop a *named* constraint. Giving the reflected metadata a
#: naming convention supplies a deterministic name to target. See the Alembic
#: cookbook, "Working with constraint names", and ``c9d0e1f2a3b4`` for the
#: same technique applied to a UNIQUE constraint.
_SQLITE_FK_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
}


def _reflected_deployment_fk_name(table: str) -> str:
    """Return the name batch mode must target to drop ``table``'s deployment FK.

    On a database built by ``a1b2c3d4e5f6`` / ``b2c3d4e5f6a7``'s original
    ``CREATE TABLE`` the constraint is anonymous, and only
    ``_SQLITE_FK_CONVENTION`` can address it; after this revision's own
    downgrade it carries an explicit name, because Alembic's batch mode
    refuses to create an unnamed constraint ("Constraint must have a name").
    Inspect the live schema rather than assume, so a re-upgrade following a
    downgrade finds the constraint either way.
    """
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(table):
        if list(fk["constrained_columns"]) == ["deployment_id"]:
            return fk["name"] or f"fk_{table}_deployment_id_deployment"
    msg = f"{table} has no foreign key on deployment_id to rewrite"
    raise RuntimeError(msg)


def _sqlite_swap_deployment_fk(table: str, *, ondelete: str | None) -> None:
    """Rebuild ``table`` on SQLite with its deployment FK's cascade set."""
    with op.batch_alter_table(table, naming_convention=_SQLITE_FK_CONVENTION) as batch:
        batch.drop_constraint(_reflected_deployment_fk_name(table), type_="foreignkey")
        batch.create_foreign_key(
            f"{table}_deployment_id_fkey",
            "deployment",
            ["deployment_id"],
            ["id"],
            ondelete=ondelete,
        )


def _rename_constraint(table: str, old: str, new: str) -> None:
    """Rename a constraint on PostgreSQL.

    Alembic exposes no ``rename_constraint``; PostgreSQL's ``ALTER TABLE ...
    RENAME CONSTRAINT`` also renames the index backing a PRIMARY KEY or
    UNIQUE constraint, so this covers ``pg_constraint`` and ``pg_indexes``
    in one statement.
    """
    op.execute(f'ALTER TABLE {table} RENAME CONSTRAINT "{old}" TO "{new}"')


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        # 1. Retire the pre-rename constraint names.
        _rename_constraint("deploymentstatus", _STALE_PK, _CURRENT_PK)
        _rename_constraint("deploymentstatus", _STALE_UQ, _CURRENT_UQ)

        # 1 + 2. The foreign key needs both a new name and no cascade;
        # changing ``ON DELETE`` requires a drop/create either way, so the
        # rename comes along for free.
        op.drop_constraint(_STALE_FK, "deploymentstatus", type_="foreignkey")
        op.create_foreign_key(
            _CURRENT_FK, "deploymentstatus", "deployment", ["deployment_id"], ["id"]
        )

        # 3. Same for podstatus, whose name is already conventional.
        op.drop_constraint(_POD_FK, "podstatus", type_="foreignkey")
        op.create_foreign_key(
            _POD_FK, "podstatus", "deployment", ["deployment_id"], ["id"]
        )

        # 4. Adopt PostgreSQL's convention for the attribution foreign key.
        _rename_constraint("deployment", _DEPLOYMENT_FK_OLD, _DEPLOYMENT_FK_NEW)
        return

    # SQLite: rebuild each status table with the cascade gone (items 2 and 3).
    for table in ("deploymentstatus", "podstatus"):
        _sqlite_swap_deployment_fk(table, ondelete=None)

    # Item 4: adopt the same name PostgreSQL uses, so one canonical name
    # identifies this constraint on both backends.
    with op.batch_alter_table("deployment") as batch:
        batch.drop_constraint(_DEPLOYMENT_FK_OLD, type_="foreignkey")
        batch.create_foreign_key(
            _DEPLOYMENT_FK_NEW, "user", ["created_by_user_id"], ["id"]
        )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        _rename_constraint("deployment", _DEPLOYMENT_FK_NEW, _DEPLOYMENT_FK_OLD)

        op.drop_constraint(_POD_FK, "podstatus", type_="foreignkey")
        op.create_foreign_key(
            _POD_FK,
            "podstatus",
            "deployment",
            ["deployment_id"],
            ["id"],
            ondelete="CASCADE",
        )

        op.drop_constraint(_CURRENT_FK, "deploymentstatus", type_="foreignkey")
        op.create_foreign_key(
            _STALE_FK,
            "deploymentstatus",
            "deployment",
            ["deployment_id"],
            ["id"],
            ondelete="CASCADE",
        )

        _rename_constraint("deploymentstatus", _CURRENT_UQ, _STALE_UQ)
        _rename_constraint("deploymentstatus", _CURRENT_PK, _STALE_PK)
        return

    with op.batch_alter_table("deployment") as batch:
        batch.drop_constraint(_DEPLOYMENT_FK_NEW, type_="foreignkey")
        batch.create_foreign_key(
            _DEPLOYMENT_FK_OLD, "user", ["created_by_user_id"], ["id"]
        )

    for table in ("deploymentstatus", "podstatus"):
        _sqlite_swap_deployment_fk(table, ondelete="CASCADE")
