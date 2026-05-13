"""Server-side session token minting and lookup. See ADR-019."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Session as SessionModel

ABSOLUTE_LIFETIME = timedelta(days=30)
IDLE_LIFETIME = timedelta(days=7)
SLIDING_REFRESH_DEBOUNCE = timedelta(seconds=60)


def mint_token() -> tuple[str, bytes]:
    """Return (raw_token, sha256_digest)."""
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("ascii")).digest()
    return raw, digest


def hash_token(raw_token: str) -> bytes:
    return hashlib.sha256(raw_token.encode("ascii")).digest()


async def create_session(
    db_session: AsyncSession, user_id: UUID
) -> tuple[SessionModel, str]:
    """Mint a session token and persist the session row.

    Returns the persisted row plus the raw token. The raw token is the only
    place outside the response where the unhashed value exists; callers must
    hand it to the transport and discard it.
    """
    raw, digest = mint_token()
    now = datetime.now(UTC)
    session_row = SessionModel(
        user_id=user_id,
        token_hash=digest,
        created_at=now,
        last_used_at=now,
        expires_at=now + ABSOLUTE_LIFETIME,
    )
    db_session.add(session_row)
    await db_session.commit()
    await db_session.refresh(session_row)
    return session_row, raw


async def lookup_session(
    db_session: AsyncSession, raw_token: str
) -> SessionModel | None:
    """Look up a session by raw token. Returns None if missing or expired.

    Lazy-invalidation: an expired session is deleted in the same transaction
    and ``None`` is returned. The daily cleanup task is belt-and-suspenders
    for rows that are never looked up again.
    """
    digest = hash_token(raw_token)
    result = await db_session.exec(
        select(SessionModel).where(SessionModel.token_hash == digest)
    )
    session_row = result.first()
    if session_row is None:
        return None
    now = datetime.now(UTC)
    expires_at = _ensure_aware(session_row.expires_at)
    last_used_at = _ensure_aware(session_row.last_used_at)
    if now >= expires_at or now >= last_used_at + IDLE_LIFETIME:
        await db_session.delete(session_row)
        await db_session.commit()
        return None
    return session_row


async def touch_session(db_session: AsyncSession, session_row: SessionModel) -> bool:
    """Sliding refresh: advance ``last_used_at`` if the debounce window has elapsed.

    Returns ``True`` when the row was updated. Skips the write when the previous
    update happened within :data:`SLIDING_REFRESH_DEBOUNCE` to avoid hot-row
    contention on busy users — see ADR-019.
    """
    now = datetime.now(UTC)
    last_used_at = _ensure_aware(session_row.last_used_at)
    if now - last_used_at < SLIDING_REFRESH_DEBOUNCE:
        return False
    session_row.last_used_at = now
    db_session.add(session_row)
    await db_session.commit()
    await db_session.refresh(session_row)
    return True


async def delete_session_by_token(db_session: AsyncSession, raw_token: str) -> bool:
    """Delete the session row for ``raw_token``. Returns whether one was deleted."""
    digest = hash_token(raw_token)
    result = await db_session.exec(
        select(SessionModel).where(SessionModel.token_hash == digest)
    )
    session_row = result.first()
    if session_row is None:
        return False
    await db_session.delete(session_row)
    await db_session.commit()
    return True


async def delete_all_sessions_for_user(db_session: AsyncSession, user_id: UUID) -> int:
    """Delete every session belonging to ``user_id``. Returns the count deleted.

    The caller owns the transaction: this helper stages the deletes but
    does not commit. Pairing the session-delete with the originating
    write (deactivate / role-change / password-reset) in a single commit
    is what makes the operation atomic — if the write succeeds and the
    delete fails (or vice versa) we must roll BOTH back. See research.md
    §D15 and the audit comment in ``services/auth/users.py`` /
    ``services/auth/password_change.py``.
    """
    result = await db_session.exec(
        select(SessionModel).where(SessionModel.user_id == user_id)
    )
    rows = list(result.all())
    for row in rows:
        await db_session.delete(row)
    return len(rows)


async def delete_other_sessions_for_user(
    db_session: AsyncSession, user_id: UUID, *, except_session_id: UUID
) -> int:
    """Delete every session for ``user_id`` other than ``except_session_id``.

    Caller-preserving variant used by ``changePassword``: rotating credentials
    must kick off any other device whose token might already be compromised
    without logging the user out of the device they're rotating from.

    Caller owns the transaction; see :func:`delete_all_sessions_for_user`.
    """
    result = await db_session.exec(
        select(SessionModel)
        .where(SessionModel.user_id == user_id)
        .where(SessionModel.id != except_session_id)
    )
    rows = list(result.all())
    for row in rows:
        await db_session.delete(row)
    return len(rows)


def _ensure_aware(value: datetime) -> datetime:
    """SQLite drops tzinfo; reattach UTC so comparisons against now() work."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
