"""Unit tests for the result payload of ``execute_velero_backup_flow`` (#136).

The USER flow hands its result to ``execute_backup_workflow`` through a Prefect
Variable. These tests pin what that payload says about the backup size: the
byte sum of the PodVolumeBackups, never Velero's ``backupItemOperationsCompleted``
count. The flow body runs through ``Flow.fn`` with every Kubernetes and Prefect
boundary patched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrmin_backend.agent.service.kubernetes.velero.client import VeleroClientError
from styrmin_backend.workflows.templates.backup import execute_velero_backup_flow

MODULE = "styrmin_backend.workflows.templates.backup"
VELERO_CLIENT = "styrmin_backend.agent.service.kubernetes.velero.client.VeleroClient"
LOAD_CONFIG = (
    "styrmin_backend.agent.service.kubernetes.dependency.load_kubernetes_config"
)


@dataclass
class FlowRun:
    payload: dict[str, Any]
    velero_client: MagicMock
    logger: MagicMock


async def _run_flow(
    *,
    phase: str,
    pod_volume_backups: list[dict[str, Any]] | Exception | None = None,
    hook_status: dict[str, int] | None = None,
    volumes: dict[str, list[str]] | None = None,
    post_hook_failures: dict[str, str] | None = None,
    pod_components: dict[str, str] | None = None,
) -> FlowRun:
    velero_backup: dict[str, Any] = {
        "metadata": {"name": "styrmin-backup-1", "namespace": "styrmin"},
        "status": {
            "phase": phase,
            "backupItemOperationsCompleted": 7,
            "expiration": "2026-11-05T10:00:00Z",
        },
    }
    if phase == "PartiallyFailed":
        velero_backup["status"]["errors"] = 1
    if hook_status is not None:
        velero_backup["status"]["hookStatus"] = hook_status
    velero_client = MagicMock()
    velero_client.create_backup_from_dict = AsyncMock()
    velero_client.poll_backup_status = AsyncMock(return_value=velero_backup)
    if isinstance(pod_volume_backups, Exception):
        velero_client.list_pod_volume_backups = AsyncMock(
            side_effect=pod_volume_backups
        )
    else:
        velero_client.list_pod_volume_backups = AsyncMock(
            return_value=pod_volume_backups or []
        )

    api_client = MagicMock()
    api_client.close = AsyncMock()
    pods = []
    for pod, component in (pod_components or {}).items():
        item = MagicMock()
        item.metadata.name = pod  # ``MagicMock(name=...)`` names the mock instead
        item.metadata.labels = {"styrmin/component": component}
        pods.append(item)
    core_api = MagicMock()
    core_api.list_namespaced_pod = AsyncMock(return_value=MagicMock(items=pods))
    variable = MagicMock()
    variable.set = AsyncMock()
    logger = MagicMock()

    with (
        patch("kubernetes_asyncio.client.ApiClient", return_value=api_client),
        patch("kubernetes_asyncio.client.CoreV1Api", return_value=core_api),
        patch(LOAD_CONFIG, AsyncMock()),
        patch(VELERO_CLIENT, return_value=velero_client),
        patch(f"{MODULE}.config", MagicMock()),
        patch(f"{MODULE}.get_run_logger", return_value=logger),
        patch(f"{MODULE}.flow_run_ctx", MagicMock(id="flow-run-1")),
        patch(f"{MODULE}.Variable", variable),
    ):
        await execute_velero_backup_flow.fn(
            crd_body={"kind": "Backup"},
            velero_backup_name="styrmin-backup-1",
            velero_namespace="styrmin",
            volumes=volumes,
            post_hook_failures=post_hook_failures,
        )

    variable.set.assert_awaited_once()
    return FlowRun(
        payload=variable.set.await_args.kwargs["value"],
        velero_client=velero_client,
        logger=logger,
    )


async def test_completed_backup_reports_pod_volume_bytes_not_operation_count() -> None:
    run = await _run_flow(
        phase="Completed",
        pod_volume_backups=[
            {"status": {"phase": "Completed", "progress": {"totalBytes": 2_048}}}
        ],
    )

    assert run.payload["volume_bytes"] == 2_048
    assert "backupItemOperationsCompleted" not in run.payload["status"]
    run.velero_client.list_pod_volume_backups.assert_awaited_once_with(
        "styrmin", "styrmin-backup-1"
    )


@pytest.mark.parametrize("phase", ["PartiallyFailed", "Failed"])
async def test_backup_that_did_not_complete_reports_no_size(phase: str) -> None:
    run = await _run_flow(
        phase=phase,
        pod_volume_backups=[
            {"status": {"phase": "Completed", "progress": {"totalBytes": 2_048}}}
        ],
    )

    assert run.payload["volume_bytes"] is None


async def test_failed_backup_checks_no_volume() -> None:
    """Velero stored nothing, so the failure is Velero's own."""
    run = await _run_flow(phase="Failed", volumes={"database": ["data"]})

    assert run.payload["problems"] == {}
    run.velero_client.list_pod_volume_backups.assert_not_awaited()


