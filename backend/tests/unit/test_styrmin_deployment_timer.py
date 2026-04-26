"""Unit tests for the styrmin-deployment kopf timer.

Specifically: verify the timer no-ops when ``phase == Restoring`` so the
restore workflow can drive the post-velero lifecycle without the timer
tripping its 300 s readiness timeout or racing phase advancement. This
is the regression that caused deployments to land in 'failed' after a
successful velero restore.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from styrmin_backend.operator.crd.schema import DeploymentPhase, DisplayState
from styrmin_backend.operator.handlers.styrmin_deployment import (
    kopf_styrmin_deployment_timer,
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
