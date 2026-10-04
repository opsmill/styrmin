"""Unit tests for the styrmin-deployment kopf timer.

Specifically: verify the timer no-ops when ``phase == Restoring`` so the
restore workflow can drive the post-velero lifecycle without the timer
tripping its 300 s readiness timeout or racing phase advancement. This
is the regression that caused deployments to land in 'failed' after a
successful velero restore.

Also: the timer fails the CR when the HelmRelease reports the
component-container guard failure (018, FR-007).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.operator import reconciler as reconciler_module
from styrmin_backend.operator.crd.schema import (
    ConditionType,
    DeploymentPhase,
    DisplayState,
)
from styrmin_backend.operator.crd.status import get_condition
from styrmin_backend.operator.handlers import styrmin_deployment as handlers_module
from styrmin_backend.operator.handlers.styrmin_deployment import (
    kopf_styrmin_deployment_timer,
)
from styrmin_backend.services.component_container.exceptions import (
    ComponentContainerNotFoundError,
)


class _Patch:
    """Minimal stand-in for ``kopf.Patch``.

    kopf.Patch acts like a dict-of-dicts; for assertions we just inspect
    what the timer wrote into ``status``.
    """

    def __init__(self) -> None:
        self.status: dict[str, Any] = {}
        self.spec: dict[str, Any] = {}
        self.metadata: dict[str, Any] = {}


class _Logger:
    """Silent logger; the timer only writes warnings on the timeout branch."""

    def info(self, *_: Any, **__: Any) -> None: ...
    def warning(self, *_: Any, **__: Any) -> None: ...
    def debug(self, *_: Any, **__: Any) -> None: ...
    def error(self, *_: Any, **__: Any) -> None: ...


def _make_body(creation_offset_seconds: int = 0) -> dict[str, Any]:
    """Build a kopf-shaped body dict with a creationTimestamp.

    *creation_offset_seconds* is subtracted from "now" so callers can
    simulate a CRD that has been alive long enough to trigger the
    300 s readiness timeout (default 0 = newly created).
    """
    created_at = datetime.now(tz=timezone.utc) - timedelta(
        seconds=creation_offset_seconds
    )
    return {"metadata": {"creationTimestamp": created_at.isoformat()}}


@pytest.mark.anyio
async def test_timer_skips_when_phase_is_restoring_even_after_timeout() -> None:
    """A CRD stuck at phase=Restoring for 600 s must NOT have its
    displayState bumped to Error by the operator's timeout branch.

    Reproduces the post-restore "Deployment did not reach Ready within
    300s" regression: velero recreates the CRD with empty status, the
    restore workflow patches it to phase=Restoring, then the timer used
    to fire the timeout because phase was not in (Ready, Failed, Deleting).
    """
    patch = _Patch()
    body = _make_body(creation_offset_seconds=600)
    status = {
        "phase": DeploymentPhase.RESTORING.value,
        "displayState": DisplayState.RESTORING.value,
    }

    await kopf_styrmin_deployment_timer(
        body=body,
        spec={},
        status=status,
        name="my-deployment",
        namespace="styrmin-deadbeef",
        patch=patch,
        logger=_Logger(),
    )

    # Nothing should have been patched — the timer must defer to the
    # restore workflow.
    assert patch.status == {}


@pytest.mark.anyio
async def test_timer_still_trips_timeout_for_non_restoring_phase() -> None:
    """Sanity check: the timeout branch still fires for other in-progress
    phases (otherwise the early-return on Restoring could mask a broken
    timeout for normal deployments)."""
    patch = _Patch()
    body = _make_body(creation_offset_seconds=600)
    status = {
        "phase": DeploymentPhase.CREATING_HELM_RELEASE.value,
        "displayState": DisplayState.DEPLOYING.value,
    }

    await kopf_styrmin_deployment_timer(
        body=body,
        spec={},
        status=status,
        name="my-deployment",
        namespace="styrmin-deadbeef",
        patch=patch,
        logger=_Logger(),
    )

    assert patch.status.get("displayState") == DisplayState.ERROR.value
    assert "did not reach Ready" in patch.status.get("message", "")


# --- Component-container guard failure surfacing (018, T056) ---

# helm-controller v1 wraps the post-renderer error in its Released/Ready condition message.
GUARD_FAILURE_MESSAGE = (
    "Helm upgrade failed for release styrmin-deadbeef/my-release with chart simple-app@0.1.0: "
    "error while running post render on files: error in remove for path: "
    "'/spec/template/spec/styrmin.io~1component-container~1server~1wrong-name/image': "
    "Unable to remove nonexistent key: image: missing value"
)
TIMEOUT_FAILURE_MESSAGE = (
    "Helm upgrade failed for release styrmin-deadbeef/my-release with chart simple-app@0.1.0: "
    "context deadline exceeded"
)
EXPECTED_GUARD_MESSAGE = ComponentContainerNotFoundError(
    component_name="server", container="wrong-name"
).args[0]
SPEC = {"releaseReference": "my-release"}


def _hr_condition(
    type_: str,
    status: str,
    reason: str,
    message: str,
    observed_generation: int | None,
) -> dict[str, Any]:
    condition: dict[str, Any] = {
        "type": type_,
        "status": status,
        "reason": reason,
        "message": message,
        "lastTransitionTime": "2026-10-04T10:00:00Z",
    }
    if observed_generation is not None:
        condition["observedGeneration"] = observed_generation
    return condition


def _helmrelease(
    *,
    generation: int,
    conditions: list[dict[str, Any]],
    last_attempted_generation: int | None = None,
) -> dict[str, Any]:
    """A HelmRelease as helm-controller v1 reports it (``helm.toolkit.fluxcd.io/v2``)."""
    status: dict[str, Any] = {"conditions": conditions, "observedGeneration": 1}
    if last_attempted_generation is not None:
        status["lastAttemptedGeneration"] = last_attempted_generation
    return {
        "apiVersion": "helm.toolkit.fluxcd.io/v2",
        "kind": "HelmRelease",
        "metadata": {
            "name": "my-release",
            "namespace": "styrmin-deadbeef",
            "generation": generation,
        },
        "status": status,
    }


def _guard_failed_helmrelease(generation: int = 2) -> dict[str, Any]:
    return _helmrelease(
        generation=generation,
        last_attempted_generation=generation,
        conditions=[
            _hr_condition(
                "Ready", "False", "UpgradeFailed", GUARD_FAILURE_MESSAGE, generation
            ),
            _hr_condition(
                "Released", "False", "UpgradeFailed", GUARD_FAILURE_MESSAGE, generation
            ),
        ],
    )


def _stale_hr_ready_condition() -> dict[str, Any]:
    return {
        "type": ConditionType.HELM_RELEASE_READY.value,
        "status": "True",
        "reason": "FluxReady",
        "message": "HelmRelease is Ready",
    }


def _mock_helmrelease(mocker: Any, helmrelease: dict[str, Any] | None) -> Any:
    return mocker.patch.object(
        reconciler_module,
        "_get_helmrelease",
        new=mocker.AsyncMock(return_value=helmrelease),
    )


async def _run_timer(status: dict[str, Any], patch: _Patch) -> None:
    await kopf_styrmin_deployment_timer(
        body=_make_body(),
        spec=SPEC,
        status=status,
        name="my-deployment",
        namespace="styrmin-deadbeef",
        patch=patch,
        logger=_Logger(),
    )


def _assert_failed_on_guard(patch: _Patch) -> None:
    assert patch.status["phase"] == DeploymentPhase.FAILED.value
    assert patch.status["displayState"] == DisplayState.ERROR.value
    assert patch.status["message"] == EXPECTED_GUARD_MESSAGE
    hr_ready = get_condition(
        patch.status["conditions"], ConditionType.HELM_RELEASE_READY
    )
    assert hr_ready is not None
    assert hr_ready["status"] == "False"
    assert hr_ready["reason"] == "ComponentContainerNotFound"
    assert hr_ready["message"] == EXPECTED_GUARD_MESSAGE


def test_expected_guard_message_names_component_and_container() -> None:
    assert "'server'" in EXPECTED_GUARD_MESSAGE
    assert "'wrong-name'" in EXPECTED_GUARD_MESSAGE


@pytest.mark.anyio
async def test_guard_failure_fails_deployment_while_creating_helm_release(
    mocker: Any,
) -> None:
    get_hr = _mock_helmrelease(mocker, _guard_failed_helmrelease(generation=1))
    services = mocker.patch.object(handlers_module, "execute_phase_services")
    patch = _Patch()

    await _run_timer(
        {
            "phase": DeploymentPhase.CREATING_HELM_RELEASE.value,
            "displayState": DisplayState.DEPLOYING.value,
            "conditions": [],
        },
        patch,
    )

    _assert_failed_on_guard(patch)
    get_hr.assert_awaited_once_with(
        namespace="styrmin-deadbeef", release_reference="my-release"
    )
    services.assert_not_called()


@pytest.mark.anyio
async def test_guard_failure_overrides_stale_helm_release_ready_on_update(
    mocker: Any,
) -> None:
    """On an update the previous rollout's HelmReleaseReady=True must not advance the CR."""
    _mock_helmrelease(mocker, _guard_failed_helmrelease())
    services = mocker.patch.object(handlers_module, "execute_phase_services")
    patch = _Patch()

    await _run_timer(
        {
            "phase": DeploymentPhase.CREATING_HELM_RELEASE.value,
            "displayState": DisplayState.DEPLOYING.value,
            "conditions": [_stale_hr_ready_condition()],
        },
        patch,
    )

    _assert_failed_on_guard(patch)
    services.assert_not_called()


