"""Unit tests for the operator reconciler logic."""

from unittest.mock import AsyncMock, patch

import pytest
from styrmin_backend.operator.reconciler import compute_diff, reconcile_resources


class TestComputeDiff:
    def test_no_diff_when_identical(self) -> None:
        desired = [
            {"kind": "NetworkPolicy", "metadata": {"name": "np-1", "namespace": "ns"}, "spec": {"podSelector": {}}}
        ]
        actual = [
            {"kind": "NetworkPolicy", "metadata": {"name": "np-1", "namespace": "ns"}, "spec": {"podSelector": {}}}
        ]
        to_create, to_update, to_delete = compute_diff(desired, actual)
        assert to_create == []
        assert to_update == []
        assert to_delete == []

    def test_creates_missing_resources(self) -> None:
        desired = [
            {"kind": "NetworkPolicy", "metadata": {"name": "np-1", "namespace": "ns"}, "spec": {"podSelector": {}}}
        ]
        actual: list[dict] = []
        to_create, _to_update, _to_delete = compute_diff(desired, actual)
        assert len(to_create) == 1
        assert to_create[0]["metadata"]["name"] == "np-1"

    def test_updates_modified_resources(self) -> None:
        desired = [
            {
                "kind": "NetworkPolicy",
                "metadata": {"name": "np-1", "namespace": "ns"},
                "spec": {"podSelector": {"matchLabels": {"app": "new"}}},
            }
        ]
        actual = [
            {
                "kind": "NetworkPolicy",
                "metadata": {"name": "np-1", "namespace": "ns"},
                "spec": {"podSelector": {"matchLabels": {"app": "old"}}},
            }
        ]
        to_create, to_update, to_delete = compute_diff(desired, actual)
        assert to_create == []
        assert len(to_update) == 1
        assert to_delete == []

    def test_deletes_extra_resources(self) -> None:
        desired: list[dict] = []
        actual = [{"kind": "NetworkPolicy", "metadata": {"name": "np-1", "namespace": "ns"}, "spec": {}}]
        to_create, to_update, to_delete = compute_diff(desired, actual)
        assert to_create == []
        assert to_update == []
        assert len(to_delete) == 1

    def test_idempotent_on_no_changes(self) -> None:
        desired = [
            {"kind": "NetworkPolicy", "metadata": {"name": "np-1", "namespace": "ns"}, "spec": {"a": 1}},
            {"kind": "Service", "metadata": {"name": "svc-1", "namespace": "ns"}, "spec": {"ports": [80]}},
        ]
        actual = list(desired)
        to_create, to_update, to_delete = compute_diff(desired, actual)
        assert to_create == []
        assert to_update == []
        assert to_delete == []


class TestReconcileResources:
    @pytest.mark.anyio
    async def test_applies_creates_and_updates(self) -> None:
        to_create = [{"kind": "NetworkPolicy", "metadata": {"name": "np-1", "namespace": "ns"}, "spec": {}}]
        to_update = [{"kind": "Service", "metadata": {"name": "svc-1", "namespace": "ns"}, "spec": {}}]
        to_delete = [{"kind": "Secret", "metadata": {"name": "sec-1", "namespace": "ns"}}]

        with (
            patch(
                "styrmin_backend.operator.reconciler.apply_kubernetes_resource",
                new_callable=AsyncMock,
            ) as mock_apply,
            patch(
                "styrmin_backend.operator.reconciler.delete_kubernetes_resource",
                new_callable=AsyncMock,
            ) as mock_delete,
        ):
            result = await reconcile_resources(
                namespace="ns",
                to_create=to_create,
                to_update=to_update,
                to_delete=to_delete,
            )

        assert mock_apply.call_count == 2  # 1 create + 1 update
        assert mock_delete.call_count == 1
        assert result.created == 1
        assert result.updated == 1
        assert result.deleted == 1
        assert result.errors == []

    @pytest.mark.anyio
    async def test_captures_errors_without_raising(self) -> None:
        to_create = [{"kind": "NetworkPolicy", "metadata": {"name": "np-1", "namespace": "ns"}, "spec": {}}]

        with (
            patch(
                "styrmin_backend.operator.reconciler.apply_kubernetes_resource",
                new_callable=AsyncMock,
                side_effect=Exception("API error"),
            ),
            patch(
                "styrmin_backend.operator.reconciler.delete_kubernetes_resource",
                new_callable=AsyncMock,
            ),
        ):
            result = await reconcile_resources(
                namespace="ns",
                to_create=to_create,
                to_update=[],
                to_delete=[],
            )

        assert result.created == 0
        assert len(result.errors) == 1
        assert "API error" in result.errors[0]
