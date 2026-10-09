"""Per-request data loaders.

A loader collects the keys that resolvers ask for while one GraphQL response is
built and reads them all with one query. A field the caller did not request
reads nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING
from uuid import UUID

import strawberry
from strawberry.dataloader import DataLoader

from styrmin_backend.domain.models import Step
from styrmin_backend.services.instances import get_instances_by_ids
from styrmin_backend.services.steps.reads import (
    list_steps_by_backup,
    list_steps_by_restore,
)

if TYPE_CHECKING:
    from styrmin_backend.db.models import ApplicationInstance
    from styrmin_backend.services.unit_of_work import UnitOfWork

type StepsLoader = DataLoader[UUID, list[Step]]
type InstancesLoader = DataLoader[UUID, ApplicationInstance | None]
type _StepsByParent = Callable[
    [Sequence[UUID], UnitOfWork], Awaitable[dict[UUID, list[Step]]]
]


def backup_steps(info: strawberry.Info) -> StepsLoader:
    """The steps of every backup in the response, by backup id, in one query."""
    return _steps_loader(info, "backup_steps", list_steps_by_backup)


def restore_steps(info: strawberry.Info) -> StepsLoader:
    """The steps of every restore in the response, by restore id, in one query."""
    return _steps_loader(info, "restore_steps", list_steps_by_restore)


def application_instances(info: strawberry.Info) -> InstancesLoader:
    """The application instances the response refers to, by id, in one query.

    A missing instance loads as ``None``.
    """
    loaders: dict[str, InstancesLoader] = info.context.setdefault("loaders", {})
    loader = loaders.get("application_instances")
    if loader is None:
        uow = info.context["uow"]

        async def load(instance_ids: list[UUID]) -> list[ApplicationInstance | None]:
            instances = await get_instances_by_ids(instance_ids, uow)
            return [instances.get(instance_id) for instance_id in instance_ids]

        loader = loaders["application_instances"] = DataLoader(
            load_fn=load, cache=False
        )
    return loader


def _steps_loader(
    info: strawberry.Info, name: str, steps_by_parent: _StepsByParent
) -> StepsLoader:
    loaders: dict[str, StepsLoader] = info.context.setdefault("loaders", {})
    loader = loaders.get(name)
    if loader is None:
        uow = info.context["uow"]

        async def load(parent_ids: list[UUID]) -> list[list[Step]]:
            steps = await steps_by_parent(parent_ids, uow)
            return [steps.get(parent_id, []) for parent_id in parent_ids]

        # No cache, so a mutation that runs after another one reads fresh steps.
        loader = loaders[name] = DataLoader(load_fn=load, cache=False)
    return loader
