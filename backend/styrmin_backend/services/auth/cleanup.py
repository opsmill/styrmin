"""Bulk deletion of expired session rows. See ADR-024.

Lazy invalidation in :func:`styrmin_backend.services.auth.session.lookup_session`
is the source of truth for "is this token still valid?" — but a row whose token
is never presented again would otherwise live until the absolute 30-day cap.
This module provides the belt-and-suspenders sweep that the daily Prefect
cleanup flow runs to keep the table from growing unboundedly.
"""

from __future__ import annotations

import warnings
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete
from sqlmodel import or_
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Session as SessionModel
from styrmin_backend.services.auth.session import IDLE_LIFETIME


async def delete_expired_sessions(db_session: AsyncSession) -> int:
    """Delete every session row that is past its absolute or idle expiry.

    Returns the number of rows deleted. Idempotent — a second call against an
    already-clean table is a zero-row delete.
    """
    now = datetime.now(UTC)
    idle_cutoff = now - IDLE_LIFETIME
    stmt = (
        delete(SessionModel)
        .where(
            or_(
                SessionModel.expires_at <= now,
                SessionModel.last_used_at <= idle_cutoff,
            )
        )
        # Skip in-memory synchronization: SQLite strips tzinfo from persisted
        # datetimes, which makes SQLAlchemy's evaluator trip on naive-vs-aware
        # comparisons against any session-loaded rows. The DELETE itself is
        # dialect-aware.
        .execution_options(synchronize_session=False)
    )
    # SQLModel's exec() does not accept DML; INSERT/DELETE go through execute().
    # The accompanying deprecation warning is a false positive.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = await db_session.execute(stmt)  # ty: ignore[deprecated]
    await db_session.commit()
    return cast(int, result.rowcount or 0)
