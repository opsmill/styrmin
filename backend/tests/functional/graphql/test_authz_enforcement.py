"""Functional enforcement tests for default-deny + RBAC. See ADR-020."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Role, User
from styrmin_backend.services.auth.password import hash_password
from styrmin_backend.services.auth.session import create_session

from ._queries import load_query

PASSWORD = "correct horse battery staple"


async def _seed_user_with_role(session: AsyncSession, role: Role) -> tuple[User, str]:
    """Seed a user at ``role`` and mint a fresh session token for them."""
    user = User(
        username=f"alice-{role.name.lower()}",
        password_hash=hash_password(PASSWORD),
        display_name=f"Alice {role.name}",
        active=True,
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    _row, raw_token = await create_session(session, user.id)
    return user, raw_token


# ---------------------------------------------------------------------------
# Default-deny on a non-allow-listed mutation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_mutation_returns_unauthenticated(
    unauth_client: AsyncClient,
) -> None:
    response = await unauth_client.post(
        "/graphql",
        json={
            "query": load_query("create_cluster"),
            "variables": {"name": "x"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_read_only_caller_receives_forbidden_on_admin_mutation(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    """A READ_ONLY caller must hit FORBIDDEN on createCluster (ADMIN-gated)."""
    _user, token = await _seed_user_with_role(session, Role.READ_ONLY)
    response = await unauth_client.post(
        "/graphql",
        json={
            "query": load_query("create_cluster"),
            "variables": {"name": "x"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_read_write_caller_receives_forbidden_on_admin_mutation(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    """READ_WRITE is below ADMIN, so admin-gated fields still reject."""
    _user, token = await _seed_user_with_role(session, Role.READ_WRITE)
    response = await unauth_client.post(
        "/graphql",
        json={
            "query": load_query("create_cluster"),
            "variables": {"name": "x"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_admin_caller_passes_admin_mutation(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    _user, token = await _seed_user_with_role(session, Role.ADMIN)
    response = await unauth_client.post(
        "/graphql",
        json={
            "query": load_query("create_cluster"),
            "variables": {"name": "admin-cluster"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"]["createCluster"]["name"] == "admin-cluster"


# ---------------------------------------------------------------------------
# Introspection works without authentication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_introspection_works_without_authentication(
    unauth_client: AsyncClient,
) -> None:
    """ADR-020: schema discovery is intentionally public."""
    response = await unauth_client.post(
        "/graphql",
        json={"query": "{ __schema { queryType { name } } }"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"]["__schema"]["queryType"]["name"] == "Query"


# ---------------------------------------------------------------------------
# User type field gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_admin_querying_admin_only_user_field_is_forbidden(
    unauth_client: AsyncClient, session: AsyncSession
) -> None:
    """``role`` is admin-only on ``User``; READ_WRITE caller selecting it
    must get FORBIDDEN."""
    _user, token = await _seed_user_with_role(session, Role.READ_WRITE)
    response = await unauth_client.post(
        "/graphql",
        json={
            "query": "query { currentUser { id username role } }",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    # Field-level FORBIDDEN — the username field still resolves; the
    # role field carries the error.
    assert any(err["extensions"].get("code") == "FORBIDDEN" for err in errors), errors
