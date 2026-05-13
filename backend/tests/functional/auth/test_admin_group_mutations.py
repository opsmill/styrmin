"""Propagation, role-gating, last-admin and audit-log tests for the
admin group mutations + ``groups`` query
(specs/011-admin-user-group-mgmt, chunk 9).

Mirrors ``test_admin_user_mutations.py``:

* Propagation tests for every mutation/argument in
  ``contracts/graphql.md`` (create/update/delete/list; name, role,
  member_ids replacement).
* Role-gating matrix per mutation/query:
  UNAUTHENTICATED / read_only FORBIDDEN / read_write FORBIDDEN /
  admin success.
* Last-admin rejection paths: updateGroup demote/membership-strip and
  deleteGroup against an admin-conferring group whose only member is
  the only active admin.
* Audit-log lines: each successful admin mutation emits one
  ``admin_mutation`` line; a mutation that raises emits none.
"""

from __future__ import annotations

from typing import Any, Iterator
from uuid import UUID

import pytest
from httpx import AsyncClient
from loguru import logger
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Group, Role, User, UserGroup
from styrmin_backend.services.auth.password import hash_password

from tests.functional.graphql._queries import load_query

# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


async def _seed_user(
    session: AsyncSession,
    *,
    username: str,
    role: Role = Role.READ_ONLY,
    active: bool = True,
) -> User:
    user = User(
        username=username,
        password_hash=hash_password("password-for-fixture-only"),
        display_name=username,
        active=active,
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _seed_group(
    session: AsyncSession, *, name: str, role: Role = Role.READ_ONLY
) -> Group:
    group = Group(name=name, role=role)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group


async def _link_user_to_group(
    session: AsyncSession, *, user_id: UUID, group_id: UUID
) -> None:
    session.add(UserGroup(user_id=user_id, group_id=group_id))
    await session.commit()


# -------------------------------------------------------------------------
# Loguru capture fixture (audit lines)
# -------------------------------------------------------------------------


@pytest.fixture
def audit_lines() -> Iterator[list[str]]:
    captured: list[str] = []

    def _sink(message: Any) -> None:
        captured.append(message.record["message"])

    sink_id = logger.add(_sink, level="INFO", format="{message}")
    try:
        yield captured
    finally:
        logger.remove(sink_id)


def _audit_for(action: str, lines: list[str]) -> list[str]:
    return [
        line
        for line in lines
        if line.startswith("admin_mutation ") and f"action={action} " in line
    ]


# =========================================================================
# Propagation + happy-path
# =========================================================================


@pytest.mark.asyncio
async def test_create_group_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """Every CreateGroupInput field reaches the DB row + memberships."""
    member1 = await _seed_user(session, username="member-1")
    member2 = await _seed_user(session, username="member-2")
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("create_group"),
            "variables": {
                "input": {
                    "name": "ops",
                    "role": "READ_WRITE",
                    "memberIds": [str(member1.id), str(member2.id)],
                }
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    created_id = UUID(payload["data"]["createGroup"]["id"])

    db_group = (await session.exec(select(Group).where(Group.id == created_id))).one()
    assert db_group.name == "ops"
    assert db_group.role == Role.READ_WRITE

    links = (
        await session.exec(select(UserGroup).where(UserGroup.group_id == created_id))
    ).all()
    assert {link.user_id for link in links} == {member1.id, member2.id}


@pytest.mark.asyncio
async def test_update_group_name_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    target = await _seed_group(session, name="orig-name")
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_group"),
            "variables": {
                "id": str(target.id),
                "input": {"name": "renamed"},
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    refreshed = (await session.exec(select(Group).where(Group.id == target.id))).one()
    assert refreshed.name == "renamed"


@pytest.mark.asyncio
async def test_update_group_role_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    target = await _seed_group(session, name="role-target", role=Role.READ_ONLY)
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_group"),
            "variables": {
                "id": str(target.id),
                "input": {"role": "READ_WRITE"},
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    refreshed = (await session.exec(select(Group).where(Group.id == target.id))).one()
    assert refreshed.role == Role.READ_WRITE


@pytest.mark.asyncio
async def test_update_group_member_ids_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """Set semantics: replacing the member list inserts/deletes the diff."""
    target = await _seed_group(session, name="member-target")
    u_old = await _seed_user(session, username="old-member")
    u_new1 = await _seed_user(session, username="new-1")
    u_new2 = await _seed_user(session, username="new-2")
    await _link_user_to_group(session, user_id=u_old.id, group_id=target.id)

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_group"),
            "variables": {
                "id": str(target.id),
                "input": {"memberIds": [str(u_new1.id), str(u_new2.id)]},
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    links = (
        await session.exec(select(UserGroup).where(UserGroup.group_id == target.id))
    ).all()
    assert {link.user_id for link in links} == {u_new1.id, u_new2.id}


@pytest.mark.asyncio
async def test_delete_group_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """The row is gone; user_group rows cascade."""
    target = await _seed_group(session, name="doomed")
    member = await _seed_user(session, username="doomed-member")
    await _link_user_to_group(session, user_id=member.id, group_id=target.id)

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("delete_group"),
            "variables": {"id": str(target.id)},
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"]["deleteGroup"] is True

    group_row = (await session.exec(select(Group).where(Group.id == target.id))).first()
    assert group_row is None

    links = (
        await session.exec(select(UserGroup).where(UserGroup.group_id == target.id))
    ).all()
    assert links == []


@pytest.mark.asyncio
async def test_groups_query_filter_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """``groups(search)`` filters by case-insensitive substring."""
    await _seed_group(session, name="ops-team")
    await _seed_group(session, name="dev-team")
    await _seed_group(session, name="ProdTeam")

    # No filter: all three returned.
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("list_groups"),
            "variables": {},
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    names = {g["name"] for g in payload["data"]["groups"]}
    assert {"ops-team", "dev-team", "ProdTeam"} <= names

    # Substring filter: only the matching one.
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("list_groups"),
            "variables": {"search": "dev"},
        },
    )
    payload = response.json()
    names = {g["name"] for g in payload["data"]["groups"]}
    assert "dev-team" in names
    assert "ops-team" not in names
    assert "ProdTeam" not in names


@pytest.mark.asyncio
async def test_create_group_duplicate_returns_structured_error(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """Duplicate group name surfaces ``extensions.code == DUPLICATE_GROUP_NAME``."""
    await _seed_group(session, name="dup-target")
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("create_group"),
            "variables": {
                "input": {
                    "name": "dup-target",
                    "role": "READ_ONLY",
                }
            },
        },
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "DUPLICATE_GROUP_NAME"


@pytest.mark.asyncio
async def test_update_group_unknown_id_returns_structured_error(
    admin_client: AsyncClient,
) -> None:
    """Unknown group id surfaces ``GROUP_NOT_FOUND``."""
    import uuid as _uuid

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_group"),
            "variables": {
                "id": str(_uuid.uuid4()),
                "input": {"name": "irrelevant"},
            },
        },
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "GROUP_NOT_FOUND"


@pytest.mark.asyncio
async def test_create_group_unknown_member_returns_structured_error(
    admin_client: AsyncClient,
) -> None:
    """Unknown member id surfaces ``USER_NOT_FOUND``."""
    import uuid as _uuid

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("create_group"),
            "variables": {
                "input": {
                    "name": "g-with-bad-member",
                    "role": "READ_ONLY",
                    "memberIds": [str(_uuid.uuid4())],
                }
            },
        },
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "USER_NOT_FOUND"


# =========================================================================
# Last-admin guard for group changes
# =========================================================================


@pytest.mark.asyncio
async def test_update_group_role_blocked_by_last_admin(
    admin_client: AsyncClient,
    session: AsyncSession,
    admin_user: User,
) -> None:
    """Demoting an admin-conferring group whose only active-admin member
    is the only active admin must surface ``LAST_ADMIN``.

    The fixture ``admin_user`` is a direct admin. We rotate the admin
    path through a group instead so that demoting the group strips the
    sole admin path: the direct-admin row is demoted first, then the
    group is the only admin conferral and demoting it should reject.
    """
    # Strip the direct admin so the only admin path runs through a group.
    promoted = admin_user
    admin_group = await _seed_group(session, name="admin-group", role=Role.ADMIN)
    await _link_user_to_group(session, user_id=promoted.id, group_id=admin_group.id)
    # Now demote the user to READ_WRITE so the group is the only admin source.
    promoted.role = Role.READ_WRITE
    session.add(promoted)
    await session.commit()

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_group"),
            "variables": {
                "id": str(admin_group.id),
                "input": {"role": "READ_WRITE"},
            },
        },
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "LAST_ADMIN"

    # Group role unchanged.
    refreshed = (
        await session.exec(select(Group).where(Group.id == admin_group.id))
    ).one()
    assert refreshed.role == Role.ADMIN


