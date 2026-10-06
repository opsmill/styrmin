"""The create, update and resume handlers write ``status.instanceId`` (spec 019, research D4).

The status reporter sends this field, so a report names the instance whose
spec the operator acted on, also when the handler raised and kopf retries it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import kopf
import pytest

from styrmin_backend.operator.crd.schema import ConditionType, DeploymentPhase
from styrmin_backend.operator.handlers import styrmin_deployment as handlers_module
from styrmin_backend.operator.handlers.styrmin_deployment import (
    kopf_on_styrmin_deployment_create,
    kopf_on_styrmin_deployment_resume,
    kopf_on_styrmin_deployment_update,
)
from styrmin_backend.operator.pipeline import PhaseResult

INSTANCE_ID = "11111111-2222-3333-4444-555555555555"
PREVIOUS_INSTANCE_ID = "99999999-8888-7777-6666-555555555555"

Handler = Callable[..., Awaitable[None]]


class _Patch:
    """Minimal stand-in for ``kopf.Patch``."""

    def __init__(self) -> None:
        self.status: dict[str, Any] = {}
        self.spec: dict[str, Any] = {}
        self.metadata: dict[str, Any] = {}


class _Logger:
    def info(self, *_: Any, **__: Any) -> None: ...
    def warning(self, *_: Any, **__: Any) -> None: ...
    def debug(self, *_: Any, **__: Any) -> None: ...
    def error(self, *_: Any, **__: Any) -> None: ...


def _spec(*, internal: bool = False, instance_id: str | None = INSTANCE_ID) -> dict:
    spec: dict[str, Any] = {"releaseReference": "rel-1", "internal": internal}
    if instance_id is not None:
        spec["instanceId"] = instance_id
    return spec


def _status(phase: DeploymentPhase = DeploymentPhase.READY) -> dict:
    # The previous rollout's status: its instance and a True HelmReleaseReady.
    return {
        "phase": phase.value,
        "instanceId": PREVIOUS_INSTANCE_ID,
        "conditions": [
            {"type": ConditionType.NETWORK_POLICIES_READY.value, "status": "True"},
            {"type": ConditionType.SECRETS_READY.value, "status": "True"},
            {"type": ConditionType.HELM_RELEASE_READY.value, "status": "False"},
        ],
    }


@pytest.fixture
def phases(mocker) -> dict[str, Any]:
    """The pipeline phases, succeeding unless a test sets another return value."""
    return {
        "prerequisites": mocker.patch.object(
            handlers_module,
            "execute_phase_prerequisites",
            autospec=True,
            return_value=PhaseResult(),
        ),
        "helmrelease": mocker.patch.object(
            handlers_module,
            "execute_phase_helmrelease",
            autospec=True,
            return_value=PhaseResult(),
        ),
    }


async def _run(
    handler: Handler, *, spec: dict, status: dict, patch: _Patch, **extra: Any
) -> None:
    await handler(
        spec=spec,
        status=status,
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
        **extra,
    )


HANDLERS: dict[str, tuple[Handler, dict[str, Any], DeploymentPhase]] = {
    "create": (kopf_on_styrmin_deployment_create, {}, DeploymentPhase.PENDING),
    "update": (kopf_on_styrmin_deployment_update, {"diff": ()}, DeploymentPhase.READY),
    "resume": (
        kopf_on_styrmin_deployment_resume,
        {},
        DeploymentPhase.CREATING_HELM_RELEASE,
    ),
}


@pytest.mark.anyio
@pytest.mark.parametrize("internal", [False, True], ids=["platform", "internal"])
@pytest.mark.parametrize("handler_name", list(HANDLERS))
async def test_handler_writes_the_instance_it_handled(
    phases: dict[str, Any], handler_name: str, internal: bool
) -> None:
    handler, extra, phase = HANDLERS[handler_name]
    patch = _Patch()

    await _run(
        handler,
        spec=_spec(internal=internal),
        status=_status(phase),
        patch=patch,
        **extra,
    )

    assert patch.status["instanceId"] == INSTANCE_ID


@pytest.mark.anyio
@pytest.mark.parametrize("failing_phase", ["prerequisites", "helmrelease"])
@pytest.mark.parametrize("handler_name", list(HANDLERS))
async def test_handler_writes_the_instance_when_it_raises(
    phases: dict[str, Any], handler_name: str, failing_phase: str
) -> None:
    handler, extra, phase = HANDLERS[handler_name]
    phases[failing_phase].return_value = PhaseResult(success=False, errors=["boom"])
    status = _status(phase)
    if handler_name == "resume" and failing_phase == "prerequisites":
        # Resume re-runs the prerequisites only while they are not ready.
        status = {**status, "phase": DeploymentPhase.CREATING_PREREQUISITES.value}
        status["conditions"] = []
    patch = _Patch()

    with pytest.raises(kopf.TemporaryError):
        await _run(handler, spec=_spec(), status=status, patch=patch, **extra)

    assert patch.status["instanceId"] == INSTANCE_ID


@pytest.mark.anyio
@pytest.mark.parametrize("handler_name", list(HANDLERS))
async def test_handler_writes_the_instance_when_a_phase_raises(
    phases: dict[str, Any], handler_name: str
) -> None:
    handler, extra, phase = HANDLERS[handler_name]
    phases["helmrelease"].side_effect = RuntimeError("API unreachable")
    status = _status(phase)
    patch = _Patch()

    with pytest.raises(RuntimeError):
        await _run(handler, spec=_spec(), status=status, patch=patch, **extra)

    assert patch.status["instanceId"] == INSTANCE_ID


@pytest.mark.anyio
async def test_resume_of_a_ready_deployment_writes_the_instance(
    phases: dict[str, Any],
) -> None:
    patch = _Patch()

    await _run(
        kopf_on_styrmin_deployment_resume,
        spec=_spec(),
        status={"phase": DeploymentPhase.READY.value},
        patch=patch,
    )

    assert patch.status == {"instanceId": INSTANCE_ID}
    phases["prerequisites"].assert_not_called()
    phases["helmrelease"].assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("handler_name", list(HANDLERS))
async def test_handler_leaves_the_status_instance_alone_without_a_spec_instance(
    phases: dict[str, Any], handler_name: str
) -> None:
    handler, extra, phase = HANDLERS[handler_name]
    patch = _Patch()

    await _run(
        handler,
        spec=_spec(instance_id=None),
        status=_status(phase),
        patch=patch,
        **extra,
    )

    assert "instanceId" not in patch.status


@pytest.mark.anyio
async def test_update_that_requests_the_deletion_writes_no_instance(
    phases: dict[str, Any],
) -> None:
    patch = _Patch()

    await _run(
        kopf_on_styrmin_deployment_update,
        spec={**_spec(), "deletionRequested": True},
        status=_status(),
        patch=patch,
        diff=(),
    )

    assert patch.status == {}
