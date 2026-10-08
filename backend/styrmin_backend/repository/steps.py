"""Storage of steps (spec 019). Only the step recorder and step reads use it."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, nulls_last, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import aliased
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import SelectOfScalar

from styrmin_backend.db.models import Step as StepModel
from styrmin_backend.db.models import StepKind as StepKindModel
from styrmin_backend.db.models import StepStatus as StepStatusModel
from styrmin_backend.db.models import Task as TaskModel
from styrmin_backend.domain.models import Step as StepEntity
from styrmin_backend.domain.models import StepError, StepParent
from styrmin_backend.domain.models import StepKind as StepKindEntity
from styrmin_backend.domain.models import StepStatus as StepStatusEntity

_OPEN_STATUSES = (StepStatusModel.PENDING, StepStatusModel.RUNNING)


class StepRepository(ABC):
    """Repository of steps. Lists are ordered by start time, pending steps last.

    A task is older than another when it was created first; tasks created at the
    same time are ordered by id.
    """

    @abstractmethod
    async def get(self, id: UUID, for_update: bool = False) -> StepEntity | None:
        raise NotImplementedError

    @abstractmethod
    async def find_by_key(
        self, parent: StepParent, key: str, for_update: bool = False
    ) -> StepEntity | None:
        raise NotImplementedError

    @abstractmethod
    async def insert_if_absent(self, step: StepEntity) -> bool:
        """Insert the step unless its parent has one with the same key.

        Returns ``True`` when this call inserted the row.
        """
        raise NotImplementedError

    @abstractmethod
    async def list_by_task_ids(self, task_ids: Sequence[UUID]) -> list[StepEntity]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_backup(self, backup_id: UUID) -> list[StepEntity]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_backup_ids(self, backup_ids: Sequence[UUID]) -> list[StepEntity]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_restore(self, restore_id: UUID) -> list[StepEntity]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_restore_ids(
        self, restore_ids: Sequence[UUID]
    ) -> list[StepEntity]:
        raise NotImplementedError

    @abstractmethod
    async def list_open_operator_steps_of_older_tasks(
        self, task_id: UUID, for_update: bool = False
    ) -> list[StepEntity]:
        """Pending or running operator-phase steps of the tasks older than the task.

        Only the tasks of the task's deployment count.
        """
        raise NotImplementedError

    @abstractmethod
    async def find_first_newer_task_with_succeeded_step(
        self, task_id: UUID, keys: Sequence[str]
    ) -> UUID | None:
        """The oldest task newer than the task with a succeeded step of one of ``keys``.

        Only the tasks of the task's deployment count.
        """
        raise NotImplementedError

    @abstractmethod
    async def save(self, step: StepEntity) -> None:
        raise NotImplementedError


def _parent_column(parent: StepParent) -> tuple[str, UUID]:
    for column in ("task_id", "backup_id", "restore_id"):
        parent_id = getattr(parent, column)
        if parent_id is not None:
            return column, parent_id
    raise ValueError("A step parent has no id")  # StepParent forbids this.


def _utc(value: datetime | None) -> datetime | None:
    # SQLite returns naive datetimes; every stored time is UTC.
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _older(task: Any, than: Any) -> ColumnElement[bool]:
    """``task`` was created before ``than``; the id orders tasks created at the same time."""
    return or_(
        col(task.created_on) < col(than.created_on),
        and_(
            col(task.created_on) == col(than.created_on),
            col(task.id) < col(than.id),
        ),
    )


def _ordered(
    statement: SelectOfScalar[StepModel],
) -> SelectOfScalar[StepModel]:
    return statement.order_by(
        nulls_last(col(StepModel.started_at).asc()), col(StepModel.created_on).asc()
    )


class SQLModelStepRepository(StepRepository):
    """The async SQLModel step repository."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _column_values(step: StepEntity) -> dict[str, Any]:
        values: dict[str, Any] = {
            "id": step.id,
            "task_id": step.parent.task_id,
            "backup_id": step.parent.backup_id,
            "restore_id": step.parent.restore_id,
            "key": step.key,
            "name": step.name,
            "kind": StepKindModel(step.kind.value),
            "status": StepStatusModel(step.status.value),
            "started_at": step.started_at,
            "ended_at": step.ended_at,
            "attempt_count": step.attempt_count,
            "errors": [error.model_dump(mode="json") for error in step.errors] or None,
            "detail": step.detail,
            "rolled_back_at": step.rolled_back_at,
            "rollback_message": step.rollback_message,
            "output": step.output,
            "output_truncated": step.output_truncated,
            "superseded_by_task_id": step.superseded_by_task_id,
        }
        # Callers set ``created_on`` to order steps created in one transaction.
        if step.created_on is not None:
            values["created_on"] = step.created_on
        return values

    @staticmethod
    def _to_entity(model: StepModel) -> StepEntity:
        return StepEntity(
            id=model.id,
            parent=StepParent(
                task_id=model.task_id,
                backup_id=model.backup_id,
                restore_id=model.restore_id,
            ),
            key=model.key,
            name=model.name,
            kind=StepKindEntity(model.kind.value),
            status=StepStatusEntity(model.status.value),
            started_at=_utc(model.started_at),
            ended_at=_utc(model.ended_at),
            attempt_count=model.attempt_count,
            errors=[StepError.model_validate(error) for error in model.errors or []],
            detail=model.detail,
            rolled_back_at=_utc(model.rolled_back_at),
            rollback_message=model.rollback_message,
            output=model.output,
            output_truncated=model.output_truncated,
            superseded_by_task_id=model.superseded_by_task_id,
            created_on=_utc(model.created_on),
            updated_on=_utc(model.updated_on),
        )

    async def _exec(self, statement: SelectOfScalar[StepModel]) -> list[StepModel]:
        # Reload rows already in the session, so a locked read sees the stored values.
        result = await self.session.exec(
            statement.execution_options(populate_existing=True)
        )
        return list(result.all())

    async def _one(
        self, statement: SelectOfScalar[StepModel], for_update: bool
    ) -> StepEntity | None:
        if for_update:
            statement = statement.with_for_update()
        models = await self._exec(statement)
        return self._to_entity(models[0]) if models else None

    async def _many(self, statement: SelectOfScalar[StepModel]) -> list[StepEntity]:
        return [
            self._to_entity(model) for model in await self._exec(_ordered(statement))
        ]

    async def get(self, id: UUID, for_update: bool = False) -> StepEntity | None:
        return await self._one(select(StepModel).where(StepModel.id == id), for_update)

    async def find_by_key(
        self, parent: StepParent, key: str, for_update: bool = False
    ) -> StepEntity | None:
        column, parent_id = _parent_column(parent)
        statement = select(StepModel).where(
            getattr(StepModel, column) == parent_id, StepModel.key == key
        )
        return await self._one(statement, for_update)

    async def insert_if_absent(self, step: StepEntity) -> bool:
        # A core insert does not autoflush; the parent may be pending in this session.
        await self.session.flush()
        column, _ = _parent_column(step.parent)
        dialect = self.session.bind.dialect.name  # type: ignore[union-attr]
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        table = StepModel.__table__  # type: ignore[attr-defined]
        statement = (
            insert(table)
            .values(**self._column_values(step))
            .on_conflict_do_nothing(
                index_elements=[column, "key"],
                index_where=text(f"{column} IS NOT NULL"),
            )
            .returning(table.c.id)
        )
        result = await self.session.exec(statement)
        return result.scalar() is not None

    async def list_by_task_ids(self, task_ids: Sequence[UUID]) -> list[StepEntity]:
        if not task_ids:
            return []
        return await self._many(
            select(StepModel).where(col(StepModel.task_id).in_(task_ids))
        )

    async def list_by_backup(self, backup_id: UUID) -> list[StepEntity]:
        return await self.list_by_backup_ids([backup_id])

    async def list_by_backup_ids(self, backup_ids: Sequence[UUID]) -> list[StepEntity]:
        if not backup_ids:
            return []
        return await self._many(
            select(StepModel).where(col(StepModel.backup_id).in_(backup_ids))
        )

    async def list_by_restore(self, restore_id: UUID) -> list[StepEntity]:
        return await self.list_by_restore_ids([restore_id])

    async def list_by_restore_ids(
        self, restore_ids: Sequence[UUID]
    ) -> list[StepEntity]:
        if not restore_ids:
            return []
        return await self._many(
            select(StepModel).where(col(StepModel.restore_id).in_(restore_ids))
        )

    async def list_open_operator_steps_of_older_tasks(
        self, task_id: UUID, for_update: bool = False
    ) -> list[StepEntity]:
        newer = aliased(TaskModel)
        statement = (
            select(StepModel)
            .join(TaskModel, col(TaskModel.id) == col(StepModel.task_id))
            .join(newer, col(newer.deployment_id) == col(TaskModel.deployment_id))
            .where(
                newer.id == task_id,
                _older(TaskModel, newer),
                StepModel.kind == StepKindModel.OPERATOR_PHASE,
                col(StepModel.status).in_(_OPEN_STATUSES),
            )
        )
        if for_update:
            statement = statement.with_for_update(of=StepModel)
        return await self._many(statement)

    async def find_first_newer_task_with_succeeded_step(
        self, task_id: UUID, keys: Sequence[str]
    ) -> UUID | None:
        older = aliased(TaskModel)
        statement = (
            select(TaskModel.id)
            .join(StepModel, col(StepModel.task_id) == col(TaskModel.id))
            .join(older, col(older.deployment_id) == col(TaskModel.deployment_id))
            .where(
                older.id == task_id,
                _older(older, TaskModel),
                col(StepModel.key).in_(keys),
                StepModel.status == StepStatusModel.SUCCEEDED,
            )
            .order_by(col(TaskModel.created_on).asc(), col(TaskModel.id).asc())
            .limit(1)
        )
        result = await self.session.exec(statement)
        return result.first()

    async def save(self, step: StepEntity) -> None:
        """Insert the step, or update the fields a step can change."""
        model = await self.session.get(StepModel, step.id)
        if model is None:
            self.session.add(StepModel(**self._column_values(step)))
            return
        values = self._column_values(step)
        for field in (
            "name",
            "status",
            "started_at",
            "ended_at",
            "attempt_count",
            "errors",
            "detail",
            "rolled_back_at",
            "rollback_message",
            "output",
            "output_truncated",
            "superseded_by_task_id",
        ):
            setattr(model, field, values[field])
        self.session.add(model)
