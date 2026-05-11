"""Propagation, role-gating, atomicity and audit-log tests for the
admin user mutations + ``users`` query (specs/011-admin-user-group-mgmt).

Covers tasks T033, T034, T036, T038 of chunk 6:

* T033 — propagation tests for every mutation/argument in
  ``contracts/graphql.md`` plus the canonicalisation / duplicate /
  session-invalidation / FK-rejection cases.
* T034 — RBAC matrix per mutation/query:
  UNAUTHENTICATED / read_only FORBIDDEN / read_write FORBIDDEN /
  admin success.
* T036 — atomic-on-failure under a session-delete failure for both
  ``resetUserPassword`` and ``updateUser(active=False)``.
* T038 — audit-log tests: each successful admin mutation emits one
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

from styrmin_backend.db.models import (
    Group,
    Role,
    Session as SessionModel,
    User,
    UserGroup,
)
from styrmin_backend.services.auth.password import hash_password, verify_password
from styrmin_backend.services.auth.session import create_session

from tests.functional.graphql._queries import load_query

# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


async def _seed_extra_user(
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


async def _seed_group(session: AsyncSession, *, name: str, role: Role) -> Group:
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


async def _read_back_user_state(
    test_session: AsyncSession, user_id: UUID
) -> tuple[str, int]:
    """Read ``(password_hash, session_count)`` through a fresh AsyncSession.

    The atomic-on-failure tests need to inspect committed DB state after
    an aborted mutation. The shared ``session`` fixture still has the
    mutated User object in its identity map (``expire_on_commit=False``),
    and calling ``session.expire_all()`` then querying through the same
    session triggers the SQLAlchemy "MissingGreenlet" async-sync mismatch
    when the ORM auto-refreshes expired attributes. A brand-new session
    on the same engine bypasses both problems.
    """
    engine = test_session.info["_engine"]
    async with AsyncSession(engine, expire_on_commit=False) as fresh:
        user_row = (await fresh.exec(select(User).where(User.id == user_id))).one()
        session_rows = (
            await fresh.exec(
                select(SessionModel).where(SessionModel.user_id == user_id)
            )
        ).all()
        return user_row.password_hash, len(session_rows)


async def _read_back_user_active(
    test_session: AsyncSession, user_id: UUID
) -> tuple[bool, int]:
    """Read ``(active, session_count)`` through a fresh AsyncSession."""
    engine = test_session.info["_engine"]
    async with AsyncSession(engine, expire_on_commit=False) as fresh:
        user_row = (await fresh.exec(select(User).where(User.id == user_id))).one()
        session_rows = (
            await fresh.exec(
                select(SessionModel).where(SessionModel.user_id == user_id)
            )
        ).all()
        return user_row.active, len(session_rows)


# -------------------------------------------------------------------------
# Loguru capture fixture
# -------------------------------------------------------------------------


@pytest.fixture
def audit_lines() -> Iterator[list[str]]:
    """Capture loguru log messages for the duration of the test.

    Loguru does not propagate to stdlib logging by default — caplog won't
    see ``admin_mutation`` lines. We install a list-sink and filter for
    audit messages at the assertion site.
    """

    captured: list[str] = []

    def _sink(message: Any) -> None:
        captured.append(message.record["message"])

    sink_id = logger.add(_sink, level="INFO", format="{message}")
    try:
        yield captured
    finally:
        logger.remove(sink_id)


def _audit_for(action: str, lines: list[str]) -> list[str]:
    """Return only ``admin_mutation`` lines for the requested ``action``."""
    return [
        line
        for line in lines
        if line.startswith("admin_mutation ") and f"action={action} " in line
    ]


# =========================================================================
# T033 — Propagation + happy-path
# =========================================================================


@pytest.mark.asyncio
async def test_create_user_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """Every CreateUserInput field reaches the DB row."""
    group = await _seed_group(session, name="ops", role=Role.READ_WRITE)
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("create_user"),
            "variables": {
                "input": {
                    "username": "bob",
                    "password": "a-good-password-12345",
                    "displayName": "Bob",
                    "role": "READ_WRITE",
                    "groupIds": [str(group.id)],
                }
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    created_id = UUID(payload["data"]["createUser"]["id"])

    db_user = (await session.exec(select(User).where(User.id == created_id))).one()
    assert db_user.username == "bob"
    assert db_user.display_name == "Bob"
    assert db_user.role == Role.READ_WRITE
    assert db_user.active is True
    assert verify_password(db_user.password_hash, "a-good-password-12345") is True

    links = (
        await session.exec(select(UserGroup).where(UserGroup.user_id == created_id))
    ).all()
    assert {link.group_id for link in links} == {group.id}


@pytest.mark.asyncio
async def test_update_user_display_name_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    target = await _seed_extra_user(session, username="cara")
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_user"),
            "variables": {
                "id": str(target.id),
                "input": {"displayName": "Cara Reno"},
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    refreshed = (await session.exec(select(User).where(User.id == target.id))).one()
    assert refreshed.display_name == "Cara Reno"


@pytest.mark.asyncio
async def test_update_user_role_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    target = await _seed_extra_user(session, username="dave", role=Role.READ_ONLY)
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_user"),
            "variables": {
                "id": str(target.id),
                "input": {"role": "READ_WRITE"},
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    refreshed = (await session.exec(select(User).where(User.id == target.id))).one()
    assert refreshed.role == Role.READ_WRITE


@pytest.mark.asyncio
async def test_update_user_active_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    target = await _seed_extra_user(session, username="eve", role=Role.READ_WRITE)
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_user"),
            "variables": {
                "id": str(target.id),
                "input": {"active": False},
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    refreshed = (await session.exec(select(User).where(User.id == target.id))).one()
    assert refreshed.active is False


@pytest.mark.asyncio
async def test_update_user_group_ids_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """Set semantics: replacing the group list inserts/deletes the diff."""
    target = await _seed_extra_user(session, username="frank", role=Role.READ_WRITE)
    g_old = await _seed_group(session, name="old-group", role=Role.READ_ONLY)
    g_new1 = await _seed_group(session, name="new-1", role=Role.READ_WRITE)
    g_new2 = await _seed_group(session, name="new-2", role=Role.READ_ONLY)
    await _link_user_to_group(session, user_id=target.id, group_id=g_old.id)

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_user"),
            "variables": {
                "id": str(target.id),
                "input": {"groupIds": [str(g_new1.id), str(g_new2.id)]},
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    links = (
        await session.exec(select(UserGroup).where(UserGroup.user_id == target.id))
    ).all()
    assert {link.group_id for link in links} == {g_new1.id, g_new2.id}


@pytest.mark.asyncio
async def test_reset_user_password_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """Hash actually changes and all of the target's sessions are deleted."""
    target = await _seed_extra_user(session, username="gina", role=Role.READ_WRITE)
    old_hash = target.password_hash
    # Seed two sessions for the target so we can prove both are wiped.
    await create_session(session, target.id)
    await create_session(session, target.id)

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("reset_user_password"),
            "variables": {
                "userId": str(target.id),
                "newPassword": "fresh-password-42-abc",
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"]["resetUserPassword"] is True

    refreshed = (await session.exec(select(User).where(User.id == target.id))).one()
    assert refreshed.password_hash != old_hash
    assert verify_password(refreshed.password_hash, "fresh-password-42-abc") is True

    sessions = (
        await session.exec(
            select(SessionModel).where(SessionModel.user_id == target.id)
        )
    ).all()
    assert sessions == []


@pytest.mark.asyncio
async def test_delete_user_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """The row is gone; user_group and session rows cascade."""
    target = await _seed_extra_user(session, username="hank", role=Role.READ_WRITE)
    group = await _seed_group(session, name="hank-club", role=Role.READ_ONLY)
    await _link_user_to_group(session, user_id=target.id, group_id=group.id)
    await create_session(session, target.id)

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("delete_user"),
            "variables": {"id": str(target.id)},
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"]["deleteUser"] is True

    user_row = (await session.exec(select(User).where(User.id == target.id))).first()
    assert user_row is None

    links = (
        await session.exec(select(UserGroup).where(UserGroup.user_id == target.id))
    ).all()
    assert links == []

    sessions = (
        await session.exec(
            select(SessionModel).where(SessionModel.user_id == target.id)
        )
    ).all()
    assert sessions == []


@pytest.mark.asyncio
async def test_users_query_filters_propagation(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """``users(active, role, search)`` filters apply independently."""
    await _seed_extra_user(session, username="ivy", role=Role.READ_WRITE)
    await _seed_extra_user(session, username="jane", role=Role.READ_ONLY)
    await _seed_extra_user(session, username="kate", role=Role.READ_WRITE, active=False)

    # 1. active=True filter
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("list_users"),
            "variables": {"active": True},
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    usernames = {u["username"] for u in payload["data"]["users"]}
    assert "kate" not in usernames
    assert "ivy" in usernames
    assert "jane" in usernames

    # 2. role=READ_WRITE filter — ivy + kate (irrespective of active)
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("list_users"),
            "variables": {"role": "READ_WRITE"},
        },
    )
    payload = response.json()
    usernames = {u["username"] for u in payload["data"]["users"]}
    assert "ivy" in usernames
    assert "kate" in usernames
    assert "jane" not in usernames

    # 3. search filter — substring over username/display_name
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("list_users"),
            "variables": {"search": "jan"},
        },
    )
    payload = response.json()
    usernames = {u["username"] for u in payload["data"]["users"]}
    assert "jane" in usernames
    assert "ivy" not in usernames


