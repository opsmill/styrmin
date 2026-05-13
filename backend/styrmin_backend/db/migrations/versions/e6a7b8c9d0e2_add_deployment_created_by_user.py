"""add deployment.created_by_user_id (FK to user) for attribution

Revision ID: e6a7b8c9d0e2
Revises: c0d1e2f3a4b5
Create Date: 2026-05-06 00:00:00.000000

Background: see issue #190 (parent #179) and ADR-020. Every deployment
must be attributed to the user who created it so the GraphQL schema can
expose ``Deployment.createdBy: User!`` for audit/operational lookup.

Backfill choice: for any pre-existing deployment row we attribute the
deployment to the seeded admin (the first user with role=ADMIN, ordered
by ``created_on`` then ``id``). #186 seeds an admin on first boot via
the ``app_initialization`` lifespan hook, and #187 flipped enforcement
to default-deny — so every deployment that exists at the time this
migration runs was created (or operated on) under an environment where
at least one admin exists. If there are deployments but no admin, the
data step aborts with a clear message so the operator can bootstrap an
admin before retrying.

The column is added nullable, backfilled, then altered to NOT NULL with
a FK to ``user(id)``. SQLite requires ``batch_alter_table`` for the
FK + NOT NULL alteration; PostgreSQL handles the multi-step in place.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e6a7b8c9d0e2"
down_revision: Union[str, None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add the column nullable so existing rows can be backfilled.
    with op.batch_alter_table("deployment") as batch:
        batch.add_column(sa.Column("created_by_user_id", sa.Uuid(), nullable=True))

    # 2. Backfill: attribute every existing deployment to the seeded admin.
    deployment_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM deployment")
    ).scalar_one()

    if deployment_count:
        admin_id = bind.execute(
            sa.text(
                'SELECT id FROM "user" '
                "WHERE role = 'ADMIN' "
                "ORDER BY created_on, id "
                "LIMIT 1"
            )
        ).scalar()
        if admin_id is None:
            msg = (
                "Cannot backfill deployment.created_by_user_id: no admin user "
                "exists yet. Bootstrap an admin (set STYRMIN_ADMIN_PASSWORD and "
                "let app_initialization run, or insert a user with role='ADMIN' "
                "directly) before applying this migration."
            )
            raise RuntimeError(msg)

        bind.execute(
            sa.text(
                "UPDATE deployment SET created_by_user_id = :admin_id "
                "WHERE created_by_user_id IS NULL"
            ),
            {"admin_id": str(admin_id)},
        )

    # 3. Lock down: NOT NULL + FK to user(id).
    with op.batch_alter_table("deployment") as batch:
        batch.alter_column(
            "created_by_user_id", existing_type=sa.Uuid(), nullable=False
        )
        batch.create_foreign_key(
            "fk_deployment_created_by_user_id_user",
            "user",
            ["created_by_user_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("deployment") as batch:
        batch.drop_constraint(
            "fk_deployment_created_by_user_id_user", type_="foreignkey"
        )
        batch.drop_column("created_by_user_id")
