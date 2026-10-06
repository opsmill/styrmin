"""Polling Velero backups and restores, and listing PodVolumeBackups (spec 019, research D13)."""

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from styrmin_backend.agent.service.kubernetes.velero.client import (
    VeleroClient,
    VeleroClientError,
    failure_message,
)

TERMINAL_PHASES = ["Completed", "PartiallyFailed", "Failed", "FailedValidation"]


def _velero_object(phase: str, **status: Any) -> dict[str, Any]:
    return {"metadata": {"name": "styrmin-1"}, "status": {"phase": phase, **status}}


def _client(*responses: dict[str, Any]) -> tuple[VeleroClient, MagicMock]:
    """A client whose API returns ``responses`` to successive gets."""
    client = VeleroClient(api_client=MagicMock())
    custom_api = MagicMock()
    custom_api.get_namespaced_custom_object = AsyncMock(side_effect=list(responses))
    custom_api.list_namespaced_custom_object = AsyncMock(return_value={"items": []})
    client.custom_api = custom_api
    return client, custom_api


@pytest.mark.parametrize("phase", TERMINAL_PHASES)
async def test_backup_poll_ends_on_a_terminal_phase(phase: str) -> None:
    client, custom_api = _client(_velero_object("InProgress"), _velero_object(phase))

    backup = await client.poll_backup_status("styrmin-1", "styrmin", interval=0)

    assert backup["status"]["phase"] == phase
    assert custom_api.get_namespaced_custom_object.await_count == 2


@pytest.mark.parametrize("phase", TERMINAL_PHASES)
async def test_restore_poll_ends_on_a_terminal_phase(phase: str) -> None:
    client, custom_api = _client(_velero_object("New"), _velero_object(phase))

    restore = await client.poll_restore_status("styrmin-1", "styrmin", interval=0)

    assert restore["status"]["phase"] == phase
    assert custom_api.get_namespaced_custom_object.await_count == 2


async def test_failed_validation_restore_is_returned_with_its_errors() -> None:
    errors = ['Error retrieving backup: backups.velero.io "styrmin-1" not found']
    client, _ = _client(_velero_object("FailedValidation", validationErrors=errors))

    restore = await client.poll_restore_status("styrmin-1", "styrmin", interval=0)

    assert restore["status"]["validationErrors"] == errors


async def test_on_poll_receives_the_backup_after_each_poll() -> None:
    polled = [
        _velero_object("New"),
        _velero_object("InProgress"),
        _velero_object("Completed"),
    ]
    client, _ = _client(*polled)
    on_poll = AsyncMock()

    backup = await client.poll_backup_status(
        "styrmin-1", "styrmin", interval=0, on_poll=on_poll
    )

    assert [call.args[0] for call in on_poll.await_args_list] == polled
    assert backup is polled[-1]


async def test_backup_poll_without_on_poll_still_times_out() -> None:
    client, _ = _client()

    with pytest.raises(VeleroClientError, match="timed out"):
        await client.poll_backup_status("styrmin-1", "styrmin", timeout=0)


async def test_list_pod_volume_backups_filters_by_backup_name() -> None:
    client, custom_api = _client()
    items = [{"metadata": {"name": "pvb-1"}}, {"metadata": {"name": "pvb-2"}}]
    custom_api.list_namespaced_custom_object.return_value = {"items": items}

    listed = await client.list_pod_volume_backups("styrmin", "styrmin-backup-1")

    assert listed == items
    custom_api.list_namespaced_custom_object.assert_awaited_once_with(
        group="velero.io",
        version="v1",
        namespace="styrmin",
        plural="podvolumebackups",
        label_selector="velero.io/backup-name=styrmin-backup-1",
    )


async def test_list_pod_volume_backups_uses_veleros_label_for_a_long_name() -> None:
    """Velero cuts a label value over 63 characters and appends part of its hash."""
    client, custom_api = _client()
    name = "styrmin-" + "x" * 70

    await client.list_pod_volume_backups("styrmin", name)

    digest = hashlib.sha256(name.encode()).hexdigest()
    selector = custom_api.list_namespaced_custom_object.await_args.kwargs[
        "label_selector"
    ]
    assert selector == f"velero.io/backup-name={name[:57]}{digest[:6]}"


async def test_list_pod_volume_backups_raises_a_velero_client_error() -> None:
    client, custom_api = _client()
    custom_api.list_namespaced_custom_object.side_effect = RuntimeError("forbidden")

    with pytest.raises(VeleroClientError, match="forbidden"):
        await client.list_pod_volume_backups("styrmin", "styrmin-backup-1")


@pytest.mark.parametrize(
    ("status", "message"),
    [
        pytest.param(
            {"phase": "FailedValidation", "validationErrors": ["a", "b"]},
            "Velero restore failed validation: a; b",
            id="validation-errors",
        ),
        pytest.param(
            {"phase": "Failed", "failureReason": "found a backup with status Failed"},
            "found a backup with status Failed",
            id="failure-reason",
        ),
        pytest.param(
            {"phase": "PartiallyFailed", "failureReason": "", "errors": 2},
            "Velero restore phase: PartiallyFailed (2 errors)",
            id="partially-failed",
        ),
        pytest.param(
            {"phase": "Failed"}, "Velero restore phase: Failed", id="phase-only"
        ),
    ],
)
def test_failure_message_names_veleros_reason(
    status: dict[str, Any], message: str
) -> None:
    assert failure_message("restore", status) == message
