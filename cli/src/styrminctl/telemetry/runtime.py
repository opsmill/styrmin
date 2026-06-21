"""Telemetry integration hook.

:func:`run` is the single chokepoint the outer CLI wrapper delegates to. It:

1. resolves ``eligible`` from the tokens **best-effort** (never raises);
2. runs the inner app inside ``try/except/finally``, capturing the final
   outcome (success, or the propagated exception — including the auth boundary's
   ``SystemExit``);
3. classifies the outcome via :func:`categorize_error`;
4. if eligible, builds and dispatches exactly one scrubbed event;
5. **re-raises the original exception unchanged**.

The entire telemetry path is wrapped so any internal error is swallowed and the
command's stdout / stderr / exit code are byte-identical to the
telemetry-disabled case (FR-001, FR-004, SC-003).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from .config import resolve_endpoint
from .dispatch import dispatch as _real_dispatch
from .eligibility import should_emit
from .envelope import build_envelope
from .errors import categorize_error
from .event import build_event

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from cyclopts import App

    from .store import TelemetryStore

    _DispatchFn = Callable[..., None]


def run(
    inner: Callable[[Sequence[str] | None], object],
    args: Sequence[str] | None,
    *,
    app: App,
    store: TelemetryStore,
    dispatch_fn: _DispatchFn = _real_dispatch,
) -> object:
    """Run ``inner(args)`` and emit one telemetry event around it.

    ``inner`` is the underlying CLI callable; ``args`` the raw token sequence
    (``None`` means "use ``sys.argv``", matching Cyclopts). ``app`` is used for
    closed-set command/option resolution and ``store`` supplies the
    ``install_id``. Returns ``inner``'s result, or re-raises its exception
    unchanged. ``dispatch_fn`` is injectable for tests.
    """
    tokens = _resolve_tokens(args)
    eligible = _safe_eligible(app=app, tokens=tokens, store=store)

    result: object = None
    error: BaseException | None = None
    try:
        result = inner(args)
    except BaseException as exc:  # noqa: BLE001 - observe every outcome, re-raise below
        error = exc

    if eligible:
        _emit(app=app, tokens=tokens, store=store, error=error, dispatch_fn=dispatch_fn)

    if error is not None:
        raise error
    return result


def _resolve_tokens(args: Sequence[str] | None) -> list[str]:
    """Return the token list to resolve command/options from (best-effort)."""
    if args is not None:
        return list(args)
    try:
        return list(sys.argv[1:])
    except Exception:  # noqa: BLE001 - telemetry resolution must never raise
        return []


def _safe_eligible(*, app: App, tokens: Sequence[str], store: TelemetryStore) -> bool:
    """Resolve eligibility, defaulting to ``False`` if anything goes wrong."""
    try:
        return should_emit(app=app, tokens=tokens, store=store)
    except Exception:  # noqa: BLE001 - never let telemetry resolution raise (FR-004)
        return False


def _emit(
    *,
    app: App,
    tokens: Sequence[str],
    store: TelemetryStore,
    error: BaseException | None,
    dispatch_fn: _DispatchFn,
) -> None:
    """Build and dispatch one event; swallow every telemetry-internal error."""
    try:
        outcome, error_category = categorize_error(error)
        data: Mapping[str, Any] = build_event(
            app=app,
            tokens=tokens,
            install_id=store.install_id(),
            outcome=outcome,
            error_category=error_category,
        )
        envelope = build_envelope(dict(data))
        dispatch_fn(envelope, resolve_endpoint())
    except Exception:  # noqa: BLE001, S110 - telemetry never perturbs the command (FR-004)
        pass