@pytest.mark.asyncio
async def test_update_group_member_strip_blocked_by_last_admin(
    admin_client: AsyncClient,
    session: AsyncSession,
    admin_user: User,
) -> None:
    """Removing the only-admin from their only admin-conferring group
    must surface ``LAST_ADMIN``."""
    promoted = admin_user
    admin_group = await _seed_group(session, name="ag2", role=Role.ADMIN)
    await _link_user_to_group(session, user_id=promoted.id, group_id=admin_group.id)
    promoted.role = Role.READ_WRITE
    session.add(promoted)
    await session.commit()

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_group"),
            "variables": {
                "id": str(admin_group.id),
                "input": {"memberIds": []},
            },
        },
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "LAST_ADMIN"

    # Membership unchanged.
    links = (
        await session.exec(
            select(UserGroup).where(UserGroup.group_id == admin_group.id)
        )
    ).all()
    assert {link.user_id for link in links} == {promoted.id}


@pytest.mark.asyncio
async def test_delete_group_blocked_by_last_admin(
    admin_client: AsyncClient,
    session: AsyncSession,
    admin_user: User,
) -> None:
    """Deleting an admin-conferring group whose only active-admin member
    is the only active admin must surface ``LAST_ADMIN``."""
    promoted = admin_user
    admin_group = await _seed_group(session, name="ag3", role=Role.ADMIN)
    await _link_user_to_group(session, user_id=promoted.id, group_id=admin_group.id)
    promoted.role = Role.READ_WRITE
    session.add(promoted)
    await session.commit()

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("delete_group"),
            "variables": {"id": str(admin_group.id)},
        },
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "LAST_ADMIN"

    # Group still exists.
    row = (await session.exec(select(Group).where(Group.id == admin_group.id))).first()
    assert row is not None


