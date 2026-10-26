"""The operator judges the HelmRelease on its current generation (spec 019, research D5).

Create and update reset ``HelmReleaseReady`` and record ``rolloutStartedAt``;
resume keeps both. The timer counts FluxCD's ``Ready=True`` only for the
HelmRelease's current generation, copies FluxCD's reason and remediation into
the CR status, fails the CR on ``Stalled=True`` and on ``Ready=True`` for
FluxCD's rollback of the generation's failed release, and writes conditions only
when they change.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import kopf
import pytest

from styrmin_backend.operator import reconciler as reconciler_module
from styrmin_backend.operator.crd.schema import (
    ConditionType,
    DeploymentPhase,
    DisplayState,
)
from styrmin_backend.operator.crd.status import get_condition
from styrmin_backend.operator.handlers import styrmin_deployment as handlers_module
from styrmin_backend.operator.handlers.styrmin_deployment import (
    kopf_on_styrmin_deployment_create,
    kopf_on_styrmin_deployment_resume,
    kopf_on_styrmin_deployment_update,
    kopf_styrmin_deployment_timer,
)
from styrmin_backend.operator.pipeline import PhaseResult

NAMESPACE = "styrmin-deadbeef"
SPEC = {"releaseReference": "my-release", "instanceId": "inst-2"}

PROGRESS_MESSAGE = "Running 'upgrade' action with timeout of 5m0s"
UPGRADE_FAILURE = (
    "Helm upgrade failed for release styrmin-deadbeef/my-release with chart "
    "simple-app@0.2.0: context deadline exceeded"
)
ROLLBACK_MESSAGE = (
    "Helm rollback to previous release styrmin-deadbeef/my-release.v1 with chart "
    "simple-app@0.1.0 succeeded"
)
STALLED_MESSAGE = "Failed to upgrade after 4 attempt(s)"

T_FAILED = "2026-10-06T10:05:00Z"
T_NOT_READY = "2026-10-06T10:05:01Z"
T_ROLLED_BACK = "2026-10-06T10:05:30Z"
T_READY = "2026-10-06T10:12:00Z"


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
    def exception(self, *_: Any, **__: Any) -> None: ...


class _Stopped:
    """Stand-in for kopf's ``stopped`` flag of a timer that kopf does not stop."""

    def __bool__(self) -> bool:
        return False

    async def wait(self, timeout: float) -> None: ...


def _flux(
    type_: str,
    status: str,
    reason: str,
    message: str,
    generation: int | None,
    at: str = T_FAILED,
) -> dict[str, Any]:
    condition: dict[str, Any] = {
        "type": type_,
        "status": status,
        "reason": reason,
        "message": message,
        "lastTransitionTime": at,
    }
    if generation is not None:
        condition["observedGeneration"] = generation
    return condition


def _snapshot(version: int, status: str) -> dict[str, Any]:
    """One entry of FluxCD's ``status.history``."""
    return {
        "name": "my-release",
        "namespace": NAMESPACE,
        "version": version,
        "status": status,
        "chartName": "simple-app",
        "chartVersion": "0.1.0",
        "configDigest": "sha256:fc2de67daf30f",
    }


def _helmrelease(
    *conditions: dict[str, Any],
    generation: int = 2,
    last_attempted_generation: int | None = None,
    history: list[dict[str, Any]] | None = None,
    upgrade_failures: int | None = None,
) -> dict[str, Any]:
    status: dict[str, Any] = {"conditions": list(conditions)}
    if last_attempted_generation is not None:
        status["lastAttemptedGeneration"] = last_attempted_generation
    if history is not None:
        status["history"] = history
    if upgrade_failures is not None:
        status["upgradeFailures"] = upgrade_failures
    return {
        "apiVersion": "helm.toolkit.fluxcd.io/v2",
        "kind": "HelmRelease",
        "metadata": {
            "name": "my-release",
            "namespace": NAMESPACE,
            "generation": generation,
        },
        "status": status,
    }


def _cr_condition(
    type_: str, status: str, reason: str = "", message: str = ""
) -> dict[str, Any]:
    return {
        "type": type_,
        "status": status,
        "reason": reason,
        "message": message,
        "lastTransitionTime": "2026-10-06T10:00:00+00:00",
    }


