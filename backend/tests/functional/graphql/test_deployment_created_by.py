"""Propagation + role-gating tests for ``Deployment.createdBy`` (#190).

Verifies:

1. Read propagation — a ``Deployment.created_by_user_id`` persisted in the
   DB projects through to the GraphQL ``Deployment.createdBy`` field as
   the right ``User``.
2. Role-gating — non-admin callers see only the public subset of the
   ``User`` type (``id`` / ``username`` / ``displayName``); admin callers
   see the full record. The gate itself is owned by ADR-025 and exercised
   in ``test_authz_enforcement.py`` for ``currentUser``; this module
   pins the same contract on the ``Deployment.createdBy`` traversal.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Role, User
from styrmin_backend.db.utils import get_session
from styrmin_backend.server.app import app
from styrmin_backend.services.auth.password import hash_password
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query
from .conftest import gql
from .seeds import seed_deployment, seed_user


@pytest.mark.asyncio
async def test_deployment_created_by_username_propagation(
    session: AsyncSession,
) -> None:
    """``Deployment.createdByUsername`` projects the creator's username.

    Driver-visible (not admin-gated per FR-028): a non-admin authenticated
    caller can read the field. Asserts the value matches the username of
    the user that owns the deployment row's ``created_by_user_id`` FK.
    """
    # Seed a READ_WRITE user who will both own the deployment and act as
    # the caller. Confirms the field is not admin-gated.
    caller = User(
        username="alice-creator",
        password_hash=hash_password("not-used-but-12chars"),
        display_name="Alice Creator",
        active=True,
        role=Role.READ_WRITE,
    )
    session.add(caller)
    await session.commit()
    await session.refresh(caller)
    _row, raw_token = await create_session(session, caller.id)

    deployment = await seed_deployment(session, creator=caller)

    async def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {raw_token}"},
        ) as caller_client:
            response = await caller_client.post(
                "/graphql",
                json={
                    "query": load_query("get_deployment_created_by_username"),
                    "variables": {"deploymentId": str(deployment.id)},
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    row = payload["data"]["deployment"]
    assert row["id"] == str(deployment.id)
    assert row["createdByUsername"] == "alice-creator"


@pytest.mark.asyncio
async def test_created_by_projects_persisted_user(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A ``created_by_user_id`` persisted on Deployment must surface as the
    matching ``User`` through the ``createdBy`` resolver."""
    creator = await seed_user(
        session, username="bob-creator", display_name="Bob Creator"
    )
    deployment = await seed_deployment(session, creator=creator)

    data = await gql(
        client,
        "get_deployment_created_by",
        {"deploymentId": str(deployment.id)},
    )
    created_by = data["deployment"]["createdBy"]
    assert UUID(created_by["id"]) == creator.id
    assert created_by["username"] == "bob-creator"
    assert created_by["displayName"] == "Bob Creator"


@pytest.mark.asyncio
async def test_admin_sees_full_user_record_on_created_by(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The default ``client`` is authenticated as admin (see conftest);
    selecting admin-only fields under ``createdBy`` must succeed."""
    creator = await seed_user(session, username="alice-admin", role=Role.ADMIN)
    deployment = await seed_deployment(session, creator=creator)

    data = await gql(
        client,
        "get_deployment_created_by_admin_fields",
        {"deploymentId": str(deployment.id)},
    )
    created_by = data["deployment"]["createdBy"]
    assert created_by["role"] == "ADMIN"
    assert created_by["effectiveRole"] == "ADMIN"
    assert created_by["active"] is True
    assert created_by["groups"] == []


@pytest.mark.asyncio
async def test_non_admin_querying_admin_only_field_on_created_by_is_forbidden(
    session: AsyncSession,
) -> None:
    """A READ_WRITE caller selecting ``createdBy.role`` must hit FORBIDDEN
    while ``createdBy.username`` still resolves — same field-level gate
    as ``currentUser`` per ADR-025.
    """
    # Seed a non-admin caller and a deployment they did NOT create.
    caller = User(
        username="non-admin-caller",
        password_hash=hash_password("not-used-but-12chars"),
        display_name="Non Admin Caller",
        active=True,
        role=Role.READ_WRITE,
    )
    session.add(caller)
    await session.commit()
    await session.refresh(caller)
    _row, raw_token = await create_session(session, caller.id)

    creator = await seed_user(session, username="charlie-admin", role=Role.ADMIN)
    deployment = await seed_deployment(session, creator=creator)

    async def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {raw_token}"},
        ) as caller_client:
            # Selecting an admin-only field must surface FORBIDDEN. With
            # ``createdBy: User!`` non-nullable and ``role: Role!`` non-
            # nullable, the field-level FORBIDDEN propagates the null up
            # to ``deployment``; the contract being asserted is the error
            # code, mirroring ``test_non_admin_querying_admin_only_user_field_is_forbidden``.
            response_admin = await caller_client.post(
                "/graphql",
                json={
                    "query": load_query("get_deployment_created_by_admin_fields"),
                    "variables": {"deploymentId": str(deployment.id)},
                },
            )

            # And the public-only projection must still succeed for the
            # same READ_WRITE caller — the gate is field-level, not
            # type-level.
            response_public = await caller_client.post(
                "/graphql",
                json={
                    "query": load_query("get_deployment_created_by"),
                    "variables": {"deploymentId": str(deployment.id)},
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response_admin.status_code == 200
    payload_admin = response_admin.json()
    errors = payload_admin.get("errors") or []
    assert errors, payload_admin
    assert any(err["extensions"].get("code") == "FORBIDDEN" for err in errors), errors

    assert response_public.status_code == 200
    payload_public = response_public.json()
    assert "errors" not in payload_public, payload_public
    created_by = payload_public["data"]["deployment"]["createdBy"]
    assert created_by["id"] == str(creator.id)
    assert created_by["username"] == "charlie-admin"
    assert created_by["displayName"] == creator.display_name
