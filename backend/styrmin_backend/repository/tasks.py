from abc import ABC, abstractmethod
from uuid import UUID

from sqlmodel import desc, select

from styrmin_backend.db.models import Task as TaskModel
from styrmin_backend.db.models import TaskStatus as TaskStatusModel
from styrmin_backend.db.models import TaskType as TaskTypeModel
from styrmin_backend.domain.models import Task as TaskEntity
from styrmin_backend.domain.models import TaskStatus as TaskStatusEntity
from styrmin_backend.domain.models import TaskType as TaskTypeEntity
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class TaskRepository(BaseRepository[TaskModel], ABC):
    """Repository specific to tasks."""

    @abstractmethod
    async def save(self, task: TaskEntity) -> None:
        raise NotImplementedError(
            "The save method must be implemented in the subclass."
        )

    @abstractmethod
    async def find(self, id: UUID) -> TaskEntity | None:
        raise NotImplementedError(
            "The find method must be implemented in the subclass."
        )

    @abstractmethod
    async def all(self) -> list[TaskEntity]:
        """Get all tasks."""
        raise NotImplementedError("The all method must be implemented in the subclass.")

    @abstractmethod
    async def find_by_deployment(self, deployment_id: UUID) -> list[TaskEntity]:
        """Get all tasks for a deployment, ordered newest-first."""
        raise NotImplementedError(
            "The find_by_deployment method must be implemented in the subclass."
        )


class SQLModelTaskRepository(BaseSQLModelRepository[TaskModel], TaskRepository):
    """The async SQLmodel task repository."""

    model_class = TaskModel

    def _to_model(self, task: TaskEntity) -> TaskModel:
        """Convert a domain model to a SQLModel."""
        return TaskModel(
            id=task.id,
            status=TaskStatusModel(task.status.value),
            type=TaskTypeModel(task.type.value),
            message=task.message,
            parameters=task.parameters,
            prefect_flow_run_id=task.prefect_flow_run_id,
            deployment_id=task.deployment_id,
        )

    def _to_entity(self, task: TaskModel) -> TaskEntity:
        """Convert a SQLModel to a domain model."""
        return TaskEntity(
            id=task.id,
            status=TaskStatusEntity(task.status.value),
            type=TaskTypeEntity(task.type.value),
            message=task.message,
            parameters=task.parameters,
            prefect_flow_run_id=task.prefect_flow_run_id,
            deployment_id=task.deployment_id,
            created_on=task.created_on,
            updated_on=task.updated_on,
        )

    async def save(self, task: TaskEntity) -> None:
        """Save a task to the database."""
        task_model = self._to_model(task)
        await self.session.merge(task_model)

    async def find(self, id: UUID) -> TaskEntity | None:
        result = await self.session.exec(
            select(self.model_class).where(self.model_class.id == id)
        )
        entity = result.first()

        if entity is not None:
            return self._to_entity(entity)

        return None

    async def all(self) -> list[TaskEntity]:
        """Get all tasks."""
        statement = select(self.model_class)
        result = await self.session.exec(statement)
        tasks = result.all()
        return [self._to_entity(task) for task in tasks]

    async def find_by_deployment(self, deployment_id: UUID) -> list[TaskEntity]:
        """Get all tasks for a deployment, ordered newest-first."""
        statement = (
            select(self.model_class)
            .where(self.model_class.deployment_id == deployment_id)
            .order_by(desc(self.model_class.created_on))
        )
        result = await self.session.exec(statement)
        tasks = result.all()
        return [self._to_entity(task) for task in tasks]
