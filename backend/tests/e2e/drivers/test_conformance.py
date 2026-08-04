"""ScenarioDriver Protocol conformance tests.

Ensures both ApiScenarioDriver and UiScenarioDriver implement every method
declared on :class:`ScenarioDriver` — and that no implementation is a
``raise NotImplementedError`` stub.

Lives under ``tests/e2e/`` (not unit) because the driver modules import
playwright; but is a plain unit-scoped test — no fixtures needed.
"""

from __future__ import annotations

import inspect

import pytest

from tests.e2e.drivers.api_driver import ApiScenarioDriver
from tests.e2e.drivers.protocol import ScenarioDriver
from tests.e2e.drivers.ui_driver import UiScenarioDriver


def _protocol_methods() -> list[str]:
    """Return the names of the methods declared on the ScenarioDriver protocol.

    The protocol's surface is *not* async-only — ``attach_to_deployment`` is a
    plain ``def`` — so this deliberately covers both ``async def`` and ``def``
    members. Anything comparing driver surfaces against this list must do the
    same, or every sync member reads as "missing" (see
    ``_public_methods`` / ``_is_async``).
    """
    # Protocols store their members on ``__protocol_attrs__``; fall back to
    # walking __dict__ for Python versions where the attribute isn't exposed.
    raw = getattr(ScenarioDriver, "__protocol_attrs__", None)
    if raw is None:
        raw = [
            name
            for name, value in ScenarioDriver.__dict__.items()
            if not name.startswith("_") and inspect.isfunction(value)
        ]
    return sorted(raw)


def _public_methods(cls: type) -> set[str]:
    """Public methods defined directly on ``cls`` — sync and async alike.

    ``inspect.isfunction`` is true for ``async def`` as well as ``def``, so a
    driver's whole public surface is captured regardless of how the protocol
    declares each member.
    """
    return {
        name
        for name, value in cls.__dict__.items()
        if not name.startswith("_") and inspect.isfunction(value)
    }


def _is_async(cls: type, name: str) -> bool:
    """Whether ``cls.name`` is a coroutine function."""
    return inspect.iscoroutinefunction(getattr(cls, name))


@pytest.mark.parametrize(
    "driver_cls", [ApiScenarioDriver, UiScenarioDriver], ids=["api", "ui"]
)
def test_driver_implements_every_protocol_method(driver_cls: type) -> None:
    missing = [
        name
        for name in _protocol_methods()
        if not callable(getattr(driver_cls, name, None))
    ]
    assert not missing, (
        f"{driver_cls.__name__} is missing ScenarioDriver methods: {missing}"
    )


@pytest.mark.parametrize(
    "driver_cls", [ApiScenarioDriver, UiScenarioDriver], ids=["api", "ui"]
)
def test_driver_has_no_notimplementederror_stubs(driver_cls: type) -> None:
    """A method body consisting only of ``raise NotImplementedError`` is a stub.

    Drivers MAY still surface ``ScenarioActionError`` for operations the
    entrypoint genuinely does not expose (e.g. UI has no delete-environment
    surface). Those are fully implemented — the body raises ``ScenarioActionError``
    with a reason, not a bare ``NotImplementedError``.
    """
    offenders: list[str] = []
    for name in _protocol_methods():
        method = getattr(driver_cls, name, None)
        if method is None:
            continue
        try:
            source = inspect.getsource(method)
        except OSError, TypeError:
            continue
        # Strip leading whitespace and comments before checking.
        body_lines = [
            ln.strip()
            for ln in source.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        # Heuristic: if the body (after signature + docstring) only contains
        # ``raise NotImplementedError``, flag it. We look for the token in the
        # raw source and require NO other statement after the signature.
        stripped = "\n".join(body_lines)
        if "raise NotImplementedError" in stripped:
            offenders.append(f"{driver_cls.__name__}.{name}")
    assert not offenders, (
        "Methods still raise NotImplementedError — implement them or raise "
        f"ScenarioActionError with an actionable reason instead: {offenders}"
    )


def test_protocol_methods_match_both_drivers() -> None:
    """Both drivers must expose exactly the same public surface (plus helpers).

    A divergence here means one driver gained a public method the other
    doesn't — scenarios using that method would silently work on one
    entrypoint and fail on the other.

    Async-ness is part of that surface: awaiting a sync implementation (or
    forgetting to await an async one) breaks scenarios just as loudly as a
    missing method. The expectation is read off each protocol member's own
    declaration rather than an exempt-by-name list, so a sync member added to
    the protocol tomorrow is covered without touching this test.
    """
    api_methods = _public_methods(ApiScenarioDriver)
    ui_methods = _public_methods(UiScenarioDriver)
    protocol = set(_protocol_methods())

    assert api_methods >= protocol, (
        f"ApiScenarioDriver is missing: {protocol - api_methods}"
    )
    assert ui_methods >= protocol, (
        f"UiScenarioDriver is missing: {protocol - ui_methods}"
    )

    extra_api = api_methods - ui_methods
    extra_ui = ui_methods - api_methods
    assert not extra_api and not extra_ui, (
        f"Driver surface divergence — api-only: {extra_api}, ui-only: {extra_ui}"
    )

    mismatched: list[str] = []
    for name in sorted(protocol):
        expected_async = _is_async(ScenarioDriver, name)
        for driver_cls in (ApiScenarioDriver, UiScenarioDriver):
            if _is_async(driver_cls, name) is not expected_async:
                kind = "async def" if expected_async else "def"
                mismatched.append(
                    f"{driver_cls.__name__}.{name} should be declared "
                    f"`{kind}` to match ScenarioDriver.{name}"
                )
    assert not mismatched, "Sync/async divergence from the protocol: " + "; ".join(
        mismatched
    )


def test_protocol_method_signatures_match() -> None:
    """Each driver's method parameter names, defaults, and return type must match.

    Return-type and default-value divergence would let one driver silently
    accept a call the other rejects — or return a differently-shaped ref —
    without any test failing. Checking here keeps the two entrypoints truly
    interchangeable for scenarios.
    """
    for name in _protocol_methods():
        proto_sig = inspect.signature(getattr(ScenarioDriver, name), eval_str=True)
        for driver_cls in (ApiScenarioDriver, UiScenarioDriver):
            impl_sig = inspect.signature(getattr(driver_cls, name), eval_str=True)
            proto_params = list(proto_sig.parameters.values())[1:]
            impl_params = list(impl_sig.parameters.values())[1:]
            assert [p.name for p in proto_params] == [p.name for p in impl_params], (
                f"{driver_cls.__name__}.{name}: parameter names differ from "
                f"ScenarioDriver.{name}"
            )
            assert [p.default for p in proto_params] == [
                p.default for p in impl_params
            ], (
                f"{driver_cls.__name__}.{name}: parameter defaults differ from "
                f"ScenarioDriver.{name} (proto={[p.default for p in proto_params]}, "
                f"impl={[p.default for p in impl_params]})"
            )
            assert proto_sig.return_annotation == impl_sig.return_annotation, (
                f"{driver_cls.__name__}.{name}: return annotation differs "
                f"(proto={proto_sig.return_annotation!r}, "
                f"impl={impl_sig.return_annotation!r})"
            )
