"""Unit tests for ``pod_volume_bytes``, the byte count behind ``Backup.size_bytes`` (#136)."""

from __future__ import annotations

from typing import Any

import pytest

from styrmin_backend.agent.service.kubernetes.velero.client import pod_volume_bytes


def _pod_volume_backup(phase: str, total_bytes: int | None) -> dict[str, Any]:
    progress = {} if total_bytes is None else {"totalBytes": total_bytes}
    return {"status": {"phase": phase, "progress": progress}}


def test_sums_total_bytes_of_completed_pod_volume_backups() -> None:
    items = [
        _pod_volume_backup("Completed", 1_000),
        _pod_volume_backup("Completed", 24),
        _pod_volume_backup("Failed", 5_000),
    ]

    assert pod_volume_bytes(items) == 1_024


def test_completed_empty_volume_counts_as_zero_bytes() -> None:
    assert pod_volume_bytes([_pod_volume_backup("Completed", None)]) == 0


@pytest.mark.parametrize(
    "items",
    [
        pytest.param([], id="no-pod-volume-backups"),
        pytest.param([_pod_volume_backup("Failed", 10)], id="none-completed"),
        pytest.param([{}], id="no-status"),
    ],
)
def test_no_completed_pod_volume_backup_returns_none(
    items: list[dict[str, Any]],
) -> None:
    assert pod_volume_bytes(items) is None
