"""GraphQL types of steps (spec 019, contracts/graphql.md)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

import strawberry

from styrmin_backend.domain.models import Step as StepEntity
from styrmin_backend.domain.models import StepError as StepErrorEntity
from styrmin_backend.domain.models import StepEvent as StepEventEntity
from styrmin_backend.domain.models import StepKind as StepKindEntity
from styrmin_backend.domain.models import StepStatus as StepStatusEntity
from styrmin_backend.domain.models import Task as TaskEntity
from styrmin_backend.domain.models import TaskResult as TaskResultEntity
from styrmin_backend.services.steps.reads import get_no_report_since, get_started_tasks
from styrmin_backend.services.steps.recorder import StepRecord
from styrmin_backend.services.tasks import get_task

if TYPE_CHECKING:
    from styrmin_backend.api.definitions.task.model import Task

StepStatus = strawberry.enum(StepStatusEntity, name="StepStatus")
StepKind = strawberry.enum(StepKindEntity, name="StepKind")
StepEvent = strawberry.enum(StepEventEntity, name="StepEvent")
TaskResult = strawberry.enum(TaskResultEntity, name="TaskResult")

_TASK_MODULE = "styrmin_backend.api.definitions.task.model"


class NotLoaded(Enum):
    """Marks a view field that a read model did not fill, so its resolver queries."""

    NOT_LOADED = "not_loaded"


NOT_LOADED = NotLoaded.NOT_LOADED
_NotLoaded = Literal[NotLoaded.NOT_LOADED]


@strawberry.type
class StepError:
    attempt: int
    message: str
    occurred_at: datetime

    @classmethod
    def from_instance(cls, instance: StepErrorEntity) -> StepError:
        return cls(
            attempt=instance.attempt,
            message=instance.message,
            occurred_at=instance.occurred_at,
        )


@strawberry.type(description="One unit of work inside a task, a backup or a restore.")
class Step:
    id: UUID
    key: str
    name: str
    kind: StepKind
    status: StepStatus
    started_at: datetime | None = None
    ended_at: datetime | None = None
    attempt_count: int
    errors: list[StepError] = strawberry.field(
        description="The error of each failed attempt, oldest first."
    )
    detail: str | None = strawberry.field(
        default=None,
        description="FluxCD's current reason and message, HelmRelease step only.",
    )
    rolled_back_at: datetime | None = None
    rollback_message: str | None = None
    output: str | None = strawberry.field(
        default=None,
        description=(
            "End of a failed command's output. Request it only for one step at a time."
        ),
    )
    output_truncated: bool
    task_id: UUID | None = None
    backup_id: UUID | None = None
    restore_id: UUID | None = None

    instance: strawberry.Private[StepEntity]
    superseded_by_view: strawberry.Private[TaskEntity | None | _NotLoaded] = NOT_LOADED
    started_tasks_view: strawberry.Private[list[TaskEntity] | _NotLoaded] = NOT_LOADED
    no_report_since_view: strawberry.Private[datetime | None | _NotLoaded] = NOT_LOADED

    @strawberry.field(
        description="Seconds between startedAt and endedAt; null until both are set."
    )
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds()

    @strawberry.field(description="The newest error, or null.")
    def error(self) -> str | None:
        return self.errors[-1].message if self.errors else None

    @strawberry.field
    def has_output(self) -> bool:
        return bool(self.instance.output)

    @strawberry.field(description="The later task that interrupted this step.")
    async def superseded_by(
        self, info: strawberry.Info
    ) -> Annotated["Task", strawberry.lazy(_TASK_MODULE)] | None:
        from styrmin_backend.api.definitions.task.model import Task

        task_id = self.instance.superseded_by_task_id
        if task_id is None:
            return None
        task = self.superseded_by_view
        if task is NOT_LOADED:
            task = await get_task(task_id=task_id, uow=info.context["uow"])
        return Task.from_instance(task) if task is not None else None

    @strawberry.field(description="Tasks that this hook step started.")
    async def started_tasks(
        self, info: strawberry.Info
    ) -> list[Annotated["Task", strawberry.lazy(_TASK_MODULE)]]:
        from styrmin_backend.api.definitions.task.model import Task

        tasks = self.started_tasks_view
        if tasks is NOT_LOADED:
            tasks = await get_started_tasks(step_id=self.id, uow=info.context["uow"])
        return [Task.from_instance(task) for task in tasks]

    @strawberry.field(
        description=(
            "Set while a running operator-phase step has had no agent report "
            "for more than 60 seconds."
        )
    )
    async def no_report_since(self, info: strawberry.Info) -> datetime | None:
        if self.no_report_since_view is not NOT_LOADED:
            return self.no_report_since_view
        return await get_no_report_since(self.instance, uow=info.context["uow"])

    @classmethod
    def from_instance(
        cls,
        instance: StepEntity,
        *,
        superseded_by: TaskEntity | None | _NotLoaded = NOT_LOADED,
        started_tasks: list[TaskEntity] | _NotLoaded = NOT_LOADED,
        no_report_since: datetime | None | _NotLoaded = NOT_LOADED,
    ) -> Step:
        """Build the type; a read model passes the views it computed for many steps."""
        return cls(
            id=instance.id,
            key=instance.key,
            name=instance.name,
            kind=instance.kind,
            status=instance.status,
            started_at=instance.started_at,
            ended_at=instance.ended_at,
            attempt_count=instance.attempt_count,
            errors=[StepError.from_instance(error) for error in instance.errors],
            detail=instance.detail,
            rolled_back_at=instance.rolled_back_at,
            rollback_message=instance.rollback_message,
            output=instance.output,
            output_truncated=instance.output_truncated,
            task_id=instance.task_id,
            backup_id=instance.backup_id,
            restore_id=instance.restore_id,
            instance=instance,
            superseded_by_view=superseded_by,
            started_tasks_view=started_tasks,
            no_report_since_view=no_report_since,
        )


@strawberry.input
class RecordStepInput:
    step_id: UUID | None = strawberry.field(
        default=None,
        description="Address an existing step. Use instead of a parent and key.",
    )
    task_id: UUID | None = None
    backup_id: UUID | None = None
    restore_id: UUID | None = None
    key: str | None = None
    name: str | None = strawberry.field(
        default=None,
        description="Required with STARTED when the step does not exist yet.",
    )
    kind: StepKind | None = None
    event: StepEvent
    error: str | None = strawberry.field(
        default=None, description="Required with FAILED."
    )
    output: str | None = strawberry.field(
        default=None, description="Used with OUTPUT, and allowed with FAILED."
    )
    output_truncated: bool = False
    occurred_at: datetime | None = strawberry.field(
        default=None,
        description=(
            "When the event happened, in the writer's clock. "
            "Defaults to the server's time."
        ),
    )

    def to_record(self) -> StepRecord:
        return StepRecord(
            event=self.event,
            step_id=self.step_id,
            task_id=self.task_id,
            backup_id=self.backup_id,
            restore_id=self.restore_id,
            key=self.key,
            name=self.name,
            kind=self.kind,
            error=self.error,
            output=self.output,
            output_truncated=self.output_truncated,
            occurred_at=self.occurred_at,
        )
