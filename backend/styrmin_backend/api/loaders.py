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
from styrmin_backend.services.steps.reads import (
    list_steps_by_backup,
    list_steps_by_restore,
)

if TYPE_CHECKING:
    from styrmin_backend.services.unit_of_work import UnitOfWork

type StepsLoader = DataLoader[UUID, list[Step]]
type _StepsByParent = Callable[
    [Sequence[UUID], UnitOfWork], Awaitable[dict[UUID, list[Step]]]
]


def backup_steps(info: strawberry.Info) -> StepsLoader:
    """The steps of every backup in the response, by backup id, in one query."""
    return _steps_loader(info, "backup_steps", list_steps_by_backup)


def restore_steps(info: strawberry.Info) -> StepsLoader:
    """The steps of every restore in the response, by restore id, in one query."""
    return _steps_loader(info, "restore_steps", list_steps_by_restore)


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
