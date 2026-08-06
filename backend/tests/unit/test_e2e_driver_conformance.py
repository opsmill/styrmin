"""ScenarioDriver Protocol conformance tests.

Ensures both ApiScenarioDriver and UiScenarioDriver implement every method
declared on :class:`ScenarioDriver` — and that no implementation is a
``raise NotImplementedError`` stub.

Lives under ``tests/unit/`` even though it introspects the ``tests.e2e.drivers``
modules, because it is a plain unit test: it imports the driver classes and
reflects over them, with no cluster, no fixtures and no Playwright browser.
Importing ``playwright`` is not a reason to sit under ``tests/e2e/`` — the
package is an ordinary dev dependency.

Placement is load-bearing rather than cosmetic. ``backend/tests/e2e/conftest.py``
declares an ``autouse=True`` fixture that depends on the session-scoped
``vcluster`` fixture, so *collecting* any module under ``tests/e2e/`` boots a
virtual Kubernetes cluster. The unit job runs ``pytest tests --ignore=tests/e2e``
(``tasks/__init__.py``) and the CI e2e cells select ``-m "ci and shard_<name>"``;
while this module lived under ``tests/e2e/drivers/`` — carrying neither ``ci``
nor a ``shard_*`` marker — it therefore ran in **no** CI job at all. Under
``tests/unit/`` the existing unit job picks it up with no workflow change.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from tests.e2e.drivers.api_driver import ApiScenarioDriver, _constituent_outcome
from tests.e2e.drivers.protocol import ScenarioDriver
from tests.e2e.drivers.refs import TERMINAL_ENVIRONMENT_OPERATION_STATUSES
from tests.e2e.drivers.ui_driver import UiScenarioDriver

# The environment-level backup/restore surface (spec 001-env-backup-restore).
# Spelled out rather than derived so a method silently dropped from the
# protocol — which would make every scenario using it a collection error
# instead of a conformance failure — is caught here by name.
_ENVIRONMENT_BACKUP_METHODS = (
    "create_environment_backup",
    "get_environment_backup",
    "wait_for_environment_backup",
    "restore_environment_backup",
    "wait_for_environment_restore",
    "delete_environment_backup",
)


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


def _raises_notimplementederror(method: object) -> bool:
    """Whether ``method``'s body contains a real ``raise NotImplementedError``.

    Parsed as an AST rather than grepped for the literal phrase: a substring
    search over the raw source also matches the *prose* of a docstring or a
    comment (this very file's module docstring would trip it), so a driver
    method that merely documents "raise NotImplementedError" as the thing it
    deliberately avoids would be reported as a stub. Only ``ast.Raise`` nodes
    naming ``NotImplementedError`` — bare or called — count.
    """
    try:
        source = textwrap.dedent(inspect.getsource(method))
    except OSError, TypeError:
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover — a decorator-mangled source
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        raised = node.exc
        if isinstance(raised, ast.Call):
            raised = raised.func
        if isinstance(raised, ast.Name) and raised.id == "NotImplementedError":
            return True
    return False


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
        if _raises_notimplementederror(method):
            offenders.append(f"{driver_cls.__name__}.{name}")
    assert not offenders, (
        "Methods still raise NotImplementedError — implement them or raise "
        f"ScenarioActionError with an actionable reason instead: {offenders}"
    )


def test_stub_detector_ignores_prose_and_catches_real_raises() -> None:
    """The stub detector must key off code, not the words in a docstring.

    The previous implementation substring-matched ``raise NotImplementedError``
    over the raw source, so a method whose *docstring* or comment mentioned the
    phrase read as an unimplemented stub — the exact false positive that makes a
    conformance guard untrustworthy, and the reason this asserts on both
    directions rather than only on the happy path.
    """

    def documents_but_does_not_raise() -> str:
        """Never a ``raise NotImplementedError`` — see the driver contract."""
        # raise NotImplementedError would be wrong here
        return "implemented"

    def bare_stub() -> None:
        raise NotImplementedError

    def called_stub() -> None:
        raise NotImplementedError("not yet")

    def raises_something_else() -> None:
        raise ValueError("a real, actionable failure")

    assert not _raises_notimplementederror(documents_but_does_not_raise)
    assert not _raises_notimplementederror(raises_something_else)
    assert _raises_notimplementederror(bare_stub)
    assert _raises_notimplementederror(called_stub)


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


def test_environment_backup_surface_is_on_the_protocol_and_both_drivers() -> None:
    """The environment-level surface must exist on the protocol *and* both drivers.

    ``test_driver_implements_every_protocol_method`` only checks that the
    drivers cover whatever the protocol declares — if a method were dropped from
    the protocol it would keep passing while every scenario using it broke. This
    pins the six methods by name at both ends.
    """
    protocol = set(_protocol_methods())
    missing_from_protocol = [
        name for name in _ENVIRONMENT_BACKUP_METHODS if name not in protocol
    ]
    assert not missing_from_protocol, (
        f"ScenarioDriver lost environment-level backup methods: {missing_from_protocol}"
    )
    for driver_cls in (ApiScenarioDriver, UiScenarioDriver):
        missing = [
            name
            for name in _ENVIRONMENT_BACKUP_METHODS
            if not callable(getattr(driver_cls, name, None))
        ]
        assert not missing, f"{driver_cls.__name__} is missing: {missing}"


def test_terminal_environment_statuses_cover_the_sdk_enums() -> None:
    """The refs' terminal-status names must match the SDK's terminal enum sets.

    Both drivers report the raw ``EnvironmentBackupStatus`` /
    ``EnvironmentRestoreStatus`` *name* as a plain string, so the waiter's
    terminal set is maintained by hand. If a new terminal member is ever added
    to the schema, the waiters would poll past it forever — this catches that at
    unit speed.
    """
    from styrmin_sdk.resources.environment_backups import (
        TERMINAL_ENVIRONMENT_BACKUP_STATUSES,
        TERMINAL_ENVIRONMENT_RESTORE_STATUSES,
    )

    assert TERMINAL_ENVIRONMENT_OPERATION_STATUSES == {
        status.name for status in TERMINAL_ENVIRONMENT_BACKUP_STATUSES
    }
    assert TERMINAL_ENVIRONMENT_OPERATION_STATUSES == {
        status.name for status in TERMINAL_ENVIRONMENT_RESTORE_STATUSES
    }


class _FakeBackup:
    def __init__(self, status: str) -> None:
        self.status = status


class _FakeConstituent:
    def __init__(self, *, error: str | None = None, backup_status: str | None = None):
        self.error = error
        self.backup = None if backup_status is None else _FakeBackup(backup_status)


@pytest.mark.parametrize(
    ("constituent", "expected"),
    [
        (_FakeConstituent(error="already in progress"), "error"),
        (_FakeConstituent(), "missing"),
        (_FakeConstituent(backup_status="completed"), "completed"),
        (_FakeConstituent(backup_status="failed"), "failed"),
        (_FakeConstituent(backup_status="pending"), "in-flight"),
        (_FakeConstituent(backup_status="in_progress"), "in-flight"),
        # Case-insensitive for the same reason the frontend is: a backend that
        # ever uppercased Backup.status must not silently read as in-flight.
        (_FakeConstituent(backup_status="COMPLETED"), "completed"),
    ],
)
def test_api_driver_constituent_outcome_matches_frontend_vocabulary(
    constituent: _FakeConstituent, expected: str
) -> None:
    """The API driver's classifier must agree with ``classifyConstituent``.

    The UI driver reads ``data-constituent-outcome`` straight out of the DOM,
    which the frontend computes with its own ``classifyConstituent``. The API
    driver re-implements it, so scenarios can only assert on ``outcome``
    without a ``driver_mode`` branch while the two stay in lock-step — and
    ``missing`` in particular is the deliberately-visible gap of spec FR-010.
    """
    assert _constituent_outcome(constituent) == expected


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
