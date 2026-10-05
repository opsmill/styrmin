"""Short-lived API tokens for driver actions. See ADR-059."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta

from loguru import logger

from styrmin_backend.services.auth.bootstrap import ensure_actions_service_account
from styrmin_backend.services.auth.session import (
    create_session,
    delete_session_by_token,
)
from styrmin_backend.services.unit_of_work import get_unit_of_work

#: Expiry that applies only when the flow holding the token dies before revoking it.
ACTION_TOKEN_LIFETIME = timedelta(hours=24)


@asynccontextmanager
async def action_api_token() -> AsyncGenerator[str, None]:
    """Yield a session token for the actions service account; revoke it on exit."""
    async with get_unit_of_work() as uow:
        user_id = await ensure_actions_service_account(uow.session)
        _session_row, token = await create_session(
            uow.session, user_id, lifetime=ACTION_TOKEN_LIFETIME
        )
    try:
        yield token
    finally:
        # A revoke failure must not mask the flow's own outcome.
        try:
            async with get_unit_of_work() as uow:
                await delete_session_by_token(uow.session, token)
        except Exception:
            logger.exception(
                "Could not revoke a driver action token; it expires within {}",
                ACTION_TOKEN_LIFETIME,
            )
