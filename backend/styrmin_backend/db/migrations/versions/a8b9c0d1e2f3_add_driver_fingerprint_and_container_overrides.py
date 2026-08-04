"""add applicationdriverversion fingerprint, container_overrides and identity index

Revision ID: a8b9c0d1e2f3
Revises: d0e1f2a3b4c5, f7b8c9d0e1f2
Create Date: 2026-08-04 00:00:00.000000

Specs 013 (driver fingerprint) and 014 (container overrides) added columns to
``ApplicationDriverVersion`` without shipping a revision, on the mistaken
premise that ``metadata.create_all()`` managed the schema. ``create_all()``
only ever builds a *fresh* database, so any database that already existed is
missing ``content_hash``, ``source_commit_sha``, ``container_overrides`` and
the ``uq_application_driver_version_identity`` index. This revision backfills
all four.

It is also a merge revision: ``d0e1f2a3b4c5`` (env_vars) and ``f7b8c9d0e1f2``
(drop utility.resource_template) were both authored against ``c9d0e1f2a3b4``'s
line and left the chain with two heads, which made ``styrmin db init`` /
``styrmin db migrate`` fail outright ("Multiple head revisions are present for
given argument 'head'"). Merging them here restores a single head.
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = ("d0e1f2a3b4c5", "f7b8c9d0e1f2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_IDENTITY_COLUMNS = (
    "application_driver_id",
    "source_type",
    "source_repository",
    "source_branch",
    "source_path",
    "version",
    "content_hash",
    "source_commit_sha",
)


def _assert_no_identity_collisions(bind) -> None:
    """Pre-flight: refuse the migration if existing rows would collide.

    ``uq_application_driver_version_identity`` is UNIQUE with
    ``postgresql_nulls_not_distinct=True``, so NULLs compare equal. Rows that
    pre-date spec 013 carry NULL in both fingerprint columns and therefore
    collapse onto the narrower ``(application_driver_id, source_type,
    source_repository, source_branch, source_path, version)`` tuple, which was
    never constrained. Fail loudly with the offending rows instead of letting
    ``CREATE UNIQUE INDEX`` abort with an opaque error.
    """
    result = bind.execute(
        sa.text(
            "SELECT application_driver_id, version, COUNT(*) AS n "
            "FROM applicationdriverversion "
            "GROUP BY application_driver_id, source_type, source_repository, "
            "source_branch, source_path, version "
            "HAVING COUNT(*) > 1"
        )
    ).all()
    if result:
        offenders = ", ".join(
            f"(driver={row.application_driver_id}, version={row.version!r}, count={row.n})"
            for row in result
        )
        raise RuntimeError(
            "Refusing to create uq_application_driver_version_identity: existing "
            f"applicationdriverversion rows share an identity tuple: {offenders}. "
            "Remove the duplicates before re-running the migration."
        )


def upgrade() -> None:
    """Backfill the spec 013 / 014 columns and the identity index.

    All three columns are nullable with no default, matching the model
    declarations (``content_hash: str | None``, ``source_commit_sha:
    str | None``, ``container_overrides: list | None`` on a plain
    ``Column(JSON)``), so the adds are safe on a populated table: existing
    rows get NULL and deserialize the absent key to ``None``.
    """
    bind = op.get_bind()
    _assert_no_identity_collisions(bind)

    # 013: SHA-256 of the canonical driver bytes (source_type="local" rows).
    op.add_column(
        "applicationdriverversion",
        sa.Column("content_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    # 013: resolved git commit SHA at the loaded ref (source_type="git" rows).
    op.add_column(
        "applicationdriverversion",
        sa.Column(
            "source_commit_sha", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
    )
    # 014 / US6: doc-only container-override declarations.
    op.add_column(
        "applicationdriverversion",
        sa.Column("container_overrides", sa.JSON(), nullable=True),
    )

    # 013 / R-X-1: UNIQUE over the widened identity tuple. NULLs must collide,
    # hence nulls-not-distinct; the kwarg is a no-op on SQLite.
    op.create_index(
        "uq_application_driver_version_identity",
        "applicationdriverversion",
        list(_IDENTITY_COLUMNS),
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_application_driver_version_identity",
        table_name="applicationdriverversion",
    )
    op.drop_column("applicationdriverversion", "container_overrides")
    op.drop_column("applicationdriverversion", "source_commit_sha")
    op.drop_column("applicationdriverversion", "content_hash")
