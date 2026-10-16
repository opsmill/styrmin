"""The workload readiness polls wait until extra pods are gone after a scale-down (023)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrmin_backend.agent.tasks import shared


def _workload(
    *, spec: int, replicas: int, ready: int, available: int | None = None
) -> Any:
    status = SimpleNamespace(
        observed_generation=2,
        replicas=replicas,
        updated_replicas=ready,
        ready_replicas=ready,
        available_replicas=ready if available is None else available,
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(name="server", generation=2),
        spec=SimpleNamespace(replicas=spec),
        status=status,
    )


async def _poll_deployments(workload: Any) -> None:
    with (
        patch.object(
            shared,
            "get_deployments",
            AsyncMock(return_value=SimpleNamespace(items=[workload])),
        ),
        patch.object(shared, "get_run_logger", MagicMock()),
    ):
        await shared.poll_kubernetes_deployments_status.fn(namespace="ns")


async def _poll_stateful_sets(workload: Any) -> None:
    with (
        patch.object(
            shared,
            "get_stateful_sets",
            AsyncMock(return_value=SimpleNamespace(items=[workload])),
        ),
        patch.object(shared, "get_run_logger", MagicMock()),
    ):
        await shared.poll_kubernetes_stateful_sets_status.fn(namespace="ns")


@pytest.mark.parametrize("poll", [_poll_deployments, _poll_stateful_sets])
async def test_scale_down_waits_for_the_extra_pods(poll: Any) -> None:
    # Scaled from 3 to 1: one pod is ready, two still run.
    with pytest.raises(Exception, match=r"waiting for extra replicas to stop \(3/1\)"):
        await poll(_workload(spec=1, replicas=3, ready=1))


@pytest.mark.parametrize("poll", [_poll_deployments, _poll_stateful_sets])
async def test_stopped_component_waits_until_no_pod_runs(poll: Any) -> None:
    with pytest.raises(Exception, match=r"\(1/0\)"):
        await poll(_workload(spec=0, replicas=1, ready=0))


@pytest.mark.parametrize("poll", [_poll_deployments, _poll_stateful_sets])
async def test_settled_workload_passes(poll: Any) -> None:
    await poll(_workload(spec=2, replicas=2, ready=2))