@pytest.mark.asyncio
async def test_create_user_canonicalizes_username(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """Service-layer canonicalisation: ``AlicE`` is persisted as ``alice``."""
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("create_user"),
            "variables": {
                "input": {
                    "username": "AlicE",
                    "password": "another-good-password-9",
                    "displayName": "Alice",
                    "role": "READ_ONLY",
                }
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    created_id = UUID(payload["data"]["createUser"]["id"])
    row = (await session.exec(select(User).where(User.id == created_id))).one()
    assert row.username == "alice"


@pytest.mark.asyncio
async def test_create_user_duplicate_returns_structured_error(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """Duplicate username surfaces ``extensions.code == DUPLICATE_USERNAME``."""
    await _seed_extra_user(session, username="larry", role=Role.READ_ONLY)
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("create_user"),
            "variables": {
                "input": {
                    "username": "larry",
                    "password": "good-password-here-9",
                    "displayName": "Larry",
                    "role": "READ_ONLY",
                }
            },
        },
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "DUPLICATE_USERNAME"


@pytest.mark.asyncio
async def test_deactivate_invalidates_sessions(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """``updateUser(active=False)`` purges every session for that user."""
    target = await _seed_extra_user(session, username="mona", role=Role.READ_WRITE)
    _r1, _t1 = await create_session(session, target.id)
    _r2, _t2 = await create_session(session, target.id)
    pre = (
        await session.exec(
            select(SessionModel).where(SessionModel.user_id == target.id)
        )
    ).all()
    assert len(pre) == 2

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_user"),
            "variables": {
                "id": str(target.id),
                "input": {"active": False},
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload

    post = (
        await session.exec(
            select(SessionModel).where(SessionModel.user_id == target.id)
        )
    ).all()
    assert post == []


@pytest.mark.asyncio
async def test_reset_password_invalidates_all_sessions(
    admin_client: AsyncClient, session: AsyncSession
) -> None:
    """``resetUserPassword`` clears *every* session for the target."""
    target = await _seed_extra_user(session, username="nina", role=Role.READ_WRITE)
    await create_session(session, target.id)
    await create_session(session, target.id)

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("reset_user_password"),
            "variables": {
                "userId": str(target.id),
                "newPassword": "fresh-password-42-abc",
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload

    rows = (
        await session.exec(
            select(SessionModel).where(SessionModel.user_id == target.id)
        )
    ).all()
    assert rows == []


@pytest.mark.asyncio
async def test_delete_user_blocked_by_fk(
    admin_client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FK references hold the user in place: USER_HAS_REFERENCES.

    The Deployment model carries a long list of required FKs that aren't
    relevant to this test — we just need ``_has_deployment_references``
    to report True for our target. Patching that helper proves the
    delete path honours the precondition without resorting to a 30-line
    seed of unrelated rows.
    """
    target = await _seed_extra_user(session, username="oscar", role=Role.READ_WRITE)

    real_has_refs = "styrmin_backend.services.auth.users._has_deployment_references"

    async def _truthy(*_args, **_kwargs):
        return True

    monkeypatch.setattr(real_has_refs, _truthy)

    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("delete_user"),
            "variables": {"id": str(target.id)},
        },
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors, payload
    assert errors[0]["extensions"]["code"] == "USER_HAS_REFERENCES"

    # Row is still there.
    row = (await session.exec(select(User).where(User.id == target.id))).first()
    assert row is not None


# =========================================================================
# T034 — Role-gating matrix for every admin mutation + query
# =========================================================================


async def _make_dummy_target(session: AsyncSession, *, username: str) -> User:
    return await _seed_extra_user(session, username=username, role=Role.READ_ONLY)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "variables_key"),
    [
        ("create_user", "create"),
        ("update_user", "update"),
        ("reset_user_password", "reset"),
        ("delete_user", "delete"),
        ("list_users", "list"),
    ],
)
async def test_admin_op_unauthenticated_returns_unauthenticated(
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
        ("create_user", "create"),
        ("update_user", "update"),
        ("reset_user_password", "reset"),
        ("delete_user", "delete"),
        ("list_users", "list"),
    ],
)
async def test_admin_op_read_write_caller_is_forbidden(
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
        ("create_user", "create"),
        ("update_user", "update"),
        ("reset_user_password", "reset"),
        ("delete_user", "delete"),
        ("list_users", "list"),
    ],
)
async def test_admin_op_read_only_caller_is_forbidden(
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
        ("create_user", "create"),
        ("update_user", "update"),
        ("reset_user_password", "reset"),
        ("delete_user", "delete"),
        ("list_users", "list"),
    ],
)
async def test_admin_op_admin_caller_succeeds(
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


async def _build_variables(session: AsyncSession, key: str) -> dict[str, Any]:
    """Prepare per-operation variables for the RBAC matrix tests."""
    if key == "create":
        # Use a unique username per invocation to avoid duplicate
        # conflicts when the admin variant fires after a forbidden one
        # that may have side-effected nothing.
        import uuid

        username = f"rbac-{uuid.uuid4().hex[:8]}"
        return {
            "input": {
                "username": username,
                "password": "rbac-password-12345",
                "displayName": "RBAC",
                "role": "READ_ONLY",
            }
        }
    if key == "update":
        target = await _make_dummy_target(session, username=f"upd-{_unique()}")
        return {
            "id": str(target.id),
            "input": {"displayName": "Updated"},
        }
    if key == "reset":
        target = await _make_dummy_target(session, username=f"rst-{_unique()}")
        return {
            "userId": str(target.id),
            "newPassword": "another-good-password-9",
        }
    if key == "delete":
        target = await _make_dummy_target(session, username=f"del-{_unique()}")
        return {"id": str(target.id)}
    if key == "list":
        return {}
    raise AssertionError(f"Unknown variables key: {key}")


def _unique() -> str:
    import uuid

    return uuid.uuid4().hex[:8]


# =========================================================================
# T036 — Atomic-on-failure under a session-delete failure
# =========================================================================


@pytest.mark.asyncio
async def test_reset_password_atomic_under_failure(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If session-delete raises, the password rotation rolls back too.

    Drives the service function directly (rather than through the HTTP
    resolver) because the service is the documented transaction
    boundary per ``research.md`` §D15. The UoW context-manager catches
    the exception and issues an explicit ``rollback`` — that is the
    behaviour the test is asserting on.
    """
    from styrmin_backend.services.auth.users import (
        reset_user_password as reset_password_service,
    )
    from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

    target = await _seed_extra_user(session, username="pia", role=Role.READ_WRITE)
    old_hash = target.password_hash
    target_id = target.id
    # Seed a session so we can confirm it is still present after the failure.
    _row, _token = await create_session(session, target_id)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("session-delete kaboom")

    monkeypatch.setattr(
        "styrmin_backend.services.auth.users.delete_all_sessions_for_user",
        _boom,
    )

    engine = session.info["_engine"]
    with pytest.raises(RuntimeError, match="session-delete kaboom"):
        async with AsyncSession(engine, expire_on_commit=False) as svc_session:
            uow = SqlModelUnitOfWork(session=svc_session)
            async with uow:
                await reset_password_service(
                    uow,
                    user_id=target_id,
                    new_password="another-good-password-9",
                    actor_user_id=target_id,
                )

    refreshed_hash, surviving_sessions = await _read_back_user_state(session, target_id)
    assert refreshed_hash == old_hash, (
        "password hash must be reverted when session-delete raises"
    )
    assert surviving_sessions == 1, "pre-existing session must survive the rollback"


@pytest.mark.asyncio
async def test_deactivate_user_atomic_under_failure(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If session-delete raises, the active=False flip rolls back too.

    Same rationale as the sibling reset-password test: drive the service
    function directly so the UoW context manager's rollback hook is
    exercised on the exception path (research.md §D15).
    """
    from styrmin_backend.services.auth.users import (
        UpdateUserData,
        update_user as update_user_service,
    )
    from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

    # Seed an admin so the last-admin guard doesn't reject the unrelated
    # READ_WRITE deactivation we're about to drive through the service.
    await _seed_extra_user(session, username="quinn-keeper-admin", role=Role.ADMIN)
    target = await _seed_extra_user(session, username="quinn", role=Role.READ_WRITE)
    target_id = target.id
    assert target.active is True
    _row, _token = await create_session(session, target_id)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("session-delete kaboom")

    monkeypatch.setattr(
        "styrmin_backend.services.auth.users.delete_all_sessions_for_user",
        _boom,
    )

    engine = session.info["_engine"]
    with pytest.raises(RuntimeError, match="session-delete kaboom"):
        async with AsyncSession(engine, expire_on_commit=False) as svc_session:
            uow = SqlModelUnitOfWork(session=svc_session)
            async with uow:
                await update_user_service(
                    uow,
                    user_id=target_id,
                    input=UpdateUserData(active=False),
                    actor_user_id=target_id,
                )

    refreshed_active, surviving_sessions = await _read_back_user_active(
        session, target_id
    )
    assert refreshed_active is True, (
        "active flag must be reverted when session-delete raises"
    )
    assert surviving_sessions == 1, "pre-existing session must survive the rollback"


# =========================================================================
# T038 — Audit log
# =========================================================================


@pytest.mark.asyncio
async def test_admin_mutation_emits_audit_line_create_user(
    admin_client: AsyncClient,
    session: AsyncSession,
    audit_lines: list[str],
    admin_user: User,
) -> None:
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("create_user"),
            "variables": {
                "input": {
                    "username": "audit-create",
                    "password": "audit-password-here-12",
                    "displayName": "Audit Create",
                    "role": "READ_ONLY",
                }
            },
        },
    )
    payload = response.json()
    assert "errors" not in payload, payload
    created_id = payload["data"]["createUser"]["id"]

    audit = _audit_for("create_user", audit_lines)
    assert len(audit) == 1, audit_lines
    line = audit[0]
    assert f"actor={admin_user.id}" in line
    assert f"target={created_id}" in line
    assert "changed_fields=" in line
    assert "username" in line


@pytest.mark.asyncio
async def test_admin_mutation_emits_audit_line_update_user(
    admin_client: AsyncClient,
    session: AsyncSession,
    audit_lines: list[str],
    admin_user: User,
) -> None:
    target = await _seed_extra_user(session, username="audit-upd")
    await admin_client.post(
        "/graphql",
        json={
            "query": load_query("update_user"),
            "variables": {
                "id": str(target.id),
                "input": {"displayName": "Audit Updated"},
            },
        },
    )
    audit = _audit_for("update_user", audit_lines)
    assert len(audit) == 1, audit_lines
    assert f"actor={admin_user.id}" in audit[0]
    assert f"target={target.id}" in audit[0]
    assert "display_name" in audit[0]


@pytest.mark.asyncio
async def test_admin_mutation_emits_audit_line_reset_password(
    admin_client: AsyncClient,
    session: AsyncSession,
    audit_lines: list[str],
    admin_user: User,
) -> None:
    target = await _seed_extra_user(session, username="audit-rst")
    await admin_client.post(
        "/graphql",
        json={
            "query": load_query("reset_user_password"),
            "variables": {
                "userId": str(target.id),
                "newPassword": "audit-new-password-9",
            },
        },
    )
    audit = _audit_for("reset_user_password", audit_lines)
    assert len(audit) == 1, audit_lines
    assert f"actor={admin_user.id}" in audit[0]
    assert f"target={target.id}" in audit[0]
    # Never log the value — only the field name.
    assert "audit-new-password-9" not in audit[0]


@pytest.mark.asyncio
async def test_admin_mutation_emits_audit_line_delete_user(
    admin_client: AsyncClient,
    session: AsyncSession,
    audit_lines: list[str],
    admin_user: User,
) -> None:
    target = await _seed_extra_user(session, username="audit-del")
    await admin_client.post(
        "/graphql",
        json={
            "query": load_query("delete_user"),
            "variables": {"id": str(target.id)},
        },
    )
    audit = _audit_for("delete_user", audit_lines)
    assert len(audit) == 1, audit_lines
    assert f"actor={admin_user.id}" in audit[0]
    assert f"target={target.id}" in audit[0]


@pytest.mark.asyncio
async def test_admin_mutation_no_audit_on_rollback(
    admin_client: AsyncClient,
    session: AsyncSession,
    audit_lines: list[str],
) -> None:
    """A mutation that raises inside the transaction emits no audit line."""
    await _seed_extra_user(session, username="audit-dup")
    # Now hit createUser with the same username; the service rolls back.
    response = await admin_client.post(
        "/graphql",
        json={
            "query": load_query("create_user"),
            "variables": {
                "input": {
                    "username": "audit-dup",
                    "password": "audit-password-here-12",
                    "displayName": "Audit Dup",
                    "role": "READ_ONLY",
                }
            },
        },
    )
    payload = response.json()
    errors = payload.get("errors") or []
    assert errors
    assert errors[0]["extensions"]["code"] == "DUPLICATE_USERNAME"

    audit = _audit_for("create_user", audit_lines)
    assert audit == [], "rolled-back create_user must not leave an audit line behind"
