"""Login service. See ADR-019."""

from __future__ import annotations

from sqlalchemy.orm import selectinload
from sqlmodel import select

from styrmin_backend.db.models import Session as SessionModel
from styrmin_backend.db.models import User
from styrmin_backend.services.auth.password import (
    needs_rehash,
    hash_password,
    verify_password,
)
from styrmin_backend.services.auth.session import create_session
from styrmin_backend.services.exceptions import InvalidCredentialsError
from styrmin_backend.services.unit_of_work import UnitOfWork


async def authenticate(
    uow: UnitOfWork, username: str, password: str
) -> tuple[User, SessionModel, str]:
    """Authenticate by username/password and mint a session.

    Returns ``(user, session_row, raw_token)``. Raises
    :class:`InvalidCredentialsError` for nonexistent users, wrong passwords,
    and deactivated accounts — the error shape is identical across all three
    to close the username-enumeration channel.
    """
    canonical = username.casefold()
    # Eager-load groups so downstream serialisation (User.effectiveRole,
    # User.groups) can read the relationship without hitting an async
    # lazy-load and tripping MissingGreenlet.
    result = await uow.session.exec(
        select(User)
        .where(User.username == canonical)
        .options(selectinload(User.groups))  # type: ignore[arg-type]
    )
    user = result.first()
    if user is None:
        raise InvalidCredentialsError
    if not user.active:
        raise InvalidCredentialsError
    if not verify_password(user.password_hash, password):
        raise InvalidCredentialsError

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        uow.session.add(user)
        await uow.session.commit()
        await uow.session.refresh(user)

    session_row, raw_token = await create_session(uow.session, user.id)
    return user, session_row, raw_token