def _pvb(pod: str, volume: str) -> dict[str, Any]:
    return {
        "spec": {"pod": {"namespace": "app", "name": pod}, "volume": volume},
        "status": {"phase": "Completed", "progress": {"totalBytes": 1}},
    }


async def test_completed_backup_without_a_named_volume_fails() -> None:
    """Velero skips hostPath volumes with only a warning, and completes the backup."""
    run = await _run_flow(
        phase="Completed",
        pod_volume_backups=[_pvb("server-0", "storage")],
        volumes={"server": ["storage"], "database": ["data"]},
        pod_components={"server-0": "server", "database-0": "database"},
    )

    assert list(run.payload["problems"]) == ["database"]
    assert "did not back up volume data" in run.payload["problems"]["database"]
    reason = run.payload["status"]["failureReason"]
    assert reason.startswith("component database: Velero did not back up volume data")


async def test_completed_backup_with_every_named_volume_has_no_problem() -> None:
    run = await _run_flow(
        phase="Completed",
        pod_volume_backups=[_pvb("database-0", "data")],
        volumes={"database": ["data"]},
        pod_components={"database-0": "database"},
    )

    assert run.payload["problems"] == {}
    assert run.payload["status"]["failureReason"] == ""


async def test_unreadable_pod_volume_backups_fail_a_backup_with_named_volumes() -> None:
    run = await _run_flow(
        phase="Completed",
        pod_volume_backups=VeleroClientError("403 Forbidden"),
        volumes={"database": ["data"], "worker": []},
    )

    assert list(run.payload["problems"]) == ["database"]
    assert "403 Forbidden" in run.payload["problems"]["database"]


async def test_failed_post_hook_is_reported_on_its_component() -> None:
    run = await _run_flow(
        phase="PartiallyFailed",
        pod_volume_backups=[_pvb("database-0", "data")],
        hook_status={"hooksAttempted": 4, "hooksFailed": 1},
        volumes={"database": ["data"], "task-db": []},
        post_hook_failures={"database": "Neo4j was not paused"},
        pod_components={"database-0": "database"},
    )

    problem = run.payload["problems"]["database"]
    assert problem.startswith("Neo4j was not paused. 1 of 4 backup hooks failed")
    assert "`velero backup logs styrmin-backup-1 -n styrmin`" in problem
    assert run.payload["status"]["failureReason"] == (
        f"Velero backup phase: PartiallyFailed (1 errors); component database: {problem}"
    )


async def test_failed_hooks_without_a_component_meaning_are_reported_on_the_backup() -> (
    None
):
    run = await _run_flow(
        phase="PartiallyFailed",
        hook_status={"hooksAttempted": 2, "hooksFailed": 1},
    )

    assert run.payload["problems"] == {}
    assert run.payload["status"]["failureReason"] == (
        "Velero backup phase: PartiallyFailed (1 errors); 1 of 2 backup hooks failed; "
        "`velero backup logs styrmin-backup-1 -n styrmin` prints their output"
    )


async def test_unreadable_size_warns_and_still_reports_the_completed_backup() -> None:
    run = await _run_flow(
        phase="Completed", pod_volume_backups=VeleroClientError("403 Forbidden")
    )

    assert run.payload["volume_bytes"] is None
    assert run.payload["status"]["phase"] == "Completed"
    run.logger.warning.assert_called_once()
    assert "403 Forbidden" in run.logger.warning.call_args.args[0]
