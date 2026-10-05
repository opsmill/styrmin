from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any


def yield_unit_of_work(uow: Any) -> Callable[[], AbstractAsyncContextManager[Any]]:
    """Build a ``get_unit_of_work`` stand-in that enters ``uow`` but never closes it."""

    @asynccontextmanager
    async def _get_unit_of_work() -> AsyncGenerator[Any, None]:
        async with uow:
            yield uow

    return _get_unit_of_work