def _rolling_out_status(*extra: dict[str, Any]) -> dict[str, Any]:
    """An update rollout waiting for FluxCD, as the update handler leaves it."""
    return {
        "phase": DeploymentPhase.CREATING_HELM_RELEASE.value,
        "displayState": DisplayState.DEPLOYING.value,
        "rolloutStartedAt": datetime.now(tz=UTC).isoformat(),
        "conditions": [
            _cr_condition(
                ConditionType.NETWORK_POLICIES_READY.value, "True", "AllApplied"
            ),
            _cr_condition(ConditionType.SECRETS_READY.value, "True", "AllApplied"),
            _cr_condition(
                ConditionType.HELM_RELEASE_READY.value,
                "Unknown",
                "Progressing",
                "Waiting for FluxCD to apply the HelmRelease",
            ),
            _cr_condition(ConditionType.READY.value, "True", "AllPhasesComplete"),
            *extra,
        ],
    }


def _condition(patch: _Patch, condition_type: ConditionType) -> dict[str, Any] | None:
    return get_condition(patch.status.get("conditions", []), condition_type.value)


@pytest.fixture
def services(mocker) -> Any:
    return mocker.patch.object(
        handlers_module,
        "execute_phase_services",
        new=mocker.AsyncMock(
            return_value=PhaseResult(resource_details={"services": 1, "middlewares": 0})
        ),
    )


def _serve(mocker, *helmreleases: dict[str, Any] | None) -> Any:
    """Serve one HelmRelease per tick."""
    return mocker.patch.object(
        reconciler_module,
        "_get_helmrelease",
        new=mocker.AsyncMock(side_effect=list(helmreleases)),
    )


async def _tick(
    status: dict[str, Any],
    *,
    spec: dict[str, Any] = SPEC,
    body: dict[str, Any] | None = None,
) -> _Patch:
    patch = _Patch()
    await kopf_styrmin_deployment_timer(
        body=body
        or {"metadata": {"creationTimestamp": datetime.now(tz=UTC).isoformat()}},
        spec=spec,
        status=status,
        name="my-deployment",
        namespace=NAMESPACE,
        patch=patch,
        logger=_Logger(),
        stopped=_Stopped(),
    )
    return patch


def _apply(status: dict[str, Any], patch: _Patch) -> dict[str, Any]:
    """The status after kopf merges ``patch`` into it."""
    return {**status, **patch.status}


# --- Timer: the current-generation rule ---


@pytest.mark.anyio
async def test_ready_of_a_previous_generation_does_not_count(mocker, services) -> None:
    """FluxCD has not applied the new spec yet: its Ready=True describes the previous release."""
    get_hr = _serve(
        mocker,
        _helmrelease(
            _flux("Ready", "True", "UpgradeSucceeded", "Helm upgrade succeeded", 1),
            generation=2,
        ),
    )

    patch = await _tick(_rolling_out_status())

    assert patch.status == {}
    services.assert_not_called()
    get_hr.assert_awaited_once_with(namespace=NAMESPACE, release_reference="my-release")


@pytest.mark.anyio
async def test_stale_helm_release_ready_of_a_legacy_rollout_does_not_advance(
    mocker, services
) -> None:
    """A CR mid-update from an older operator keeps HelmReleaseReady=True of the previous rollout."""
    _serve(
        mocker,
        _helmrelease(
            _flux("Ready", "True", "UpgradeSucceeded", "Helm upgrade succeeded", 1),
            generation=2,
        ),
    )
    status = _rolling_out_status()
    del status["rolloutStartedAt"]
    status["conditions"][2] = _cr_condition(
        ConditionType.HELM_RELEASE_READY.value,
        "True",
        "FluxReady",
        "HelmRelease is Ready",
    )

    patch = await _tick(status)

    assert patch.status == {}
    services.assert_not_called()


