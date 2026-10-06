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
) -> FlowRun:
    velero_backup = {
        "metadata": {"name": "styrmin-backup-1"},
        "status": {
            "phase": phase,
            "backupItemOperationsCompleted": 7,
            "expiration": "2026-11-05T10:00:00Z",
        },
    }
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
    variable = MagicMock()
    variable.set = AsyncMock()
    logger = MagicMock()

    with (
        patch("kubernetes_asyncio.client.ApiClient", return_value=api_client),
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
    run = await _run_flow(phase=phase)

    assert run.payload["volume_bytes"] is None
    run.velero_client.list_pod_volume_backups.assert_not_awaited()


async def test_unreadable_size_warns_and_still_reports_the_completed_backup() -> None:
    run = await _run_flow(
        phase="Completed", pod_volume_backups=VeleroClientError("403 Forbidden")
    )

    assert run.payload["volume_bytes"] is None
    assert run.payload["status"]["phase"] == "Completed"
    run.logger.warning.assert_called_once()
    assert "403 Forbidden" in run.logger.warning.call_args.args[0]
