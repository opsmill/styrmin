from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends, Request, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import User
from styrmin_backend.db.utils import get_session
from styrmin_backend.services.auth.session import lookup_session
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


async def _resolve_current_user(request: Request, session: AsyncSession) -> User | None:
    token = _extract_token(request)
    if token is None:
        return None
    session_row = await lookup_session(session, token)
    if session_row is None:
        return None
    return await session.get(User, session_row.user_id)


async def get_context(
    request: Request,
    response: Response,
    uow: SqlModelUnitOfWork = Depends(get_unit_of_work_dependency),
) -> dict[str, Any]:
    current_user = await _resolve_current_user(request, uow.session)
    return {
        "uow": uow,
        "request": request,
        "response": response,
        "current_user": current_user,
    }