@pytest.mark.parametrize(
    "helmrelease",
    [
        _helmrelease(
            _flux("Ready", "True", "UpgradeSucceeded", "Helm upgrade succeeded", 2)
        ),
        _helmrelease(
            _flux("Ready", "True", "UpgradeSucceeded", "Helm upgrade succeeded", None),
            last_attempted_generation=2,
        ),
    ],
    ids=["observed-generation", "last-attempted-generation"],
)
@pytest.mark.anyio
async def test_ready_of_the_current_generation_reaches_ready(
    mocker, services, helmrelease: dict[str, Any]
) -> None:
    get_hr = _serve(mocker, helmrelease)

    patch = await _tick(_rolling_out_status())

    assert patch.status["phase"] == DeploymentPhase.READY.value
    assert patch.status["displayState"] == DisplayState.RUNNING.value
    hr_ready = _condition(patch, ConditionType.HELM_RELEASE_READY)
    assert hr_ready is not None
    assert hr_ready["status"] == "True"
    services.assert_awaited_once()
    get_hr.assert_awaited_once()


@pytest.mark.anyio
async def test_missing_helmrelease_keeps_waiting(mocker, services) -> None:
    _serve(mocker, None)

    patch = await _tick(_rolling_out_status())

    assert patch.status == {}
    services.assert_not_called()


# --- Timer: copying FluxCD's state ---


@pytest.mark.anyio
async def test_fluxcd_progress_is_copied(mocker, services) -> None:
    _serve(
        mocker,
        _helmrelease(
            _flux("Ready", "Unknown", "Progressing", PROGRESS_MESSAGE, 2, T_NOT_READY)
        ),
    )

    patch = await _tick(_rolling_out_status())

    assert "phase" not in patch.status
    assert "displayState" not in patch.status
    assert _condition(patch, ConditionType.HELM_RELEASE_READY) == {
        "type": ConditionType.HELM_RELEASE_READY.value,
        "status": "Unknown",
        "reason": "Progressing",
        "message": PROGRESS_MESSAGE,
        "lastTransitionTime": T_NOT_READY,
    }
    services.assert_not_called()


def _rolled_back_helmrelease(*extra: dict[str, Any]) -> dict[str, Any]:
    """FluxCD after a failed upgrade and its rollback: Ready repeats the remediation."""
    return _helmrelease(
        _flux("Ready", "False", "RollbackSucceeded", ROLLBACK_MESSAGE, 2, T_NOT_READY),
        _flux("Released", "False", "UpgradeFailed", UPGRADE_FAILURE, 2, T_FAILED),
        _flux(
            "Remediated",
            "True",
            "RollbackSucceeded",
            ROLLBACK_MESSAGE,
            2,
            T_ROLLED_BACK,
        ),
        *extra,
    )


@pytest.mark.anyio
async def test_failure_reason_and_rollback_are_copied_without_a_phase_change(
    mocker, services
) -> None:
    _serve(mocker, _rolled_back_helmrelease())

    patch = await _tick(_rolling_out_status())

    assert "phase" not in patch.status
    assert "displayState" not in patch.status
    assert "message" not in patch.status
    # The failed upgrade names the cause; Ready only repeats the rollback.
    assert _condition(patch, ConditionType.HELM_RELEASE_READY) == {
        "type": ConditionType.HELM_RELEASE_READY.value,
        "status": "False",
        "reason": "UpgradeFailed",
        "message": UPGRADE_FAILURE,
        "lastTransitionTime": T_NOT_READY,
    }
    assert _condition(patch, ConditionType.HELM_RELEASE_REMEDIATED) == {
        "type": ConditionType.HELM_RELEASE_REMEDIATED.value,
        "status": "True",
        "reason": "RollbackSucceeded",
        "message": ROLLBACK_MESSAGE,
        "lastTransitionTime": T_ROLLED_BACK,
    }
    services.assert_not_called()


@pytest.mark.anyio
async def test_ready_reason_is_copied_when_no_failed_release_of_this_generation(
    mocker, services
) -> None:
    _serve(
        mocker,
        _helmrelease(
            _flux(
                "Ready",
                "False",
                "ArtifactFailed",
                "HelmChart is not ready",
                2,
                T_NOT_READY,
            ),
            _flux("Released", "False", "UpgradeFailed", UPGRADE_FAILURE, 1),
        ),
    )

    patch = await _tick(_rolling_out_status())

    hr_ready = _condition(patch, ConditionType.HELM_RELEASE_READY)
    assert hr_ready is not None
    assert (hr_ready["status"], hr_ready["reason"], hr_ready["message"]) == (
        "False",
        "ArtifactFailed",
        "HelmChart is not ready",
    )


