"""Tests for the pod status service."""

from uuid import uuid4

import pytest

from styrmin_backend.services.pod_status import get_pod_statuses, report_pod_statuses
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeClusterRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakePodStatusRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


def _make_uow(
    pod_statuses: FakePodStatusRepository | None = None,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        pod_statuses=pod_statuses or FakePodStatusRepository(),
    )


def _make_report(deployment_id, pods):
    return [{"deployment_id": deployment_id, "pods": pods}]


@pytest.mark.anyio
async def test_upsert_creates_new_records() -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    pods = [
        {
            "pod_name": "app-pod-1",
            "namespace": f"styrmin-{deployment_id}",
            "phase": "running",
            "ready": True,
            "restart_count": 0,
        },
        {
            "pod_name": "app-pod-2",
            "namespace": f"styrmin-{deployment_id}",
            "phase": "running",
            "ready": True,
            "restart_count": 1,
        },
    ]

    updated, removed = await report_pod_statuses(_make_report(deployment_id, pods), uow)

    assert updated == 2
    assert removed == 0
    assert len(uow.pod_statuses.models) == 2


@pytest.mark.anyio
async def test_upsert_updates_existing_records() -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    namespace = f"styrmin-{deployment_id}"

    # First report
    pods_v1 = [
        {
            "pod_name": "app-pod-1",
            "namespace": namespace,
            "phase": "pending",
            "ready": False,
            "restart_count": 0,
        },
    ]
    await report_pod_statuses(_make_report(deployment_id, pods_v1), uow)

    # Second report with updated status
    pods_v2 = [
        {
            "pod_name": "app-pod-1",
            "namespace": namespace,
            "phase": "running",
            "ready": True,
            "restart_count": 0,
        },
    ]
    updated, removed = await report_pod_statuses(
        _make_report(deployment_id, pods_v2), uow
    )

    assert updated == 1
    assert removed == 0
    assert len(uow.pod_statuses.models) == 1
    assert uow.pod_statuses.models[0].phase.value == "running"
    assert uow.pod_statuses.models[0].ready is True


@pytest.mark.anyio
async def test_upsert_removes_stale_pods() -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    namespace = f"styrmin-{deployment_id}"

    # First report with 2 pods
    pods_v1 = [
        {
            "pod_name": "app-pod-1",
            "namespace": namespace,
            "phase": "running",
            "ready": True,
            "restart_count": 0,
        },
        {
            "pod_name": "app-pod-2",
            "namespace": namespace,
            "phase": "running",
            "ready": True,
            "restart_count": 0,
        },
    ]
    await report_pod_statuses(_make_report(deployment_id, pods_v1), uow)

    # Second report with only 1 pod (pod-2 was removed)
    pods_v2 = [
        {
            "pod_name": "app-pod-1",
            "namespace": namespace,
            "phase": "running",
            "ready": True,
            "restart_count": 0,
        },
    ]
    updated, removed = await report_pod_statuses(
        _make_report(deployment_id, pods_v2), uow
    )

    assert updated == 1
    assert removed == 1
    assert len(uow.pod_statuses.models) == 1
    assert uow.pod_statuses.models[0].pod_name == "app-pod-1"


@pytest.mark.anyio
async def test_upsert_empty_list_clears_all() -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    namespace = f"styrmin-{deployment_id}"

    # First report with pods
    pods_v1 = [
        {
            "pod_name": "app-pod-1",
            "namespace": namespace,
            "phase": "running",
            "ready": True,
            "restart_count": 0,
        },
    ]
    await report_pod_statuses(_make_report(deployment_id, pods_v1), uow)

    # Second report with empty list
    updated, removed = await report_pod_statuses(_make_report(deployment_id, []), uow)

    assert updated == 0
    assert removed == 1
    assert len(uow.pod_statuses.models) == 0


