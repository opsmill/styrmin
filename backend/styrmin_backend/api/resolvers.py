from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

import strawberry

from styrmin_backend.services.exceptions import ServiceError

T = TypeVar("T")


async def resolve_related(
    info: strawberry.Info,
    repo_attr: str,
    entity_id: UUID,
    type_cls: type[T],
    error_cls: type[ServiceError],
    method: str = "get",
) -> T:
    """Fetch a related entity via UoW and convert it to a Strawberry type.

    Raises *error_cls* when the entity is not found.
    """
    uow: Any = info.context["uow"]
    async with uow:
        repo = getattr(uow, repo_attr)
        entity = await getattr(repo, method)(entity_id)
        if entity is None:
            raise error_cls()
        return type_cls.from_instance(entity)  # type: ignore[attr-defined,return-value]