@pytest.mark.anyio
async def test_conditions_of_a_previous_generation_are_not_copied(
    mocker, services
) -> None:
    _serve(
        mocker,
        _helmrelease(
            _flux("Ready", "False", "RollbackSucceeded", ROLLBACK_MESSAGE, 1),
            _flux("Remediated", "True", "RollbackSucceeded", ROLLBACK_MESSAGE, 1),
            _flux("Stalled", "True", "RetriesExceeded", STALLED_MESSAGE, 1),
        ),
    )

    patch = await _tick(_rolling_out_status())

    assert patch.status == {}


# --- Timer: FluxCD's final failure ---


@pytest.mark.anyio
async def test_stalled_fails_the_deployment(mocker, services) -> None:
    _serve(
        mocker,
        _rolled_back_helmrelease(
            _flux(
                "Stalled", "True", "RetriesExceeded", STALLED_MESSAGE, 2, T_ROLLED_BACK
            )
        ),
    )

    patch = await _tick(_rolling_out_status())

    assert patch.status["phase"] == DeploymentPhase.FAILED.value
    assert patch.status["displayState"] == DisplayState.ERROR.value
    assert patch.status["message"] == f"{STALLED_MESSAGE}: {UPGRADE_FAILURE}"
    hr_ready = _condition(patch, ConditionType.HELM_RELEASE_READY)
    assert hr_ready is not None
    assert (hr_ready["status"], hr_ready["reason"]) == ("False", "UpgradeFailed")
    remediated = _condition(patch, ConditionType.HELM_RELEASE_REMEDIATED)
    assert remediated is not None
    assert remediated["lastTransitionTime"] == T_ROLLED_BACK
    # Phase Failed must not sit next to Ready=True of the previous rollout.
    ready = _condition(patch, ConditionType.READY)
    assert ready is not None
    assert (ready["status"], ready["reason"]) == ("False", "RetriesExceeded")
    services.assert_not_called()


@pytest.mark.anyio
async def test_retry_that_succeeds_after_a_rollback_reaches_ready(
    mocker, services
) -> None:
    # v3 failed, v4 is FluxCD's rollback, and FluxCD's retry released v5.
    upgraded = _helmrelease(
        _flux(
            "Ready", "True", "UpgradeSucceeded", "Helm upgrade succeeded", 2, T_READY
        ),
        _flux(
            "Released", "True", "UpgradeSucceeded", "Helm upgrade succeeded", 2, T_READY
        ),
        history=[
            _snapshot(5, "deployed"),
            _snapshot(4, "superseded"),
            _snapshot(3, "failed"),
        ],
        upgrade_failures=1,
    )
    _serve(mocker, _rolled_back_helmrelease(), upgraded)
    # The readiness timeout fired while FluxCD was still retrying.
    status = {**_rolling_out_status(), "displayState": DisplayState.ERROR.value}

    first = await _tick(status)
    second = await _tick(_apply(status, first))

    assert "phase" not in first.status
    assert second.status["phase"] == DeploymentPhase.READY.value
    assert second.status["displayState"] == DisplayState.RUNNING.value
    hr_ready = _condition(second, ConditionType.HELM_RELEASE_READY)
    assert hr_ready is not None
    assert hr_ready["status"] == "True"
    # The rollback of the failed attempt stays recorded for the step history.
    remediated = _condition(second, ConditionType.HELM_RELEASE_REMEDIATED)
    assert remediated is not None
    assert remediated["lastTransitionTime"] == T_ROLLED_BACK
    services.assert_awaited_once()


ROLLBACK_RELEASED = (
    "Helm upgrade succeeded for release styrmin-deadbeef/my-release.v4 with chart "
    "simple-app@0.1.0"
)


def _ready_after_rollback_helmrelease(**overrides: Any) -> dict[str, Any]:
    """FluxCD after it rolled back v3 to v4 and found v4 in sync (H1, helm-controller v1.1.0).

    FluxCD compared only the chart and the values, so it reports the rollback as the
    released upgrade, and removed ``Remediated``.
    """
    arguments: dict[str, Any] = {
        "history": [
            _snapshot(4, "deployed"),
            _snapshot(3, "failed"),
            _snapshot(2, "superseded"),
        ],
        "upgrade_failures": 1,
        **overrides,
    }
    return _helmrelease(
        _flux("Ready", "True", "UpgradeSucceeded", ROLLBACK_RELEASED, 2, T_READY),
        _flux("Released", "True", "UpgradeSucceeded", ROLLBACK_RELEASED, 2, T_READY),
        **arguments,
    )