@pytest.mark.anyio
async def test_guard_failure_message_replaces_readiness_timeout_message(
    mocker: Any,
) -> None:
    """A CR older than the readiness timeout reports the typed cause, not the timeout."""
    _mock_helmrelease(mocker, _guard_failed_helmrelease())
    patch = _Patch()

    await kopf_styrmin_deployment_timer(
        body=_make_body(creation_offset_seconds=600),
        spec=SPEC,
        status={
            "phase": DeploymentPhase.CREATING_HELM_RELEASE.value,
            "displayState": DisplayState.DEPLOYING.value,
            "conditions": [_stale_hr_ready_condition()],
        },
        name="my-deployment",
        namespace="styrmin-deadbeef",
        patch=patch,
        logger=_Logger(),
    )

    _assert_failed_on_guard(patch)


@pytest.mark.anyio
async def test_guard_failure_fails_ready_deployment_before_drift_detection(
    mocker: Any,
) -> None:
    _mock_helmrelease(mocker, _guard_failed_helmrelease())
    list_resources = mocker.patch.object(
        reconciler_module, "list_managed_resources", new=mocker.AsyncMock()
    )
    patch = _Patch()

    await _run_timer(
        {
            "phase": DeploymentPhase.READY.value,
            "displayState": DisplayState.RUNNING.value,
            "conditions": [_stale_hr_ready_condition()],
        },
        patch,
    )

    _assert_failed_on_guard(patch)
    list_resources.assert_not_called()


