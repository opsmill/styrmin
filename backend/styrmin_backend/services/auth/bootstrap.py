"""Default-admin bootstrap. See ADR-024.

Seeds a default admin row on startup so a fresh install is immediately
usable. Multi-replica safe via ``INSERT ... ON CONFLICT (username) DO
NOTHING RETURNING id``: only the replica that wins the insert race
observes the returned id and emits the generated-password log; losing
replicas exit silently.
"""

from __future__ import annotations

import secrets
import warnings
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend import config
from styrmin_backend.db.models import Role, User
from styrmin_backend.db.utils import get_async_engine
from styrmin_backend.services.auth.password import hash_password

DEFAULT_ADMIN_USERNAME = "admin"
_GENERATED_PASSWORD_BYTES = 24


def _build_insert(dialect_name: str):
    if dialect_name == "sqlite":
        return sqlite_insert
    if dialect_name == "postgresql":
        return pg_insert
    msg = f"Bootstrap does not support dialect: {dialect_name}"
    raise RuntimeError(msg)


async def bootstrap_default_admin(
    session: AsyncSession,
    *,
    username: str,
    password: str | None,
) -> UUID | None:
    """Insert a default admin if one does not exist for ``username``.

    Returns the new user's id when this call wins the insert race, or
    ``None`` when the username already exists (idempotent re-run, or
    another replica won). When ``password`` is ``None`` a random one is
    generated and logged at WARN level — exactly once, only on the
    winning call.
    """
    canonical = username.casefold()
    generated = password is None
    if generated:
        password = secrets.token_urlsafe(_GENERATED_PASSWORD_BYTES)

    password_hash = hash_password(password)

    dialect_name = session.bind.dialect.name  # type: ignore[union-attr]
    insert = _build_insert(dialect_name)
    stmt = (
        insert(User.__table__)
        .values(
            id=uuid4(),
            username=canonical,
            password_hash=password_hash,
            display_name=canonical,
            active=True,
            role=Role.ADMIN.name,
        )
        .on_conflict_do_nothing(index_elements=["username"])
        .returning(User.__table__.c.id)
    )
    # SQLModel's exec() is for SELECT; INSERT goes through execute(). The
    # accompanying deprecation warning is a false positive for DML.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = await session.execute(stmt)  # ty: ignore[deprecated]
    inserted_id = result.scalar()
    await session.commit()

    if inserted_id is None:
        return None

    if generated:
        logger.warning(
            "Bootstrapped admin user '{}' with a generated password "
            "(this line is logged ONCE — capture it now): {}",
            canonical,
            password,
        )
    else:
        logger.info(
            "Bootstrapped admin user '{}' from STYRMIN_ADMIN_PASSWORD", canonical
        )
    return inserted_id


async def bootstrap_default_admin_from_settings() -> None:
    """Read settings and seed the default admin. Called from ``app_initialization``."""
    settings = config.SETTINGS.active_settings
    async with AsyncSession(get_async_engine(), expire_on_commit=False) as session:
        await bootstrap_default_admin(
            session,
            username=settings.admin_username,
            password=settings.admin_password,
        )