def _assert_failed_by_rollback(patch: _Patch, message: str) -> None:
    assert patch.status["phase"] == DeploymentPhase.FAILED.value
    assert patch.status["displayState"] == DisplayState.ERROR.value
    assert patch.status["message"] == message
    ready = _condition(patch, ConditionType.READY)
    assert ready is not None
    assert (ready["status"], ready["reason"], ready["message"]) == (
        "False",
        "RolledBack",
        message,
    )


@pytest.mark.anyio
async def test_ready_after_a_rollback_of_this_generation_fails_the_deployment(
    mocker, services
) -> None:
    """H1: FluxCD's rollback of a post-render override is not the release of the generation."""
    _serve(mocker, _rolled_back_helmrelease(), _ready_after_rollback_helmrelease())
    # The readiness timeout fired while FluxCD was still waiting for the upgrade.
    status = {**_rolling_out_status(), "displayState": DisplayState.ERROR.value}

    first = await _tick(status)
    second = await _tick(_apply(status, first))

    assert "phase" not in first.status
    _assert_failed_by_rollback(
        second,
        f"FluxCD rolled the release back after release v3 failed: {UPGRADE_FAILURE}",
    )
    # The failed upgrade and the rollback stay recorded for the step history.
    hr_ready = _condition(second, ConditionType.HELM_RELEASE_READY)
    assert hr_ready is not None
    assert (hr_ready["status"], hr_ready["reason"], hr_ready["message"]) == (
        "False",
        "UpgradeFailed",
        UPGRADE_FAILURE,
    )
    remediated = _condition(second, ConditionType.HELM_RELEASE_REMEDIATED)
    assert remediated is not None
    assert remediated["lastTransitionTime"] == T_ROLLED_BACK
    services.assert_not_called()


@pytest.mark.anyio
async def test_ready_after_a_rollback_the_operator_did_not_see_fails_the_deployment(
    mocker, services
) -> None:
    """With the production 60-second interval, the timer can miss FluxCD's failure and rollback."""
    _serve(mocker, _ready_after_rollback_helmrelease())

    patch = await _tick(_rolling_out_status())

    message = "FluxCD rolled the release back after release v3 failed"
    _assert_failed_by_rollback(patch, message)
    hr_ready = _condition(patch, ConditionType.HELM_RELEASE_READY)
    assert hr_ready is not None
    assert (hr_ready["status"], hr_ready["reason"], hr_ready["message"]) == (
        "False",
        "RolledBack",
        message,
    )
    services.assert_not_called()


@pytest.mark.parametrize(
    "overrides",
    [
        # A new generation resets FluxCD's failure counters.
        {"upgrade_failures": 0},
        {"upgrade_failures": None},
        # The newest release is not the next version after the failed one.
        {
            "history": [
                _snapshot(5, "deployed"),
                _snapshot(3, "failed"),
                _snapshot(2, "superseded"),
            ]
        },
        # An ordinary upgrade of a release with no failure in its history.
        {"history": [_snapshot(4, "deployed"), _snapshot(3, "superseded")]},
        {"history": [_snapshot(4, "deployed")]},
    ],
    ids=["failures-reset", "no-failures", "version-gap", "no-failed", "one-release"],
)
@pytest.mark.anyio
async def test_ready_without_a_rollback_of_this_generation_reaches_ready(
    mocker, services, overrides: dict[str, Any]
) -> None:
    _serve(mocker, _ready_after_rollback_helmrelease(**overrides))

    patch = await _tick(_rolling_out_status())

    assert patch.status["phase"] == DeploymentPhase.READY.value
    assert patch.status["displayState"] == DisplayState.RUNNING.value
    services.assert_awaited_once()


