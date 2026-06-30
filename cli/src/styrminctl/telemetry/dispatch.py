"""Best-effort, bounded telemetry dispatch.

:func:`dispatch` runs a synchronous ``httpx`` POST on a **daemon thread** and the
caller ``join``s that thread with the latency budget. If the join times out the
caller returns anyway and the worker is abandoned; because it is a daemon thread
the interpreter does not wait for it on exit (FR-002, FR-003, research R4).

The worker target wraps its entire body in ``try/except BaseException`` so a
hung or dying worker can never raise out of dispatch *and* can never print
``Exception ignored in thread ...`` at interpreter teardown (critique E2,
SC-003). There is no retry, batching, or on-disk spool (FR-001).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol, Self, cast

import httpx

from .config import TELEMETRY_BUDGET_MS

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from typing import Any


class _PostClient(Protocol):
    """Structural type for the subset of ``httpx.Client`` dispatch relies on.

    ``__enter__``/``__exit__`` make it usable as a context manager; ``post``
    takes a positional ``url`` and arbitrary keyword arguments. Kept minimal so
    both ``httpx.Client`` and lightweight test doubles satisfy it structurally.
    """

    def __enter__(self) -> Self: ...

    def __exit__(self, *exc: object) -> bool: ...

    def post(self, url: str, /, **kwargs: object) -> object: ...


def _default_client_factory() -> _PostClient:
    """Return an ``httpx.Client`` with tight per-phase timeouts.

    The per-phase timeouts keep a *progressing-but-slow* endpoint from running
    away; the daemon-thread + bounded-join in :func:`dispatch` provides the hard
    wall-clock cap that a per-phase timeout alone cannot (a hanging TCP connect
    can still exceed the budget without it).
    """
    client = httpx.Client(timeout=httpx.Timeout(connect=0.1, read=0.5, write=0.5, pool=0.1))
    # httpx.Client satisfies the _PostClient subset at runtime; the cast tells the
    # type checker so without coupling the Protocol to httpx's full signatures.
    return cast("_PostClient", client)


def dispatch(
    envelope: Mapping[str, Any],
    endpoint: str,
    *,
    budget_ms: int = TELEMETRY_BUDGET_MS,
    client_factory: Callable[[], _PostClient] = _default_client_factory,
) -> None:
    """Fire-and-forget a single POST of ``envelope`` to ``endpoint``.

    Spawns a daemon thread that performs exactly one POST, then joins it for at
    most ``budget_ms`` milliseconds. On timeout the caller returns immediately
    and the worker is abandoned (it is a daemon, so it never blocks exit). Never
    raises and never writes to stderr — every error, including one raised at
    interpreter teardown, is swallowed by the worker's top-level catch-all
    (FR-001-FR-004, critique E2).
    """

    def _worker() -> None:
        try:
            with client_factory() as client:
                client.post(endpoint, json=dict(envelope))
        except BaseException:  # noqa: BLE001, S110 - intentional total isolation (critique E2)
            # Swallow EVERYTHING: connection refused, timeouts, HTTP errors, and
            # interpreter-teardown errors. A daemon worker that lets an exception
            # escape would print "Exception ignored in thread ..." to stderr and
            # break the byte-identical-output guarantee (SC-003).
            pass

    thread = threading.Thread(target=_worker, name="styrminctl-telemetry", daemon=True)
    try:
        thread.start()
        thread.join(timeout=budget_ms / 1000)
    except BaseException:  # noqa: BLE001, S110 - dispatch itself must never raise (FR-004)
        pass
