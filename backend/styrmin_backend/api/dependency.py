from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends, Request, Response
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Session as SessionModel
from styrmin_backend.db.models import User
from styrmin_backend.db.utils import get_session
from styrmin_backend.services.auth.session import lookup_session, touch_session
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

SESSION_COOKIE_NAME = "styrmin_session"


async def get_unit_of_work_dependency(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[SqlModelUnitOfWork, None]:
    """FastAPI dependency that provides a UnitOfWork via DI session."""
    uow = SqlModelUnitOfWork(session=session)
    async with uow:
        yield uow


def _extract_token(request: Request) -> str | None:
    """Bearer header takes precedence over the session cookie. See ADR-019."""
    auth_header = request.headers.get("authorization") or request.headers.get(
        "Authorization"
    )
    if auth_header:
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() == "bearer" and token:
            return token
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return None


async def _resolve_current_user(
    request: Request, session: AsyncSession
) -> tuple[User | None, SessionModel | None]:
    """Returns ``(user, session_row)`` for the current request.

    ``session_row`` is exposed so resolvers like ``logout`` and
    ``changePassword`` can target the calling session specifically.
    """
    token = _extract_token(request)
    if token is None:
        return None, None
    session_row = await lookup_session(session, token)
    if session_row is None:
        return None, None
    await touch_session(session, session_row)
    # Eager-load groups so RequiresRole(effective_role) and the User
    # serialiser can read the membership without an async lazy-load.
    result = await session.exec(
        select(User)
        .where(User.id == session_row.user_id)
        .options(selectinload(User.groups))  # type: ignore[arg-type]
    )
    return result.first(), session_row


async def get_context(
    request: Request,
    response: Response,
    uow: SqlModelUnitOfWork = Depends(get_unit_of_work_dependency),
) -> dict[str, Any]:
    current_user, current_session = await _resolve_current_user(request, uow.session)
    return {
        "uow": uow,
        "request": request,
        "response": response,
        "current_user": current_user,
        "current_session": current_session,
    }