@pytest.mark.parametrize(
    "ready",
    [
        _hr_condition(
            "Ready", "False", "UpgradeFailed", "Failed to upgrade after 1 attempt(s)", 2
        ),
        _hr_condition("Ready", "Unknown", "Progressing", "Fulfilling prerequisites", 2),
    ],
    ids=["ready-false-summary", "ready-unknown-retrying"],
)
@pytest.mark.anyio
async def test_guard_key_in_released_condition_matches(
    mocker: Any, ready: dict[str, Any]
) -> None:
    _mock_helmrelease(
        mocker,
        _helmrelease(
            generation=2,
            conditions=[
                ready,
                _hr_condition(
                    "Released", "False", "UpgradeFailed", GUARD_FAILURE_MESSAGE, 2
                ),
            ],
        ),
    )
    patch = _Patch()

    await _run_timer(
        {
            "phase": DeploymentPhase.READY.value,
            "displayState": DisplayState.RUNNING.value,
            "conditions": [_stale_hr_ready_condition()],
        },
        patch,
    )

    _assert_failed_on_guard(patch)


@pytest.mark.parametrize(
    "helmrelease",
    [
        # Guard failure from the previous generation, before helm-controller retried.
        _helmrelease(
            generation=3,
            last_attempted_generation=2,
            conditions=[
                _hr_condition(
                    "Ready", "False", "UpgradeFailed", GUARD_FAILURE_MESSAGE, 2
                ),
                _hr_condition(
                    "Released", "False", "UpgradeFailed", GUARD_FAILURE_MESSAGE, 2
                ),
            ],
        ),
        # Current generation failed for another reason; the guard message is stale.
        _helmrelease(
            generation=3,
            conditions=[
                _hr_condition(
                    "Ready", "False", "ArtifactFailed", "HelmChart is not ready", 3
                ),
                _hr_condition(
                    "Released", "False", "UpgradeFailed", GUARD_FAILURE_MESSAGE, 2
                ),
            ],
        ),
        # No condition observedGeneration: falls back to a stale lastAttemptedGeneration.
        _helmrelease(
            generation=3,
            last_attempted_generation=2,
            conditions=[
                _hr_condition(
                    "Ready", "False", "UpgradeFailed", GUARD_FAILURE_MESSAGE, None
                ),
            ],
        ),
        # A non-guard failure for the current generation keeps today's behaviour.
        _helmrelease(
            generation=3,
            conditions=[
                _hr_condition(
                    "Ready", "False", "UpgradeFailed", TIMEOUT_FAILURE_MESSAGE, 3
                ),
                _hr_condition(
                    "Released", "False", "UpgradeFailed", TIMEOUT_FAILURE_MESSAGE, 3
                ),
            ],
        ),
        # The fix rolled out: Ready=True wins over any leftover message.
        _helmrelease(
            generation=3,
            conditions=[
                _hr_condition(
                    "Ready", "True", "UpgradeSucceeded", "Helm upgrade succeeded", 3
                ),
                _hr_condition("Remediated", "False", "x", GUARD_FAILURE_MESSAGE, 3),
            ],
        ),
        {"metadata": {"generation": 3}},
        None,
    ],
    ids=[
        "stale-generation",
        "stale-released-message",
        "stale-last-attempted-generation",
        "non-guard-failure",
        "ready-true",
        "no-status",
        "not-found",
    ],
)
@pytest.mark.anyio
async def test_ready_deployment_ignores_non_matching_helmrelease(
    mocker: Any, helmrelease: dict[str, Any] | None
) -> None:
    _mock_helmrelease(mocker, helmrelease)
    mocker.patch(
        "styrmin_backend.operator.pipeline.build_desired_resources_from_crd",
        return_value=[],
    )
    list_resources = mocker.patch.object(
        reconciler_module,
        "list_managed_resources",
        new=mocker.AsyncMock(return_value=[]),
    )
    patch = _Patch()

    await _run_timer(
        {
            "phase": DeploymentPhase.READY.value,
            "displayState": DisplayState.RUNNING.value,
            "conditions": [_stale_hr_ready_condition()],
        },
        patch,
    )

    assert patch.status == {}
    assert list_resources.await_count == 3


