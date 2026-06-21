"""Unit tests for the telemetry runtime hook (T011 / FR-001, FR-004, SC-003).

Covers :func:`styrminctl.telemetry.runtime.run`:

* exactly one event is built per eligible invocation, **after** the outcome is
  known (success and failure paths);
* stdout / stderr are byte-identical regardless of what the telemetry dispatch
  does -- a no-op, a real capture, or an exploding dispatch (SC-003);
* a raising command produces ``outcome == "failure"`` and the original
  exception is re-raised **unchanged**;
* any internal telemetry error is swallowed and never perturbs the command.
"""

from __future__ import annotations

import io
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

import pytest
from cyclopts import App
from styrminctl.telemetry import runtime
from styrminctl.telemetry.store import TelemetryStore

_Inner = Callable[[Sequence[str] | None], object]
_DispatchFn = Callable[..., None]


@pytest.fixture
def app() -> App:
    a = App(name="styrminctl")

    @a.command(name="ok")
    def ok() -> str:
        return "ok-result"

    @a.command(name="boom")
    def boom() -> None:
        raise ValueError("kaboom")

    return a


@pytest.fixture
def store(tmp_path: Path) -> TelemetryStore:
    # Enabled, writable store with a stable install_id.
    return TelemetryStore(path=tmp_path / "telemetry.json")


def _capture() -> tuple[list[dict[str, object]], _DispatchFn]:
    """Return a ``(captured_envelopes, dispatch_fn)`` pair."""
    captured: list[dict[str, object]] = []

    def fake_dispatch(envelope: dict[str, object], endpoint: str, **_kw: object) -> None:
        captured.append(envelope)

    return captured, fake_dispatch


def _data_of(envelope: dict[str, object]) -> dict[str, object]:
    """Return the envelope's ``data`` object, typed for key access."""
    data = envelope["data"]
    assert isinstance(data, dict)
    return cast("dict[str, object]", data)


def _noop_dispatch(_envelope: dict[str, object], _endpoint: str, **_kw: object) -> None:
    return None


def _exploding_dispatch(_envelope: dict[str, object], _endpoint: str, **_kw: object) -> None:
    raise RuntimeError("telemetry blew up")


def test_success_path_emits_exactly_one_event_after_outcome(app: App, store: TelemetryStore) -> None:
    captured, fake_dispatch = _capture()
    sentinel = object()

    def inner(_args: Sequence[str] | None) -> object:
        return sentinel

    result = runtime.run(inner, ["ok"], app=app, store=store, dispatch_fn=fake_dispatch)

    assert result is sentinel
    assert len(captured) == 1
    data = _data_of(captured[0])
    assert data["command"] == "ok"
    assert data["outcome"] == "success"
    assert data["error_category"] is None


def test_failure_path_emits_failure_then_reraises_unchanged(app: App, store: TelemetryStore) -> None:
    captured, fake_dispatch = _capture()
    original = ValueError("kaboom")

    def inner(_args: Sequence[str] | None) -> object:
        raise original

    with pytest.raises(ValueError) as exc_info:
        runtime.run(inner, ["boom"], app=app, store=store, dispatch_fn=fake_dispatch)

    # Re-raised unchanged (same instance).
    assert exc_info.value is original
    assert len(captured) == 1
    assert _data_of(captured[0])["outcome"] == "failure"


def test_systemexit_nonzero_is_failure_and_reraised(app: App, store: TelemetryStore) -> None:
    captured, fake_dispatch = _capture()
    original = SystemExit(1)

    def inner(_args: Sequence[str] | None) -> object:
        raise original

    with pytest.raises(SystemExit) as exc_info:
        runtime.run(inner, ["boom"], app=app, store=store, dispatch_fn=fake_dispatch)

    assert exc_info.value is original
    assert len(captured) == 1
    data = _data_of(captured[0])
    assert data["outcome"] == "failure"
    assert data["error_category"] == "usage"


def test_ineligible_command_emits_nothing(app: App, store: TelemetryStore) -> None:
    captured, fake_dispatch = _capture()

    def inner(_args: Sequence[str] | None) -> object:
        return None

    runtime.run(inner, ["--help"], app=app, store=store, dispatch_fn=fake_dispatch)
    assert captured == []


def test_internal_telemetry_error_is_swallowed(app: App, store: TelemetryStore) -> None:
    """A dispatch that raises must not perturb the command's return value."""
    sentinel = object()

    def inner(_args: Sequence[str] | None) -> object:
        return sentinel

    # Must not raise; command result preserved.
    result = runtime.run(inner, ["ok"], app=app, store=store, dispatch_fn=_exploding_dispatch)
    assert result is sentinel


def _run_capturing_io(
    inner: _Inner, tokens: list[str], app: App, store: TelemetryStore, dispatch_fn: _DispatchFn
) -> tuple[str, str, BaseException | None]:
    """Run ``runtime.run`` capturing stdout/stderr and any propagated exception."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    raised: BaseException | None = None
    try:
        runtime.run(inner, tokens, app=app, store=store, dispatch_fn=dispatch_fn)
    except BaseException as exc:  # noqa: BLE001 - recorded only for comparison
        raised = exc
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return out.getvalue(), err.getvalue(), raised


def test_stdout_stderr_identical_across_dispatch_outcomes_success(app: App, store: TelemetryStore) -> None:
    """SC-003: command output is identical whatever the telemetry dispatch does."""

    def inner(_args: Sequence[str] | None) -> object:
        print("hello stdout")
        print("hello stderr", file=sys.stderr)
        return "r"

    captured, fake_dispatch = _capture()
    noop_out, noop_err, _ = _run_capturing_io(inner, ["ok"], app, store, _noop_dispatch)
    cap_out, cap_err, _ = _run_capturing_io(inner, ["ok"], app, store, fake_dispatch)
    boom_out, boom_err, _ = _run_capturing_io(inner, ["ok"], app, store, _exploding_dispatch)

    assert noop_out == cap_out == boom_out == "hello stdout\n"
    assert noop_err == cap_err == boom_err == "hello stderr\n"
    assert len(captured) == 1  # the real dispatch saw exactly one event


def test_stdout_stderr_identical_across_dispatch_outcomes_failure(app: App, store: TelemetryStore) -> None:
    """SC-003: failure-path output is identical whatever the telemetry dispatch does."""

    def inner(_args: Sequence[str] | None) -> object:
        print("out before fail")
        print("err before fail", file=sys.stderr)
        raise ValueError("x")

    noop_out, noop_err, noop_exc = _run_capturing_io(inner, ["boom"], app, store, _noop_dispatch)
    boom_out, boom_err, boom_exc = _run_capturing_io(inner, ["boom"], app, store, _exploding_dispatch)

    assert noop_out == boom_out == "out before fail\n"
    assert noop_err == boom_err == "err before fail\n"
    assert type(noop_exc) is ValueError
    assert type(boom_exc) is ValueError
