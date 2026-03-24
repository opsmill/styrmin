from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from functools import partial, wraps
from typing import Any

from typer import Typer


class AsyncTyper(Typer):
    @staticmethod
    def maybe_run_async(decorator: Callable, func: Callable) -> Any:  # noqa: ANN401
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            def runner(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
                return asyncio.run(func(*args, **kwargs))

            decorator(runner)
        else:
            decorator(func)
        return func

    def callback(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        decorator = super().callback(*args, **kwargs)
        return partial(self.maybe_run_async, decorator)

    def command(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        decorator = super().command(*args, **kwargs)
        return partial(self.maybe_run_async, decorator)