@pytest.mark.asyncio
async def test_update_group_role_allowed_when_other_admin_exists(
    admin_client: AsyncClient,
    session: AsyncSession,
    admin_user: User,
) -> None:
    """When a second direct admin exists, demoting an admin-conferring
    group is allowed even if its members would otherwise lose admin."""
    # admin_user is a direct admin. Add a second user as admin via group.
    secondary = await _seed_user(session, username="secondary", role=Role.READ_WRITE)
    admin_group = await _seed_group(session, name="ag4", role=Role.ADMIN)
    await _link_user_to_group(session, user_id=secondary.id, group_id=admin_group.id)

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_group"),
            "variables": {
                "id": str(admin_group.id),
                "input": {"role": "READ_WRITE"},
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload

    refreshed = (
        await session.exec(select(Group).where(Group.id == admin_group.id))
    ).one()
    assert refreshed.role == Role.READ_WRITE


# =========================================================================
# Role-gating matrix
# =========================================================================


async def _build_variables(session: AsyncSession, key: str) -> dict[str, Any]:
    """Per-operation variables for the RBAC matrix tests."""
    if key == "create":
        import uuid

        name = f"rbac-{uuid.uuid4().hex[:8]}"
        return {
            "input": {
                "name": name,
                "role": "READ_ONLY",
            }
        }
    if key == "update":
        target = await _seed_group(session, name=f"upd-{_unique()}")
        return {
            "id": str(target.id),
            "input": {"name": f"renamed-{_unique()}"},
        }
    if key == "delete":
        target = await _seed_group(session, name=f"del-{_unique()}")
        return {"id": str(target.id)}
    if key == "list":
        return {}
    raise AssertionError(f"Unknown variables key: {key}")


def _unique() -> str:
    import uuid

    return uuid.uuid4().hex[:8]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "variables_key"),
    [
        ("create_group", "create"),
        ("update_group", "update"),
        ("delete_group", "delete"),
        ("list_groups", "list"),
    ],
)
async def test_group_op_unauthenticated(
    unauth_client: AsyncClient,
    session: AsyncSession,
    operation: str,
    variables_key: str,
) -> None:
    variables = await _build_variables(session, variables_key)
    response = await unauth_client.post(
        "/graphql",
        json={"query": load_query(operation), "variables": variables},
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "variables_key"),
    [
        ("create_group", "create"),
        ("update_group", "update"),
        ("delete_group", "delete"),
        ("list_groups", "list"),
    ],
)
async def test_group_op_read_write_caller_is_forbidden(
    read_write_client: AsyncClient,
    session: AsyncSession,
    operation: str,
    variables_key: str,
) -> None:
    variables = await _build_variables(session, variables_key)
    response = await read_write_client.post(
        "/graphql",
        json={"query": load_query(operation), "variables": variables},
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "variables_key"),
    [
        ("create_group", "create"),
        ("update_group", "update"),
        ("delete_group", "delete"),
        ("list_groups", "list"),
    ],
)
async def test_group_op_read_only_caller_is_forbidden(
    read_only_client: AsyncClient,
    session: AsyncSession,
    operation: str,
    variables_key: str,
) -> None:
    variables = await _build_variables(session, variables_key)
    response = await read_only_client.post(
        "/graphql",
        json={"query": load_query(operation), "variables": variables},
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "variables_key"),
    [
        ("create_group", "create"),
        ("update_group", "update"),
        ("delete_group", "delete"),
        ("list_groups", "list"),
    ],
)
async def test_group_op_admin_caller_succeeds(
    admin_client: AsyncClient,
    session: AsyncSession,
    operation: str,
    variables_key: str,
) -> None:
    variables = await _build_variables(session, variables_key)
    response = await admin_client.post(
        "/graphql",
        json={"query": load_query(operation), "variables": variables},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload


# =========================================================================
# Audit log
# =========================================================================


@pytest.mark.asyncio
async def test_audit_line_create_group(
    admin_client: AsyncClient,
    session: AsyncSession,
    audit_lines: list[str],
    admin_user: User,
) -> None:
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("create_group"),
            "variables": {
                "input": {"name": "audit-create", "role": "READ_ONLY"},
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    created_id = payload["data"]["createGroup"]["id"]

    audit = _audit_for("create_group", audit_lines)
    assert len(audit) == 1, audit_lines
    line = audit[0]
    assert f"actor={admin_user.id}" in line
    assert f"target={created_id}" in line
    assert "changed_fields=" in line
    assert "name" in line
    assert "role" in line


@pytest.mark.asyncio
async def test_audit_line_update_group(
    admin_client: AsyncClient,
    session: AsyncSession,
    audit_lines: list[str],
    admin_user: User,
) -> None:
    target = await _seed_group(session, name="audit-upd")
    await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_group"),
            "variables": {
                "id": str(target.id),
                "input": {"name": "audit-upd-renamed"},
            },
        },
    )
    audit = _audit_for("update_group", audit_lines)
    assert len(audit) == 1, audit_lines
    assert f"actor={admin_user.id}" in audit[0]
    assert f"target={target.id}" in audit[0]
    assert "name" in audit[0]


@pytest.mark.asyncio
async def test_audit_line_delete_group(
    admin_client: AsyncClient,
    session: AsyncSession,
    audit_lines: list[str],
    admin_user: User,
) -> None:
    target = await _seed_group(session, name="audit-del")
    await admin_client.post(
        "/graphql",
        json={
            "query": load_query("delete_group"),
            "variables": {"id": str(target.id)},
        },
    )
    audit = _audit_for("delete_group", audit_lines)
    assert len(audit) == 1, audit_lines
    assert f"actor={admin_user.id}" in audit[0]
    assert f"target={target.id}" in audit[0]


@pytest.mark.asyncio
async def test_no_audit_line_on_rollback(
    admin_client: AsyncClient,
    session: AsyncSession,
    audit_lines: list[str],
) -> None:
    """A mutation that raises inside the transaction emits no audit line."""
    await _seed_group(session, name="audit-dup")
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("create_group"),
            "variables": {
                "input": {"name": "audit-dup", "role": "READ_ONLY"},
            },
        },
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors
    assert errors[0]["extensions"]["code"] == "DUPLICATE_GROUP_NAME"

    audit = _audit_for("create_group", audit_lines)
    assert audit == [], "rolled-back create_group must not leave an audit line"
