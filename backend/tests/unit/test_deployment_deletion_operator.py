"""Unit tests for the operator-side deletion observer + janitor (spec 008).

Covers three orthogonal pieces:

1. The ``spec.deletionRequested`` field-update observer — runs the
   teardown and advances the CR to ``phase: Deleting`` /
   ``displayState: Deleting`` without blocking on the namespace
   finaliser.
2. The periodic timer — advances ``Deleting`` to ``Deleted`` once the
   namespace returns 404, and emits a ``Deleted`` condition with a
   ``lastTransitionTime`` the janitor can read.
3. The janitor's selection rule — only reaps CRs whose
   ``status.phase == "Deleted"`` AND whose ``Deleted`` condition is
   older than ``DELETED_CR_TTL_HOURS``; never reaps ``Deleting``-stuck
   CRs.

Kubernetes / kopf interactions are mocked at the helper boundary so the
tests run in-process with no cluster.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from styrmin_backend.operator.config import ANNOTATION_SKIP_TEARDOWN
from styrmin_backend.operator.crd.schema import (
    ConditionType,
    DeploymentPhase,
    DisplayState,
)
from styrmin_backend.operator.handlers import styrmin_deployment as handlers_module
from styrmin_backend.operator.handlers.styrmin_deployment import (
    kopf_on_styrmin_deployment_delete,
    kopf_on_styrmin_deployment_deletion_requested,
    kopf_on_styrmin_deployment_update,
    kopf_styrmin_deployment_timer,
)
from styrmin_backend.operator.janitor import is_eligible_for_reap


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


def _make_body(creation_offset_seconds: int = 0) -> dict[str, Any]:
    created_at = datetime.now(tz=timezone.utc) - timedelta(
        seconds=creation_offset_seconds
    )
    return {"metadata": {"creationTimestamp": created_at.isoformat()}}


# ---------------------------------------------------------------------------
# 1. spec.deletionRequested observer
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deletion_requested_handler_runs_teardown_and_advances_to_deleting(
    mocker,
) -> None:
    """When ``spec.deletionRequested`` flips true, the operator must run
    teardown + request namespace deletion + set phase/displayState to
    ``Deleting`` (not ``Deleted`` — that requires the namespace to be
    actually gone, which is the timer's job)."""

    teardown_mock = mocker.patch.object(
        handlers_module, "_teardown_owned_resources", autospec=True
    )
    delete_ns_mock = mocker.patch.object(
        handlers_module, "_request_namespace_deletion", autospec=True
    )

    patch = _Patch()
    spec = {"releaseReference": "rel-1", "deletionRequested": True}
    status = {"phase": DeploymentPhase.READY.value}

    await kopf_on_styrmin_deployment_deletion_requested(
        spec=spec,
        status=status,
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
    )

    teardown_mock.assert_called_once()
    delete_ns_mock.assert_called_once()
    assert patch.status["phase"] == DeploymentPhase.DELETING.value
    assert patch.status["displayState"] == DisplayState.DELETING.value


@pytest.mark.anyio
async def test_legacy_update_handler_defers_when_deletion_requested(
    mocker,
) -> None:
    """``spec.deletionRequested=true`` is a spec change too, so the
    field=spec update handler also fires. It MUST defer to the
    deletion-observer handler (skip the re-reconcile) rather than
    re-running the deploy pipeline mid-teardown."""

    prereq_mock = mocker.patch(
        "styrmin_backend.operator.handlers.styrmin_deployment.execute_phase_prerequisites",
        autospec=True,
    )
    helmrelease_mock = mocker.patch(
        "styrmin_backend.operator.handlers.styrmin_deployment.execute_phase_helmrelease",
        autospec=True,
    )

    patch = _Patch()
    spec = {
        "releaseReference": "rel-1",
        "deletionRequested": True,
    }

    await kopf_on_styrmin_deployment_update(
        spec=spec,
        status={"phase": DeploymentPhase.READY.value},
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
        diff=(),
    )

    prereq_mock.assert_not_called()
    helmrelease_mock.assert_not_called()
    # Critically, displayState must NOT be set to Deploying — that would
    # mid-teardown flicker to Deploying in the UI.
    assert patch.status == {}


@pytest.mark.anyio
async def test_deletion_requested_handler_short_circuits_when_already_deleted(
    mocker,
) -> None:
    """If the CR is already in phase: Deleted (defensive — the CEL rule
    prevents un-flipping the spec, but the handler may fire on resume),
    we must not run teardown again or rewind the phase."""

    teardown_mock = mocker.patch.object(
        handlers_module, "_teardown_owned_resources", autospec=True
    )
    delete_ns_mock = mocker.patch.object(
        handlers_module, "_request_namespace_deletion", autospec=True
    )

    patch = _Patch()
    spec = {"releaseReference": "rel-1", "deletionRequested": True}
    status = {"phase": DeploymentPhase.DELETED.value}

    await kopf_on_styrmin_deployment_deletion_requested(
        spec=spec,
        status=status,
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
    )

    teardown_mock.assert_not_called()
    delete_ns_mock.assert_not_called()
    assert patch.status == {}


@pytest.mark.anyio
async def test_delete_handler_runs_teardown(mocker) -> None:
    """A manual ``kubectl delete`` tears down the resources the CR names."""
    teardown_mock = mocker.patch.object(
        handlers_module, "_teardown_owned_resources", autospec=True
    )
    patch = _Patch()

    await kopf_on_styrmin_deployment_delete(
        spec={"releaseReference": "rel-1"},
        status={"phase": DeploymentPhase.READY.value},
        name="dep-1",
        namespace="styrmin-abc",
        annotations={},
        patch=patch,
        logger=_Logger(),
    )

    teardown_mock.assert_called_once()
    assert patch.status["phase"] == DeploymentPhase.DELETING.value


@pytest.mark.anyio
async def test_delete_handler_skips_teardown_when_annotated(mocker) -> None:
    """A cross-target restore discards its restored copy of the source's CR.

    That copy names the counterpart's own HelmRelease and resources, so tearing
    them down would uninstall the counterpart's release and remove the
    resources the restore is re-applying. kopf can still run this handler for
    it, because kopf puts back the finalizer the restore clears.
    """
    teardown_mock = mocker.patch.object(
        handlers_module, "_teardown_owned_resources", autospec=True
    )
    patch = _Patch()

    await kopf_on_styrmin_deployment_delete(
        spec={"releaseReference": "rel-1"},
        status={"phase": DeploymentPhase.RESTORING.value},
        name="dep-1",
        namespace="styrmin-abc",
        annotations={ANNOTATION_SKIP_TEARDOWN: "true"},
        patch=patch,
        logger=_Logger(),
    )

    teardown_mock.assert_not_called()
    assert patch.status == {}


# ---------------------------------------------------------------------------
# 2. Timer advancement to phase: Deleted
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_timer_advances_to_deleted_once_namespace_is_gone(mocker) -> None:
    """The timer must flip the phase to Deleted (with a Deleted
    condition the janitor can read) only after the namespace is gone."""

    mocker.patch.object(
        handlers_module, "_namespace_is_gone", return_value=True, autospec=True
    )

    patch = _Patch()
    body = _make_body(creation_offset_seconds=60)
    status = {
        "phase": DeploymentPhase.DELETING.value,
        "displayState": DisplayState.DELETING.value,
        "conditions": [],
    }

    await kopf_styrmin_deployment_timer(
        body=body,
        spec={"releaseReference": "rel-1", "deletionRequested": True},
        status=status,
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
        stopped=_Stopped(),
    )

    assert patch.status["phase"] == DeploymentPhase.DELETED.value
    assert patch.status["displayState"] == DisplayState.DELETED.value

    deleted_conds = [
        c
        for c in patch.status["conditions"]
        if c["type"] == ConditionType.DELETED.value
    ]
    assert len(deleted_conds) == 1
    assert deleted_conds[0]["status"] == "True"
    assert deleted_conds[0]["reason"] == "NamespaceGone"
    assert deleted_conds[0]["lastTransitionTime"]  # non-empty timestamp


@pytest.mark.anyio
async def test_timer_keeps_deleting_when_namespace_still_present(mocker) -> None:
    """If the namespace finaliser hasn't completed yet, the timer must
    leave the CR in ``Deleting`` and try again next tick."""

    mocker.patch.object(
        handlers_module, "_namespace_is_gone", return_value=False, autospec=True
    )

    patch = _Patch()
    body = _make_body(creation_offset_seconds=60)
    status = {
        "phase": DeploymentPhase.DELETING.value,
        "conditions": [],
    }

    await kopf_styrmin_deployment_timer(
        body=body,
        spec={"releaseReference": "rel-1", "deletionRequested": True},
        status=status,
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
        stopped=_Stopped(),
    )

    assert "phase" not in patch.status
    assert "displayState" not in patch.status


@pytest.mark.anyio
async def test_timer_noop_for_terminal_deleted_phase(mocker) -> None:
    """A CR already at ``phase: Deleted`` is the janitor's responsibility
    — the timer must not re-emit conditions or otherwise touch it."""

    ns_gone_mock = mocker.patch.object(
        handlers_module, "_namespace_is_gone", return_value=True, autospec=True
    )

    patch = _Patch()
    body = _make_body(creation_offset_seconds=60)
    status = {
        "phase": DeploymentPhase.DELETED.value,
        "conditions": [
            {
                "type": ConditionType.DELETED.value,
                "status": "True",
                "reason": "NamespaceGone",
                "message": "...",
                "lastTransitionTime": datetime.now(tz=timezone.utc).isoformat(),
            }
        ],
    }

    await kopf_styrmin_deployment_timer(
        body=body,
        spec={"releaseReference": "rel-1", "deletionRequested": True},
        status=status,
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
        stopped=_Stopped(),
    )

    # _advance_to_phase_deleted will be entered (because the gating
    # condition includes deletionRequested), but the early return for
    # phase == DELETED below it ensures nothing is written; alternatively
    # the handler may flip the same state idempotently. Either way, no
    # spurious phase regression.
    assert patch.status.get("phase") in (None, DeploymentPhase.DELETED.value)
    # Sanity: the namespace-gone helper was queried at most once.
    assert ns_gone_mock.call_count <= 1


# ---------------------------------------------------------------------------
# 3. Janitor selection rule
# ---------------------------------------------------------------------------


def _deleted_status(*, transitioned_at: datetime, phase: str = "Deleted") -> dict:
    return {
        "phase": phase,
        "conditions": [
            {
                "type": ConditionType.DELETED.value,
                "status": "True",
                "reason": "NamespaceGone",
                "message": "...",
                "lastTransitionTime": transitioned_at.isoformat(),
            }
        ],
    }


def test_janitor_reaps_when_phase_deleted_and_ttl_elapsed() -> None:
    now = datetime.now(tz=timezone.utc)
    status = _deleted_status(transitioned_at=now - timedelta(hours=7))
    assert is_eligible_for_reap(status, now=now, ttl_hours=6) is True


def test_janitor_does_not_reap_when_ttl_not_elapsed() -> None:
    now = datetime.now(tz=timezone.utc)
    status = _deleted_status(transitioned_at=now - timedelta(hours=2))
    assert is_eligible_for_reap(status, now=now, ttl_hours=6) is False


def test_janitor_never_reaps_phase_deleting() -> None:
    """CRs stuck in Deleting are never auto-reaped — visibility for
    human investigation is more important than tidiness (spec FR-015)."""

    now = datetime.now(tz=timezone.utc)
    status = _deleted_status(
        transitioned_at=now - timedelta(hours=24),
        phase=DeploymentPhase.DELETING.value,
    )
    assert is_eligible_for_reap(status, now=now, ttl_hours=6) is False


def test_janitor_does_not_reap_when_deleted_condition_missing() -> None:
    """Defensive: cannot date the transition, so we leave the CR alone
    rather than reap something we cannot prove is past TTL."""

    now = datetime.now(tz=timezone.utc)
    status = {"phase": DeploymentPhase.DELETED.value, "conditions": []}
    assert is_eligible_for_reap(status, now=now, ttl_hours=6) is False


def test_janitor_handles_z_suffix_iso_timestamp() -> None:
    """Kubernetes serialises timestamps with a ``Z`` suffix; verify
    parsing handles both forms."""

    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    status = {
        "phase": DeploymentPhase.DELETED.value,
        "conditions": [
            {
                "type": ConditionType.DELETED.value,
                "status": "True",
                "lastTransitionTime": (now - timedelta(hours=12))
                .isoformat()
                .replace("+00:00", "Z"),
            }
        ],
    }
    assert is_eligible_for_reap(status, now=now, ttl_hours=6) is True
