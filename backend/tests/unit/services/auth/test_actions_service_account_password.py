"""No person can log in as, or set a password for, ``styrmin-actions`` (ADR-059).

``recordStep`` trusts the username, so these paths must never produce a
session for that user. The account is seeded with a usable hash to prove
the refusals do not depend on the unusable hash the bootstrap writes.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Role, Session as SessionModel, User
from styrmin_backend.services.auth.bootstrap import ACTIONS_SERVICE_ACCOUNT_USERNAME
from styrmin_backend.services.auth.login import authenticate
from styrmin_backend.services.auth.password import hash_password
from styrmin_backend.services.auth.password_change import change_password
from styrmin_backend.services.auth.session import create_session
from styrmin_backend.services.auth.users import (
    CreateUserData,
    create_user,
    reset_user_password,
)
from styrmin_backend.services.exceptions import (
    ActionsServiceAccountError,
    InvalidCredentialsError,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

_PASSWORD = "known-password"


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as ses:
        yield ses
    await engine.dispose()


@pytest.fixture
async def actions_user(db_session: AsyncSession) -> User:
    user = User(
        username=ACTIONS_SERVICE_ACCOUNT_USERNAME,
        password_hash=hash_password(_PASSWORD),
        display_name="Styrmin driver actions",
        active=True,
        role=Role.READ_WRITE,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _stored_hash(db_session: AsyncSession, user: User) -> str:
    result = await db_session.exec(select(User.password_hash).where(User.id == user.id))
    return result.one()


@pytest.mark.asyncio
async def test_login_refuses_actions_user_with_the_right_password(
    db_session: AsyncSession, actions_user: User
) -> None:
    uow = SqlModelUnitOfWork(session=db_session)
    with pytest.raises(InvalidCredentialsError):
        await authenticate(uow, ACTIONS_SERVICE_ACCOUNT_USERNAME.upper(), _PASSWORD)

    sessions = await db_session.exec(
        select(SessionModel).where(SessionModel.user_id == actions_user.id)
    )
    assert sessions.all() == []


@pytest.mark.asyncio
async def test_change_password_refuses_actions_user(
    db_session: AsyncSession, actions_user: User
) -> None:
    session_row, _token = await create_session(db_session, actions_user.id)
    before = await _stored_hash(db_session, actions_user)

    with pytest.raises(ActionsServiceAccountError) as exc_info:
        await change_password(
            db_session,
            user=actions_user,
            current_password=_PASSWORD,
            new_password="new-password",
            calling_session_id=session_row.id,
        )

    assert exc_info.value.error_code == "FORBIDDEN"
    assert await _stored_hash(db_session, actions_user) == before


@pytest.mark.asyncio
async def test_reset_user_password_refuses_actions_user(
    db_session: AsyncSession, actions_user: User
) -> None:
    session_row, _token = await create_session(db_session, actions_user.id)
    before = await _stored_hash(db_session, actions_user)
    uow = SqlModelUnitOfWork(session=db_session)

    with pytest.raises(ActionsServiceAccountError) as exc_info:
        await reset_user_password(
            uow,
            user_id=actions_user.id,
            new_password="new-password",
            actor_user_id=uuid4(),
        )

    assert exc_info.value.error_code == "FORBIDDEN"
    assert await _stored_hash(db_session, actions_user) == before
    # The refusal comes before the session wipe, so running actions keep their token.
    assert await db_session.get(SessionModel, session_row.id) is not None


@pytest.mark.asyncio
async def test_create_user_refuses_the_actions_username(
    db_session: AsyncSession,
) -> None:
    uow = SqlModelUnitOfWork(session=db_session)

    with pytest.raises(ActionsServiceAccountError) as exc_info:
        await create_user(
            uow,
            input=CreateUserData(
                username="Styrmin-Actions",
                password=_PASSWORD,
                display_name="Someone",
                role=Role.ADMIN,
            ),
            actor_user_id=uuid4(),
        )

    assert exc_info.value.error_code == "FORBIDDEN"
    users = await db_session.exec(select(User))
    assert users.all() == []