@pytest.mark.anyio
async def test_creating_helm_release_keeps_waiting_on_stale_guard_failure(
    mocker: Any,
) -> None:
    """After the user fixes the config, the previous generation's failure must not re-fail the CR."""
    get_hr = _mock_helmrelease(
        mocker,
        _helmrelease(
            generation=3,
            last_attempted_generation=2,
            conditions=[
                _hr_condition(
                    "Ready", "False", "UpgradeFailed", GUARD_FAILURE_MESSAGE, 2
                ),
            ],
        ),
    )
    patch = _Patch()

    await _run_timer(
        {
            "phase": DeploymentPhase.CREATING_HELM_RELEASE.value,
            "displayState": DisplayState.DEPLOYING.value,
            "conditions": [
                {
                    "type": ConditionType.HELM_RELEASE_READY.value,
                    "status": "False",
                    "reason": "ComponentContainerNotFound",
                    "message": EXPECTED_GUARD_MESSAGE,
                }
            ],
        },
        patch,
    )

    assert patch.status == {}
    # One GET for the guard, one for the existing readiness check.
    assert get_hr.await_count == 2


@pytest.mark.parametrize(
    ("helmrelease", "expected"),
    [
        (_guard_failed_helmrelease(), ("server", "wrong-name")),
        (
            _helmrelease(
                generation=2,
                last_attempted_generation=2,
                conditions=[
                    _hr_condition(
                        "Ready", "False", "UpgradeFailed", GUARD_FAILURE_MESSAGE, None
                    ),
                ],
            ),
            ("server", "wrong-name"),
        ),
        (_helmrelease(generation=2, conditions=[]), None),
        ({}, None),
    ],
    ids=["observed-generation", "last-attempted-generation", "no-conditions", "empty"],
)
@pytest.mark.anyio
async def test_read_helmrelease_guard_failure(
    mocker: Any,
    helmrelease: dict[str, Any],
    expected: tuple[str, str] | None,
) -> None:
    custom_api = mocker.MagicMock()
    custom_api.get_namespaced_custom_object = mocker.AsyncMock(return_value=helmrelease)
    mocker.patch.object(
        reconciler_module.kubeclient, "CustomObjectsApi", return_value=custom_api
    )
    mocker.patch(
        "styrmin_backend.operator.kubernetes.get_kubernetes_client",
        return_value=_FakeClient(),
    )

    result = await reconciler_module.read_helmrelease_guard_failure(
        namespace="styrmin-deadbeef", release_reference="my-release"
    )

    assert result == expected
    custom_api.get_namespaced_custom_object.assert_awaited_once_with(
        group="helm.toolkit.fluxcd.io",
        version="v2",
        namespace="styrmin-deadbeef",
        plural="helmreleases",
        name="my-release",
    )


@pytest.mark.anyio
async def test_read_helmrelease_guard_failure_when_helmrelease_missing(
    mocker: Any,
) -> None:
    custom_api = mocker.MagicMock()
    custom_api.get_namespaced_custom_object = mocker.AsyncMock(
        side_effect=ApiException(status=404)
    )
    mocker.patch.object(
        reconciler_module.kubeclient, "CustomObjectsApi", return_value=custom_api
    )
    mocker.patch(
        "styrmin_backend.operator.kubernetes.get_kubernetes_client",
        return_value=_FakeClient(),
    )

    assert (
        await reconciler_module.read_helmrelease_guard_failure(
            namespace="styrmin-deadbeef", release_reference="my-release"
        )
        is None
    )


class _FakeClient:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_: object) -> None:
        return None