@pytest.mark.anyio
async def test_internal_deployment_with_a_ready_pod_reaches_ready_after_a_rollback(
    mocker, services
) -> None:
    _serve(mocker, _ready_after_rollback_helmrelease())
    mocker.patch.object(
        reconciler_module,
        "_check_any_pod_ready",
        new=mocker.AsyncMock(return_value=True),
    )

    patch = await _tick(_rolling_out_status(), spec={**SPEC, "internal": True})

    assert patch.status["phase"] == DeploymentPhase.READY.value
    assert patch.status["displayState"] == DisplayState.RUNNING.value


@pytest.mark.anyio
async def test_no_status_patch_when_fluxcd_state_did_not_change(
    mocker, services
) -> None:
    _serve(mocker, _rolled_back_helmrelease(), _rolled_back_helmrelease())
    status = _rolling_out_status()

    first = await _tick(status)
    second = await _tick(_apply(status, first))

    assert first.status
    assert second.status == {}


@pytest.mark.anyio
async def test_new_fluxcd_transition_is_written(mocker, services) -> None:
    retrying = _helmrelease(
        _flux("Ready", "Unknown", "Progressing", PROGRESS_MESSAGE, 2, T_READY),
        _flux("Released", "False", "UpgradeFailed", UPGRADE_FAILURE, 2, T_FAILED),
        _flux(
            "Remediated",
            "True",
            "RollbackSucceeded",
            ROLLBACK_MESSAGE,
            2,
            T_ROLLED_BACK,
        ),
    )
    _serve(mocker, _rolled_back_helmrelease(), retrying)
    status = _rolling_out_status()

    first = await _tick(status)
    second = await _tick(_apply(status, first))

    hr_ready = _condition(second, ConditionType.HELM_RELEASE_READY)
    assert hr_ready is not None
    assert (hr_ready["status"], hr_ready["reason"], hr_ready["lastTransitionTime"]) == (
        "Unknown",
        "Progressing",
        T_READY,
    )


# --- Timer: internal deployments ---


@pytest.mark.anyio
async def test_internal_deployment_with_a_ready_pod_reaches_ready(
    mocker, services
) -> None:
    """The ingress controller's HelmRelease may never be Ready without a load balancer."""
    _serve(
        mocker,
        _helmrelease(
            _flux("Ready", "Unknown", "Progressing", PROGRESS_MESSAGE, 2),
            _flux("Stalled", "True", "RetriesExceeded", STALLED_MESSAGE, 2),
        ),
    )
    mocker.patch.object(
        reconciler_module,
        "_check_any_pod_ready",
        new=mocker.AsyncMock(return_value=True),
    )

    patch = await _tick(_rolling_out_status(), spec={**SPEC, "internal": True})

    assert patch.status["phase"] == DeploymentPhase.READY.value
    assert patch.status["displayState"] == DisplayState.RUNNING.value
    services.assert_not_called()


# --- Handlers: start of a rollout ---


@pytest.fixture
def phases(mocker) -> dict[str, Any]:
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


OLD_ROLLOUT_START = "2026-10-01T08:00:00+00:00"


def _previous_rollout_status() -> dict[str, Any]:
    """The status a finished rollout leaves, with a rollback FluxCD made during it."""
    return {
        "phase": DeploymentPhase.READY.value,
        "rolloutStartedAt": OLD_ROLLOUT_START,
        "conditions": [
            _cr_condition(
                ConditionType.NETWORK_POLICIES_READY.value, "True", "AllApplied"
            ),
            _cr_condition(ConditionType.SECRETS_READY.value, "True", "AllApplied"),
            _cr_condition(ConditionType.HELM_RELEASE_READY.value, "True", "FluxReady"),
            _cr_condition(
                ConditionType.HELM_RELEASE_REMEDIATED.value, "True", "RollbackSucceeded"
            ),
            _cr_condition(ConditionType.READY.value, "True", "AllPhasesComplete"),
        ],
    }


ROLLOUT_HANDLERS = {
    "create": (kopf_on_styrmin_deployment_create, {}),
    "update": (kopf_on_styrmin_deployment_update, {"diff": ()}),
}


