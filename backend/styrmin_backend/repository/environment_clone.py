"""Repository for the environment clone record.

Like the environment backup/restore parents, ``EnvironmentClone`` stores no
status — but unlike them its terminality is **not** expressible as a SQL
``EXISTS``: it folds the backing capture's own derived status, whether the
created environment still exists, the constituent ``Restore`` rows reachable
only through JSON ``deployment_results[].restore_id`` values, and the
``clone_errors`` entries. So the guards and resolvers load the candidate clone
rows and derive in Python (the candidate set is tiny — the clones of one
environment), and this repository's job is to make that cheap: every read
eager-loads what the derivation touches, and the restore rows behind the JSON
ids are fetched for a whole batch of clones with a single ``IN`` query instead
of one query per entry.
"""

from abc import ABC, abstractmethod
from typing import Any, Sequence
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import selectinload
from sqlmodel import select

from styrmin_backend.db.models import (
    EnvironmentBackup,
    EnvironmentClone,
    Restore,
)
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


def referenced_restore_ids(clones: Sequence[EnvironmentClone]) -> set[UUID]:
    """Collect the ``Restore`` ids referenced by a batch of clones.

    The ids live inside the JSON ``deployment_results`` entries, where the
    service writes them as strings (JSON has no UUID type). Entries without a
    dispatched restore carry no ``restore_id`` or a null one and are skipped.

    An id that does not parse as a UUID is skipped with a warning rather than
    raising: the value can only come from a historical row, and one unreadable
    entry must not break every read of the clone. The derivation treats an
    unresolvable reference the same way it treats a cascade-deleted restore —
    the entry's recorded outcome stands (see ``data-model.md``).
    """
    ids: set[UUID] = set()
    for clone in clones:
        for entry in clone.deployment_results or []:
            if not isinstance(entry, dict):
                logger.warning(
                    "Ignoring malformed deployment_results entry on clone {}: {!r}",
                    clone.id,
                    entry,
                )
                continue
            raw = entry.get("restore_id")
            if raw is None:
                continue
            if isinstance(raw, UUID):
                ids.add(raw)
                continue
            try:
                ids.add(UUID(str(raw)))
            except ValueError:
                logger.warning(
                    "Ignoring unparseable restore_id {!r} on clone {}", raw, clone.id
                )
    return ids


class EnvironmentCloneRepository(BaseRepository[EnvironmentClone], ABC):
    """Repository specific to environment clones."""

    @abstractmethod
    async def save(self, clone: EnvironmentClone) -> EnvironmentClone:
        """Persist changes to a clone record."""
        raise NotImplementedError()

    @abstractmethod
    async def get_by_source_environment_id(
        self, environment_id: UUID
    ) -> Sequence[EnvironmentClone]:
        """Get the clones made *from* an environment, newest first."""
        raise NotImplementedError()

    @abstractmethod
    async def get_by_created_environment_id(
        self, environment_id: UUID
    ) -> Sequence[EnvironmentClone]:
        """Get the clones that created an environment, newest first."""
        raise NotImplementedError()

    @abstractmethod
    async def get_referenced_restores(
        self, clones: Sequence[EnvironmentClone]
    ) -> dict[UUID, Restore]:
        """Fetch the constituent restores of a batch of clones in one query."""
        raise NotImplementedError()


class SQLModelEnvironmentCloneRepository(
    BaseSQLModelRepository[EnvironmentClone], EnvironmentCloneRepository
):
    """The async SQLModel environment clone repository."""

    model_class = EnvironmentClone

    def _eager_load_options(self) -> list[Any]:
        """Eager-load everything a read of a clone touches.

        Deriving the clone's status reads the backing capture's *own* derived
        status, so the capture's constituent ``Backup`` rows are chained one
        level deeper; the two environments are loaded because every surface
        that renders a clone renders its provenance. Leaving any of them lazy
        would raise ``MissingGreenlet`` inside the async GraphQL resolvers.
        """
        return [
            selectinload(self.model_class.source_environment),  # type: ignore[arg-type]
            selectinload(self.model_class.created_environment),  # type: ignore[arg-type]
            selectinload(self.model_class.environment_backup).selectinload(  # type: ignore[arg-type]
                EnvironmentBackup.backups  # type: ignore[arg-type]
            ),
        ]

    async def get(self, id: UUID) -> EnvironmentClone | None:
        """Get a clone with its provenance and capture eagerly loaded."""
        statement = (
            select(self.model_class)
            .where(self.model_class.id == id)
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()

    async def save(self, clone: EnvironmentClone) -> EnvironmentClone:
        """Persist changes to a clone record.

        ``merge`` rather than ``add`` so a clone loaded in another session (the
        flow re-reads its row between steps) round-trips without the caller
        having to care which session owns the instance.
        """
        merged = await self.session.merge(clone)
        await self.session.flush()
        return merged

    async def get_by_source_environment_id(
        self, environment_id: UUID
    ) -> Sequence[EnvironmentClone]:
        """Get the clones made *from* an environment, newest first."""
        statement = (
            select(self.model_class)
            .where(self.model_class.source_environment_id == environment_id)
            .options(*self._eager_load_options())
            .order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        )
        result = await self.session.exec(statement)
        return result.all()

    async def get_by_created_environment_id(
        self, environment_id: UUID
    ) -> Sequence[EnvironmentClone]:
        """Get the clones that created an environment, newest first.

        At most one clone creates a given environment, but the lookup returns a
        sequence so the deletion cascade stays correct without depending on
        that: ``created_environment_id`` carries no unique constraint.
        """
        statement = (
            select(self.model_class)
            .where(self.model_class.created_environment_id == environment_id)
            .options(*self._eager_load_options())
            .order_by(self.model_class.created_on.desc())  # type: ignore[union-attr]
        )
        result = await self.session.exec(statement)
        return result.all()

    async def get_referenced_restores(
        self, clones: Sequence[EnvironmentClone]
    ) -> dict[UUID, Restore]:
        """Fetch the constituent restores of a batch of clones in one query.

        Keyed by restore id. A referenced id with no row — the restore cascaded
        away with its backup — is simply absent from the mapping, which is what
        lets the derivation keep the recorded outcome final instead of
        re-interpreting a missing input.
        """
        ids = referenced_restore_ids(clones)
        if not ids:
            return {}
        statement = select(Restore).where(Restore.id.in_(ids))  # type: ignore[attr-defined]
        result = await self.session.exec(statement)
        return {restore.id: restore for restore in result.all()}