@pytest.mark.anyio
async def test_batch_report_multiple_deployments() -> None:
    """Multiple deployments in a single batch are handled atomically."""
    uow = _make_uow()
    dep_a = uuid4()
    dep_b = uuid4()

    reports = [
        {
            "deployment_id": dep_a,
            "pods": [
                {
                    "pod_name": "a-pod-1",
                    "namespace": f"styrmin-{dep_a}",
                    "phase": "running",
                    "ready": True,
                    "restart_count": 0,
                },
            ],
        },
        {
            "deployment_id": dep_b,
            "pods": [
                {
                    "pod_name": "b-pod-1",
                    "namespace": f"styrmin-{dep_b}",
                    "phase": "pending",
                    "ready": False,
                    "restart_count": 0,
                },
            ],
        },
    ]

    updated, removed = await report_pod_statuses(reports, uow)

    assert updated == 2
    assert removed == 0
    assert len(uow.pod_statuses.models) == 2
    assert uow.committed is True


@pytest.mark.anyio
async def test_unknown_phase_maps_to_unknown() -> None:
    """An unrecognized phase string is mapped to UNKNOWN."""
    uow = _make_uow()
    deployment_id = uuid4()
    pods = [
        {
            "pod_name": "weird-pod",
            "namespace": f"styrmin-{deployment_id}",
            "phase": "exploded",
            "ready": False,
            "restart_count": 0,
        },
    ]

    updated, _ = await report_pod_statuses(_make_report(deployment_id, pods), uow)

    assert updated == 1
    assert uow.pod_statuses.models[0].phase.value == "unknown"


@pytest.mark.anyio
async def test_cross_deployment_isolation() -> None:
    """Upserting pods for deployment A does not affect deployment B."""
    uow = _make_uow()
    dep_a = uuid4()
    dep_b = uuid4()

    # Report pods for both deployments
    await report_pod_statuses(
        [
            {
                "deployment_id": dep_a,
                "pods": [
                    {
                        "pod_name": "shared-name",
                        "namespace": f"styrmin-{dep_a}",
                        "phase": "running",
                        "ready": True,
                        "restart_count": 0,
                    },
                ],
            },
            {
                "deployment_id": dep_b,
                "pods": [
                    {
                        "pod_name": "shared-name",
                        "namespace": f"styrmin-{dep_b}",
                        "phase": "pending",
                        "ready": False,
                        "restart_count": 0,
                    },
                ],
            },
        ],
        uow,
    )

    assert len(uow.pod_statuses.models) == 2

    # Clear deployment A's pods — deployment B should be unaffected
    await report_pod_statuses(_make_report(dep_a, []), uow)

    assert len(uow.pod_statuses.models) == 1
    assert uow.pod_statuses.models[0].deployment_id == dep_b


@pytest.mark.anyio
async def test_get_pod_statuses_by_deployment() -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    namespace = f"styrmin-{deployment_id}"

    pods = [
        {
            "pod_name": "app-pod-1",
            "namespace": namespace,
            "phase": "running",
            "ready": True,
            "restart_count": 0,
        },
    ]
    await report_pod_statuses(_make_report(deployment_id, pods), uow)

    result = await get_pod_statuses(uow, deployment_id=deployment_id)
    assert len(result) == 1
    assert result[0].pod_name == "app-pod-1"


@pytest.mark.anyio
async def test_get_pod_statuses_no_filter_returns_all() -> None:
    uow = _make_uow()
    dep_a = uuid4()
    dep_b = uuid4()

    await report_pod_statuses(
        [
            {
                "deployment_id": dep_a,
                "pods": [
                    {
                        "pod_name": "a-pod",
                        "namespace": f"styrmin-{dep_a}",
                        "phase": "running",
                        "ready": True,
                        "restart_count": 0,
                    },
                ],
            },
            {
                "deployment_id": dep_b,
                "pods": [
                    {
                        "pod_name": "b-pod",
                        "namespace": f"styrmin-{dep_b}",
                        "phase": "pending",
                        "ready": False,
                        "restart_count": 0,
                    },
                ],
            },
        ],
        uow,
    )

    result = await get_pod_statuses(uow)
    assert len(result) == 2
    pod_names = {p.pod_name for p in result}
    assert pod_names == {"a-pod", "b-pod"}


@pytest.mark.anyio
async def test_get_pod_statuses_no_filter_empty_db() -> None:
    uow = _make_uow()
    result = await get_pod_statuses(uow)
    assert result == []