@pytest.mark.anyio
@pytest.mark.parametrize("internal", [False, True], ids=["platform", "internal"])
@pytest.mark.parametrize("handler_name", list(ROLLOUT_HANDLERS))
async def test_rollout_resets_helm_release_ready_and_records_its_start(
    phases: dict[str, Any], handler_name: str, internal: bool
) -> None:
    handler, extra = ROLLOUT_HANDLERS[handler_name]
    patch = _Patch()
    before = datetime.now(tz=UTC)

    await handler(
        spec={**SPEC, "internal": internal},
        status=_previous_rollout_status(),
        name="my-deployment",
        namespace=NAMESPACE,
        patch=patch,
        logger=_Logger(),
        **extra,
    )

    hr_ready = _condition(patch, ConditionType.HELM_RELEASE_READY)
    assert hr_ready is not None
    assert (hr_ready["status"], hr_ready["reason"]) == ("Unknown", "Progressing")
    assert _condition(patch, ConditionType.HELM_RELEASE_REMEDIATED) is None
    started = datetime.fromisoformat(patch.status["rolloutStartedAt"])
    assert before <= started <= datetime.now(tz=UTC)


@pytest.mark.anyio
@pytest.mark.parametrize("handler_name", list(ROLLOUT_HANDLERS))
async def test_rollout_reset_survives_a_failed_phase(
    phases: dict[str, Any], handler_name: str
) -> None:
    handler, extra = ROLLOUT_HANDLERS[handler_name]
    phases["prerequisites"].return_value = PhaseResult(success=False, errors=["quota"])
    patch = _Patch()

    with pytest.raises(kopf.TemporaryError, match="quota"):
        await handler(
            spec=SPEC,
            status=_previous_rollout_status(),
            name="my-deployment",
            namespace=NAMESPACE,
            patch=patch,
            logger=_Logger(),
            **extra,
        )

    hr_ready = _condition(patch, ConditionType.HELM_RELEASE_READY)
    assert hr_ready is not None
    assert hr_ready["status"] == "Unknown"
    assert patch.status["rolloutStartedAt"] != OLD_ROLLOUT_START


def _resumed_status(*, rollout_started_at: str | None) -> dict[str, Any]:
    status = _rolling_out_status()
    status["conditions"][2] = _cr_condition(
        ConditionType.HELM_RELEASE_READY.value,
        "False",
        "UpgradeFailed",
        UPGRADE_FAILURE,
    )
    if rollout_started_at is None:
        del status["rolloutStartedAt"]
    else:
        status["rolloutStartedAt"] = rollout_started_at
    return status


@pytest.mark.anyio
async def test_resume_keeps_helm_release_ready_and_the_rollout_start(
    phases: dict[str, Any],
) -> None:
    status = _resumed_status(rollout_started_at=OLD_ROLLOUT_START)
    patch = _Patch()

    await kopf_on_styrmin_deployment_resume(
        spec=SPEC,
        status=status,
        name="my-deployment",
        namespace=NAMESPACE,
        patch=patch,
        logger=_Logger(),
    )

    assert "rolloutStartedAt" not in patch.status
    hr_ready = get_condition(
        patch.status.get("conditions", status["conditions"]),
        ConditionType.HELM_RELEASE_READY.value,
    )
    assert hr_ready is not None
    assert (hr_ready["status"], hr_ready["reason"]) == ("False", "UpgradeFailed")


@pytest.mark.anyio
async def test_resume_records_a_missing_rollout_start(phases: dict[str, Any]) -> None:
    patch = _Patch()
    before = datetime.now(tz=UTC)

    await kopf_on_styrmin_deployment_resume(
        spec=SPEC,
        status=_resumed_status(rollout_started_at=None),
        name="my-deployment",
        namespace=NAMESPACE,
        patch=patch,
        logger=_Logger(),
    )

    started = datetime.fromisoformat(patch.status["rolloutStartedAt"])
    assert before <= started <= datetime.now(tz=UTC)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "phase",
    [DeploymentPhase.READY, DeploymentPhase.FAILED, DeploymentPhase.DELETED],
    ids=lambda phase: phase.value,
)
async def test_resume_outside_a_rollout_records_no_start(
    phases: dict[str, Any], phase: DeploymentPhase
) -> None:
    patch = _Patch()

    await kopf_on_styrmin_deployment_resume(
        spec=SPEC,
        status={"phase": phase.value, "conditions": []},
        name="my-deployment",
        namespace=NAMESPACE,
        patch=patch,
        logger=_Logger(),
    )

    assert "rolloutStartedAt" not in patch.status
