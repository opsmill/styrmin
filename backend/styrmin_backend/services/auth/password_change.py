"""Password rotation. See ADR-024, issue #189.

The mutation flow:

1. Verify ``current_password`` against the calling user's hash.
2. Hash the new password with current argon2 parameters (also enforces the
   length policy).
3. Persist the new hash and delete every other session for the user in the
   same commit — rotating credentials must kick off any other device whose
   token might already be compromised, while preserving the calling session
   so the user is not logged out of the device they're rotating from.
"""

from __future__ import annotations

from uuid import UUID

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import User
from styrmin_backend.services.auth.password import (
    hash_password,
    verify_password,
)
from styrmin_backend.services.auth.session import (
    delete_other_sessions_for_user,
)
from styrmin_backend.services.exceptions import InvalidCredentialsError


async def change_password(
    db_session: AsyncSession,
    *,
    user: User,
    current_password: str,
    new_password: str,
    calling_session_id: UUID,
) -> int:
    """Rotate ``user``'s password and revoke every other session.

    Returns the number of other sessions invalidated. Raises
    :class:`InvalidCredentialsError` when ``current_password`` does not
    verify against the stored hash — same code as a failed login so the
    error surface stays uniform.
    """
    if not verify_password(user.password_hash, current_password):
        raise InvalidCredentialsError

    user.password_hash = hash_password(new_password)
    db_session.add(user)
    invalidated = await delete_other_sessions_for_user(
        db_session, user.id, except_session_id=calling_session_id
    )
    await db_session.commit()
    await db_session.refresh(user)

    logger.info(
        "password_changed user_id={} other_sessions_invalidated={}",
        user.id,
        invalidated,
    )
    return invalidated
