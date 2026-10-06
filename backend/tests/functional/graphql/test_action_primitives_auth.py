"""Driver action primitives authenticate against the GraphQL API (issue #381, ADR-059).

The primitives run against the real ASGI app, so each call passes the
default-deny gate and the ``RequiresRole(READ_WRITE)`` gate exactly as it
does in a cluster. The token comes from ``action_api_token``, the helper
``apply_state`` uses to mint one per reconcile.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend import config
from styrmin_backend.actions import primitives
from styrmin_backend.agent.tasks.utils import STEP_ID_ENV
from styrmin_backend.db.models import (
    Role,
    Step as StepRow,
    StepKind,
    StepStatus,
    Task as TaskRow,
    TaskStatus,
    TaskType,
    User,
)
from styrmin_backend.db.utils import get_session
from styrmin_backend.server.app import app
from styrmin_backend.services.auth import action_token
from styrmin_backend.services.auth.bootstrap import (
    ACTIONS_SERVICE_ACCOUNT_USERNAME,
    ensure_actions_service_account,
)
from styrmin_backend.services.auth.login import authenticate
from styrmin_backend.services.exceptions import InvalidCredentialsError
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.helpers.unit_of_work import yield_unit_of_work

from .seeds import seed_deployment, seed_task


@pytest.fixture(autouse=True)
def asgi_api(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Route the primitives' HTTP calls to the in-process app and its test DB."""

    async def get_session_override() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_session] = get_session_override
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        primitives,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda **kwargs: real_client(
                transport=ASGITransport(app=app), **kwargs
            )
        ),
    )
    monkeypatch.setattr(config.SETTINGS.url, "api", "http://test")
    monkeypatch.delenv("STYRMIN_TOKEN", raising=False)
    monkeypatch.delenv(STEP_ID_ENV, raising=False)
    monkeypatch.setattr(
        action_token,
        "get_unit_of_work",
        yield_unit_of_work(SqlModelUnitOfWork(session=session)),
    )
    yield
    app.dependency_overrides.clear()


def _flow_info() -> AsyncMock:
    async def _run(*_args, **_kwargs):
        return SimpleNamespace(id=uuid4())

    return AsyncMock(side_effect=_run)


def _context(deployment_id) -> SimpleNamespace:
    return SimpleNamespace(
        components={}, instance=SimpleNamespace(deployment_id=deployment_id)
    )


_PRIMITIVE_CALLS = {
    "stop_components": lambda ctx: primitives.stop_components.fn([], ctx),
    "start_components": lambda ctx: primitives.start_components.fn([], ctx),
    "upgrade_deployment_version": lambda ctx: primitives.upgrade_deployment_version.fn(
        "1.0.1", ctx
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("primitive", sorted(_PRIMITIVE_CALLS))
async def test_primitive_without_token_is_rejected(
    session: AsyncSession, primitive: str
) -> None:
    deployment = await seed_deployment(session)

    with pytest.raises(RuntimeError, match="Authentication is required"):
        await _PRIMITIVE_CALLS[primitive](_context(deployment.id))


@pytest.mark.asyncio
@pytest.mark.parametrize("primitive", sorted(_PRIMITIVE_CALLS))
async def test_primitive_dispatches_with_action_token(
    session: AsyncSession,
    prefect_manager_mock,
    monkeypatch: pytest.MonkeyPatch,
    primitive: str,
) -> None:
    prefect_manager_mock.run_action = _flow_info()
    wait_for_task = AsyncMock()
    monkeypatch.setattr(primitives, "_wait_for_task", wait_for_task)
    deployment = await seed_deployment(session)

    async with action_token.action_api_token() as token:
        monkeypatch.setenv("STYRMIN_TOKEN", token)
        await _PRIMITIVE_CALLS[primitive](_context(deployment.id))

    prefect_manager_mock.run_action.assert_awaited_once()
    wait_for_task.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("primitive", sorted(_PRIMITIVE_CALLS))
async def test_primitive_links_its_task_to_the_hook_step(
    session: AsyncSession,
    prefect_manager_mock,
    monkeypatch: pytest.MonkeyPatch,
    primitive: str,
) -> None:
    """``STYRMIN_STEP_ID`` reaches ``task.started_by_step_id`` (spec 019, research D12)."""
    prefect_manager_mock.run_action = _flow_info()
    monkeypatch.setattr(primitives, "_wait_for_task", AsyncMock())
    deployment = await seed_deployment(session)
    upgrade = await seed_task(
        session, deployment=deployment, task_type=TaskType.UPGRADE_INSTANCE
    )
    hook = StepRow(
        task_id=upgrade.id,
        key="hook:upgrade:core",
        name="Run the upgrade hook",
        kind=StepKind.HOOK,
        status=StepStatus.RUNNING,
    )
    session.add(hook)
    await session.commit()
    deployment_id, hook_id = deployment.id, hook.id
    monkeypatch.setenv(STEP_ID_ENV, str(hook_id))

    async with action_token.action_api_token() as token:
        monkeypatch.setenv("STYRMIN_TOKEN", token)
        await _PRIMITIVE_CALLS[primitive](_context(deployment_id))

    session.expire_all()
    (started,) = (
        await session.exec(select(TaskRow).where(TaskRow.started_by_step_id == hook_id))
    ).all()
    assert started.deployment_id == deployment_id


@pytest.mark.asyncio
async def test_wait_for_task_reads_task_with_action_token(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = await seed_task(session, status=TaskStatus.SUCCESS)

    async with action_token.action_api_token() as token:
        monkeypatch.setenv("STYRMIN_TOKEN", token)
        async with primitives._api_client() as client:
            await primitives._wait_for_task(client, str(task.id), timeout=5.0)


@pytest.mark.asyncio
async def test_action_token_is_revoked_on_exit(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployment = await seed_deployment(session)
    with pytest.raises(ValueError, match="boom"):
        async with action_token.action_api_token() as token:
            raise ValueError("boom")
    monkeypatch.setenv("STYRMIN_TOKEN", token)

    with pytest.raises(RuntimeError, match="Authentication is required"):
        await primitives.stop_components.fn([], _context(deployment.id))


@pytest.mark.asyncio
async def test_deactivated_service_account_token_is_rejected(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployment = await seed_deployment(session)
    account = await session.get(User, await ensure_actions_service_account(session))
    assert account is not None
    account.active = False
    session.add(account)
    await session.commit()

    async with action_token.action_api_token() as token:
        monkeypatch.setenv("STYRMIN_TOKEN", token)
        with pytest.raises(RuntimeError, match="Authentication is required"):
            await primitives.stop_components.fn([], _context(deployment.id))


@pytest.mark.asyncio
async def test_service_account_is_read_write_and_cannot_log_in(
    session: AsyncSession,
) -> None:
    first = await ensure_actions_service_account(session)
    assert await ensure_actions_service_account(session) == first

    account = await session.get(User, first)
    assert account is not None
    assert account.username == ACTIONS_SERVICE_ACCOUNT_USERNAME
    assert account.role == Role.READ_WRITE

    uow = SqlModelUnitOfWork(session=session)
    async with uow:
        with pytest.raises(InvalidCredentialsError):
            await authenticate(uow, ACTIONS_SERVICE_ACCOUNT_USERNAME, "any-password")
