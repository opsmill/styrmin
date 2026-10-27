"""Tests for the agent status reporter — models, extraction, communication, resilience."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from styrmin_backend.agent.status.models import (
    DeploymentStatusReport,
    DeploymentPodStatusReport,
    PodPhase,
    PodStatusData,
    ReportDeploymentStatusesResponse,
    ReportPodStatusesResponse,
)
from styrmin_backend.agent.status.reporter import (
    _collect_crd_status,
    _extract_pod_data,
    _get_active_deployments,
    _poll_once,
    _report_deployment_statuses_to_backend,
    _report_pod_statuses_to_backend,
    run_status_reporter,
)
from tests.helpers.pods import load_pod

GRAPHQL_URL = "http://test:8000/graphql"
SCHEMA_PATH = Path(__file__).resolve().parents[4] / "schema.graphql"


# ---------------------------------------------------------------------------
# Helpers — fake Kubernetes pod objects
# ---------------------------------------------------------------------------


def _make_container_status(
    name: str = "main",
    ready: bool = True,
    restart_count: int = 0,
    state: str = "running",
    reason: str | None = None,
    started_at: str | None = "2026-01-01T00:00:00",
    message: str | None = None,
) -> SimpleNamespace:
    running = None
    waiting = None
    terminated = None

    if state == "running":
        running = SimpleNamespace(
            started_at=SimpleNamespace(isoformat=lambda: started_at)
            if started_at
            else None
        )
    elif state == "waiting":
        waiting = SimpleNamespace(reason=reason, message=message)
    elif state == "terminated":
        terminated = SimpleNamespace(reason=reason, message=message)

    return SimpleNamespace(
        name=name,
        ready=ready,
        restart_count=restart_count,
        state=SimpleNamespace(running=running, waiting=waiting, terminated=terminated),
        image="test-image:latest",
    )


def _make_condition(
    type_: str, status: str, reason: str | None = None, message: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(type=type_, status=status, reason=reason, message=message)


def _make_pod(
    name: str = "test-pod",
    namespace: str = "styrmin-test",
    phase: str = "Running",
    container_statuses: list | None = None,
    node_name: str | None = "node-1",
    start_time: str | None = "2026-01-01T00:00:00",
    labels: dict[str, str] | None = None,
    init_container_statuses: list | None = None,
    conditions: list | None = None,
    sidecars: tuple[str, ...] = (),
) -> SimpleNamespace:
    init_containers = [
        SimpleNamespace(
            name=cs.name, restart_policy="Always" if cs.name in sidecars else None
        )
        for cs in init_container_statuses or ()
    ]
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, namespace=namespace, labels=labels),
        status=SimpleNamespace(
            phase=phase,
            container_statuses=container_statuses,
            init_container_statuses=init_container_statuses,
            conditions=conditions,
            start_time=SimpleNamespace(isoformat=lambda: start_time)
            if start_time
            else None,
        ),
        spec=SimpleNamespace(node_name=node_name, init_containers=init_containers)
        if node_name
        else None,
    )


# ---------------------------------------------------------------------------
# A. Model validation tests (bindings contract)
# ---------------------------------------------------------------------------


class TestModelContract:
    def test_pod_phase_enum_matches_graphql_schema(self) -> None:
        schema_text = SCHEMA_PATH.read_text()
        match = re.search(r"enum PodPhase \{([^}]+)\}", schema_text, re.MULTILINE)
        assert match, "PodPhase enum not found in schema.graphql"
        schema_values = set(match.group(1).split())
        model_values = {p.value for p in PodPhase}
        assert model_values == schema_values

    def test_pod_status_data_validates_valid_input(self) -> None:
        data = PodStatusData(
            podName="app-1",
            namespace="styrmin-test",
            phase=PodPhase.RUNNING,
            ready=True,
            restartCount=0,
        )
        assert data.pod_name == "app-1"
        assert data.phase == PodPhase.RUNNING

    def test_pod_status_data_rejects_invalid_phase(self) -> None:
        with pytest.raises(ValidationError, match="phase"):
            PodStatusData(
                podName="app-1",
                namespace="styrmin-test",
                phase="running",  # type: ignore[arg-type]
                ready=True,
                restartCount=0,
            )

    def test_pod_status_report_serializes_to_graphql_format(self) -> None:
        report = DeploymentPodStatusReport(
            deploymentId="abc-123",
            pods=[
                PodStatusData(
                    podName="pod-1",
                    namespace="ns",
                    phase=PodPhase.RUNNING,
                    ready=True,
                    restartCount=2,
                    nodeName="node-1",
                )
            ],
        )
        dumped = report.model_dump(by_alias=True)
        assert dumped["deploymentId"] == "abc-123"
        pod = dumped["pods"][0]
        assert pod["podName"] == "pod-1"
        assert pod["phase"] == "RUNNING"
        assert pod["restartCount"] == 2
        assert pod["nodeName"] == "node-1"

    def test_crd_status_report_serializes_correctly(self) -> None:
        report = DeploymentStatusReport(
            deploymentId="abc",
            instanceId="11111111-2222-3333-4444-555555555555",
            phase="Ready",
            message="All good",
        )
        dumped = report.model_dump(by_alias=True)
        assert dumped["deploymentId"] == "abc"
        assert dumped["instanceId"] == "11111111-2222-3333-4444-555555555555"
        assert dumped["phase"] == "Ready"
        assert dumped["managedResourceCounts"] is None

    def test_report_pod_statuses_response_parses(self) -> None:
        resp = ReportPodStatusesResponse.model_validate(
            {"success": True, "message": "ok", "podsUpdated": 3, "podsRemoved": 1}
        )
        assert resp.pods_updated == 3
        assert resp.pods_removed == 1

    def test_report_deployment_statuses_response_parses(self) -> None:
        resp = ReportDeploymentStatusesResponse.model_validate(
            {
                "success": True,
                "message": "ok",
                "statusesUpdated": 2,
                "deploymentsUpdated": 1,
            }
        )
        assert resp.statuses_updated == 2


# ---------------------------------------------------------------------------
# B. _extract_pod_data tests
# ---------------------------------------------------------------------------


class TestExtractPodData:
    def test_running_pod(self) -> None:
        pod = _make_pod(
            container_statuses=[_make_container_status()],
        )
        result = _extract_pod_data(pod)
        assert isinstance(result, PodStatusData)
        assert result.phase == PodPhase.RUNNING
        assert result.ready is True
        assert result.restart_count == 0

    def test_pending_pod_no_containers(self) -> None:
        pod = _make_pod(phase="Pending", container_statuses=None, start_time=None)
        result = _extract_pod_data(pod)
        assert result.phase == PodPhase.PENDING
        assert result.ready is False
        assert result.started_at is None

    def test_pod_with_waiting_container(self) -> None:
        pod = _make_pod(
            container_statuses=[
                _make_container_status(
                    ready=False,
                    state="waiting",
                    reason="CrashLoopBackOff",
                )
            ],
        )
        result = _extract_pod_data(pod)
        assert result.ready is False
        dumped = result.model_dump(by_alias=True)
        assert dumped["containerStatuses"][0]["state"] == "waiting:CrashLoopBackOff"

    def test_pod_with_terminated_container(self) -> None:
        pod = _make_pod(
            phase="Failed",
            container_statuses=[
                _make_container_status(
                    ready=False,
                    state="terminated",
                    reason="OOMKilled",
                )
            ],
        )
        result = _extract_pod_data(pod)
        assert result.phase == PodPhase.FAILED
        dumped = result.model_dump(by_alias=True)
        assert dumped["containerStatuses"][0]["state"] == "terminated:OOMKilled"

    def test_pod_missing_optional_fields(self) -> None:
        pod = _make_pod(node_name=None, start_time=None, container_statuses=[])
        result = _extract_pod_data(pod)
        assert result.node_name is None
        assert result.started_at is None

    def test_extract_pod_data_reads_component_label(self) -> None:
        pod = _make_pod(labels={"styrmin/component": "api"})
        result = _extract_pod_data(pod)
        assert result.component_name == "api"

    def test_pod_status_data_serializes_component_name(self) -> None:
        data = PodStatusData(
            podName="p",
            namespace="ns",
            phase=PodPhase.RUNNING,
            ready=True,
            restartCount=0,
            componentName="worker",
        )
        dumped = data.model_dump(by_alias=True)
        assert dumped["componentName"] == "worker"

    def test_extract_pod_data_returns_none_when_label_missing(self) -> None:
        # All three "label is absent" shapes Kubernetes can return.
        for labels in (None, {}, {"unrelated": "value"}):
            pod = _make_pod(labels=labels)
            result = _extract_pod_data(pod)
            assert result.component_name is None, f"failed for labels={labels}"

    def test_extract_pod_data_normalizes_blank_label_to_none(self) -> None:
        for blank in ("", "   ", "\t\n"):
            pod = _make_pod(labels={"styrmin/component": blank})
            result = _extract_pod_data(pod)
            assert result.component_name is None, f"failed for {blank!r}"

    def test_extract_pod_data_passes_through_unknown_label_value(self) -> None:
        # The agent does NOT validate against declared components — observed
        # state is reported as-is, drift is recorded honestly.
        pod = _make_pod(labels={"styrmin/component": "ghost"})
        result = _extract_pod_data(pod)
        assert result.component_name == "ghost"


class TestExtractPodDataFailureCauses:
    """#574: the stored pod status keeps what explains why a pod is not ready."""

    def test_unscheduled_pod_has_a_pod_entry_with_the_scheduler_message(self) -> None:
        message = "0/2 nodes are available: pod has unbound immediate PersistentVolumeClaims. not found"
        pod = _make_pod(
            phase="Pending",
            container_statuses=None,
            node_name=None,
            start_time=None,
            conditions=[
                _make_condition("PodScheduled", "False", "Unschedulable", message)
            ],
        )

        result = _extract_pod_data(pod)

        assert result.ready is False
        assert result.restart_count == 0
        assert result.container_statuses == [
            {
                "name": "PodScheduled",
                "kind": "pod",
                "ready": False,
                "state": "waiting:Unschedulable",
                "message": message,
                "restart_count": 0,
                "image": "",
                "started_at": None,
            }
        ]

    def test_scheduled_pod_has_no_pod_entry(self) -> None:
        pod = _make_pod(
            container_statuses=[_make_container_status()],
            conditions=[_make_condition("PodScheduled", "True")],
        )

        result = _extract_pod_data(pod)

        assert [entry["kind"] for entry in result.container_statuses or ()] == [
            "container"
        ]

    def test_failing_init_container_is_reported_with_its_restarts(self) -> None:
        # The Semaphore pod of the issue: its init container `admin` fails and restarts,
        # while the container waits with PodInitializing.
        pod = _make_pod(
            phase="Pending",
            init_container_statuses=[
                _make_container_status(
                    name="admin",
                    ready=False,
                    restart_count=5,
                    state="waiting",
                    reason="CrashLoopBackOff",
                    message="back-off 2m40s restarting failed container=admin",
                )
            ],
            container_statuses=[
                _make_container_status(
                    name="semaphore",
                    ready=False,
                    state="waiting",
                    reason="PodInitializing",
                )
            ],
            conditions=[
                _make_condition("PodScheduled", "True"),
                _make_condition("Initialized", "False", "ContainersNotInitialized"),
            ],
        )

        result = _extract_pod_data(pod)

        entries = result.container_statuses or []
        assert [(e["name"], e["kind"], e["state"]) for e in entries] == [
            ("admin", "init", "waiting:CrashLoopBackOff"),
            ("semaphore", "container", "waiting:PodInitializing"),
        ]
        assert entries[0]["restart_count"] == 5
        assert entries[0]["message"] == (
            "back-off 2m40s restarting failed container=admin"
        )
        # kubectl counts the init container restarts while the pod initializes.
        assert result.restart_count == 5
        assert result.ready is False

    def test_initialized_pod_counts_container_and_sidecar_restarts(self) -> None:
        pod = _make_pod(
            init_container_statuses=[
                _make_container_status(
                    name="migrate",
                    ready=False,
                    restart_count=2,
                    state="terminated",
                    reason="Completed",
                ),
                _make_container_status(name="proxy", restart_count=3),
            ],
            container_statuses=[_make_container_status(name="app", restart_count=1)],
            conditions=[_make_condition("Initialized", "True")],
            sidecars=("proxy",),
        )

        result = _extract_pod_data(pod)

        assert result.restart_count == 4
        assert result.ready is True

    def test_waiting_message_is_kept(self) -> None:
        message = 'failed to pull image "traefik/whoami:v1.99.99": not found'
        pod = _make_pod(
            phase="Pending",
            container_statuses=[
                _make_container_status(
                    name="app",
                    ready=False,
                    state="waiting",
                    reason="ErrImagePull",
                    message=message,
                )
            ],
        )

        entry = (_extract_pod_data(pod).container_statuses or [])[0]

        assert entry["state"] == "waiting:ErrImagePull"
        assert entry["message"] == message

    def test_post_start_hook_message_is_not_kept(self) -> None:
        # The kubelet quotes the output of the hook command in this message.
        pod = _make_pod(
            container_statuses=[
                _make_container_status(
                    ready=False,
                    state="waiting",
                    reason="PostStartHookError",
                    message=(
                        "Exec lifecycle hook ([sh -c ./register.sh]) for Container "
                        '"app" in Pod "app-0" failed - error: command exited with 1, '
                        'message: "token=s3cr3t rejected"'
                    ),
                )
            ],
        )

        entry = (_extract_pod_data(pod).container_statuses or [])[0]

        assert entry["state"] == "waiting:PostStartHookError"
        assert entry["message"] is None

    def test_terminated_message_is_not_kept(self) -> None:
        # The container writes this message, so it can hold anything it printed.
        pod = _make_pod(
            container_statuses=[
                _make_container_status(
                    ready=False,
                    state="terminated",
                    reason="Error",
                    message="password=hunter2",
                )
            ],
        )

        entry = (_extract_pod_data(pod).container_statuses or [])[0]

        assert entry["state"] == "terminated:Error"
        assert entry["message"] is None


class TestExtractPodDataFromKind:
    """The reporter on pods that a kind cluster returned for failed deployments (#574)."""

    @pytest.mark.anyio
    async def test_pod_not_scheduled(self) -> None:
        result = _extract_pod_data(await load_pod("pod_not_scheduled"))

        assert (result.phase, result.ready, result.restart_count) == (
            PodPhase.PENDING,
            False,
            0,
        )
        assert result.node_name is None
        assert [
            (e["name"], e["kind"], e["state"], e["message"])
            for e in result.container_statuses or ()
        ] == [
            (
                "PodScheduled",
                "pod",
                "waiting:Unschedulable",
                "0/2 nodes are available: pod has unbound immediate "
                "PersistentVolumeClaims. not found",
            )
        ]

    @pytest.mark.anyio
    async def test_pod_with_failing_init_container(self) -> None:
        result = _extract_pod_data(await load_pod("pod_init_container_failing"))

        assert (result.phase, result.ready, result.restart_count) == (
            PodPhase.PENDING,
            False,
            7,
        )
        assert [
            (e["name"], e["kind"], e["state"], e["restart_count"])
            for e in result.container_statuses or ()
        ] == [
            ("admin", "init", "running", 7),
            ("semaphore", "container", "waiting:PodInitializing", 0),
        ]

    @pytest.mark.anyio
    async def test_pod_with_image_that_cannot_be_pulled(self) -> None:
        result = _extract_pod_data(await load_pod("pod_image_pull_failing"))

        [entry] = result.container_statuses or []
        assert (entry["kind"], entry["state"]) == (
            "container",
            "waiting:ImagePullBackOff",
        )
        assert entry["message"].endswith("docker.io/traefik/whoami:v1.99.99: not found")


# ---------------------------------------------------------------------------
# C. Backend communication tests (mock httpx)
# ---------------------------------------------------------------------------


def _mock_response(json_data: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("POST", GRAPHQL_URL),
    )


class TestReportPodStatuses:
    @pytest.mark.anyio
    async def test_success(self) -> None:
        report = DeploymentPodStatusReport(
            deploymentId=str(uuid4()),
            pods=[
                PodStatusData(
                    podName="p1",
                    namespace="ns",
                    phase=PodPhase.RUNNING,
                    ready=True,
                    restartCount=0,
                )
            ],
        )
        mock_resp = _mock_response(
            {
                "data": {
                    "reportPodStatuses": {
                        "success": True,
                        "message": "ok",
                        "podsUpdated": 1,
                        "podsRemoved": 0,
                    }
                }
            }
        )
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            mock.return_value.__aenter__ = AsyncMock(return_value=mock.return_value)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            mock.return_value.post = AsyncMock(return_value=mock_resp)
            await _report_pod_statuses_to_backend(GRAPHQL_URL, [report])

    @pytest.mark.anyio
    async def test_graphql_errors_does_not_crash(self) -> None:
        report = DeploymentPodStatusReport(
            deploymentId=str(uuid4()),
            pods=[
                PodStatusData(
                    podName="p1",
                    namespace="ns",
                    phase=PodPhase.RUNNING,
                    ready=True,
                    restartCount=0,
                )
            ],
        )
        mock_resp = _mock_response({"data": None, "errors": [{"message": "bad input"}]})
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            mock.return_value.__aenter__ = AsyncMock(return_value=mock.return_value)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            mock.return_value.post = AsyncMock(return_value=mock_resp)
            await _report_pod_statuses_to_backend(GRAPHQL_URL, [report])

    @pytest.mark.anyio
    async def test_backend_unavailable_does_not_crash(self) -> None:
        report = DeploymentPodStatusReport(
            deploymentId=str(uuid4()),
            pods=[
                PodStatusData(
                    podName="p1",
                    namespace="ns",
                    phase=PodPhase.RUNNING,
                    ready=True,
                    restartCount=0,
                )
            ],
        )
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            mock.return_value.__aenter__ = AsyncMock(return_value=mock.return_value)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            mock.return_value.post = AsyncMock(
                side_effect=httpx.ConnectError("refused")
            )
            await _report_pod_statuses_to_backend(GRAPHQL_URL, [report])

    @pytest.mark.anyio
    async def test_http_500_does_not_crash(self) -> None:
        report = DeploymentPodStatusReport(
            deploymentId=str(uuid4()),
            pods=[
                PodStatusData(
                    podName="p1",
                    namespace="ns",
                    phase=PodPhase.RUNNING,
                    ready=True,
                    restartCount=0,
                )
            ],
        )
        mock_resp = _mock_response({"error": "internal"}, status_code=500)
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            mock.return_value.__aenter__ = AsyncMock(return_value=mock.return_value)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            mock.return_value.post = AsyncMock(return_value=mock_resp)
            await _report_pod_statuses_to_backend(GRAPHQL_URL, [report])

    @pytest.mark.anyio
    async def test_timeout_does_not_crash(self) -> None:
        report = DeploymentPodStatusReport(
            deploymentId=str(uuid4()),
            pods=[
                PodStatusData(
                    podName="p1",
                    namespace="ns",
                    phase=PodPhase.RUNNING,
                    ready=True,
                    restartCount=0,
                )
            ],
        )
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            mock.return_value.__aenter__ = AsyncMock(return_value=mock.return_value)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            mock.return_value.post = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
            await _report_pod_statuses_to_backend(GRAPHQL_URL, [report])

    @pytest.mark.anyio
    async def test_empty_reports_skips(self) -> None:
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            await _report_pod_statuses_to_backend(GRAPHQL_URL, [])
            mock.assert_not_called()


class TestReportDeploymentStatuses:
    @pytest.mark.anyio
    async def test_success(self) -> None:
        report = DeploymentStatusReport(
            deploymentId=str(uuid4()),
            phase="Ready",
        )
        mock_resp = _mock_response(
            {
                "data": {
                    "reportDeploymentStatuses": {
                        "success": True,
                        "message": "ok",
                        "statusesUpdated": 1,
                        "deploymentsUpdated": 1,
                    }
                }
            }
        )
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            mock.return_value.__aenter__ = AsyncMock(return_value=mock.return_value)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            mock.return_value.post = AsyncMock(return_value=mock_resp)
            await _report_deployment_statuses_to_backend(GRAPHQL_URL, [report])

    @pytest.mark.anyio
    async def test_graphql_errors_does_not_crash(self) -> None:
        report = DeploymentStatusReport(
            deploymentId=str(uuid4()),
            phase="Ready",
        )
        mock_resp = _mock_response({"data": None, "errors": [{"message": "bad input"}]})
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            mock.return_value.__aenter__ = AsyncMock(return_value=mock.return_value)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            mock.return_value.post = AsyncMock(return_value=mock_resp)
            await _report_deployment_statuses_to_backend(GRAPHQL_URL, [report])

    @pytest.mark.anyio
    async def test_backend_unavailable_does_not_crash(self) -> None:
        report = DeploymentStatusReport(
            deploymentId=str(uuid4()),
            phase="Ready",
        )
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            mock.return_value.__aenter__ = AsyncMock(return_value=mock.return_value)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            mock.return_value.post = AsyncMock(
                side_effect=httpx.ConnectError("refused")
            )
            await _report_deployment_statuses_to_backend(GRAPHQL_URL, [report])


class TestGetActiveDeployments:
    @pytest.mark.anyio
    async def test_success(self) -> None:
        dep_id = str(uuid4())
        mock_resp = _mock_response(
            {
                "data": {
                    "environments": [
                        {
                            "deployments": [
                                {
                                    "id": dep_id,
                                    "status": "running",
                                }
                            ]
                        }
                    ]
                }
            }
        )
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            mock.return_value.__aenter__ = AsyncMock(return_value=mock.return_value)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            mock.return_value.post = AsyncMock(return_value=mock_resp)
            results = await _get_active_deployments(GRAPHQL_URL)
        assert len(results) == 1
        assert str(results[0][0]) == dep_id
        assert results[0][1] == "running"

    @pytest.mark.anyio
    async def test_backend_down_returns_empty(self) -> None:
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            mock.return_value.__aenter__ = AsyncMock(return_value=mock.return_value)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            mock.return_value.post = AsyncMock(
                side_effect=httpx.ConnectError("refused")
            )
            results = await _get_active_deployments(GRAPHQL_URL)
        assert results == []

    @pytest.mark.anyio
    async def test_data_null_returns_empty(self) -> None:
        mock_resp = _mock_response(
            {"data": None, "errors": [{"message": "internal error"}]}
        )
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            mock.return_value.__aenter__ = AsyncMock(return_value=mock.return_value)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            mock.return_value.post = AsyncMock(return_value=mock_resp)
            results = await _get_active_deployments(GRAPHQL_URL)
        assert results == []

    @pytest.mark.anyio
    async def test_reports_internal_deployments(self) -> None:
        """The default environment list hides internal deployments, so the
        reporter asks for them: an ingress controller needs its status
        reported, including the tombstone after teardown (#252)."""
        running_id = str(uuid4())
        deleting_id = str(uuid4())
        mock_resp = _mock_response(
            {
                "data": {
                    "environments": [
                        {
                            "deployments": [
                                {"id": running_id, "status": "running"},
                                {"id": deleting_id, "status": "deleting"},
                            ]
                        }
                    ]
                }
            }
        )
        with patch("styrmin_backend.agent.status.reporter.httpx.AsyncClient") as mock:
            mock.return_value.__aenter__ = AsyncMock(return_value=mock.return_value)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            mock.return_value.post = AsyncMock(return_value=mock_resp)
            results = await _get_active_deployments(GRAPHQL_URL)
            sent_query = mock.return_value.post.await_args.kwargs["json"]["query"]
        assert "includeInternal: true" in sent_query
        assert [(str(dep_id), status) for dep_id, status in results] == [
            (running_id, "running"),
            (deleting_id, "deleting"),
        ]


# ---------------------------------------------------------------------------
# D. Poll cycle resilience tests
# ---------------------------------------------------------------------------


class TestPollOnce:
    @pytest.mark.anyio
    async def test_no_deployments(self) -> None:
        with patch(
            "styrmin_backend.agent.status.reporter._get_active_deployments",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await _poll_once(GRAPHQL_URL)

    @pytest.mark.anyio
    async def test_pod_collection_failure_continues(self) -> None:
        dep_id = uuid4()
        with (
            patch(
                "styrmin_backend.agent.status.reporter._get_active_deployments",
                new_callable=AsyncMock,
                return_value=[(dep_id, "running")],
            ),
            patch(
                "styrmin_backend.agent.status.reporter._collect_pod_statuses",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "styrmin_backend.agent.status.reporter._collect_crd_status",
                new_callable=AsyncMock,
                return_value={
                    "phase": "Ready",
                    "displayState": "Running",
                    "message": None,
                    "conditions": None,
                    "managedResourceCounts": None,
                },
            ),
            patch(
                "styrmin_backend.agent.status.reporter._report_pod_statuses_to_backend",
                new_callable=AsyncMock,
            ) as mock_pod_report,
            patch(
                "styrmin_backend.agent.status.reporter._report_deployment_statuses_to_backend",
                new_callable=AsyncMock,
            ) as mock_crd_report,
        ):
            await _poll_once(GRAPHQL_URL)
            # Pod report called with empty list (collection failed)
            mock_pod_report.assert_called_once()
            assert mock_pod_report.call_args[0][1] == []
            # CRD report still called with data
            mock_crd_report.assert_called_once()
            assert len(mock_crd_report.call_args[0][1]) == 1

    @pytest.mark.anyio
    async def test_pod_report_failure_does_not_block_crd_report(self) -> None:
        dep_id = uuid4()
        with (
            patch(
                "styrmin_backend.agent.status.reporter._get_active_deployments",
                new_callable=AsyncMock,
                return_value=[(dep_id, "running")],
            ),
            patch(
                "styrmin_backend.agent.status.reporter._collect_pod_statuses",
                new_callable=AsyncMock,
                return_value=[
                    PodStatusData(
                        podName="p1",
                        namespace="ns",
                        phase=PodPhase.RUNNING,
                        ready=True,
                        restartCount=0,
                    )
                ],
            ),
            patch(
                "styrmin_backend.agent.status.reporter._collect_crd_status",
                new_callable=AsyncMock,
                return_value={
                    "phase": "Ready",
                    "displayState": "Running",
                    "message": None,
                    "conditions": None,
                    "managedResourceCounts": None,
                },
            ),
            patch(
                "styrmin_backend.agent.status.reporter._report_pod_statuses_to_backend",
                new_callable=AsyncMock,
                side_effect=RuntimeError("pod report exploded"),
            ),
            patch(
                "styrmin_backend.agent.status.reporter._report_deployment_statuses_to_backend",
                new_callable=AsyncMock,
            ) as mock_crd_report,
        ):
            await _poll_once(GRAPHQL_URL)
            mock_crd_report.assert_called_once()

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("namespace_read", "expected_phases"),
        [
            # Kubernetes deletes the CR with the namespace's contents, before
            # it removes the namespace itself.
            pytest.param(
                SimpleNamespace(metadata=SimpleNamespace(deletion_timestamp="now")),
                [],
                id="namespace-terminating",
            ),
            pytest.param(None, ["Deleted"], id="namespace-gone"),
            pytest.param(RuntimeError("API down"), [], id="namespace-read-fails"),
            # A create that failed before its CR write leaves a namespace that
            # nothing deletes.
            pytest.param(
                SimpleNamespace(metadata=SimpleNamespace(deletion_timestamp=None)),
                ["Deleted"],
                id="namespace-not-being-deleted",
            ),
        ],
    )
    async def test_deleting_deployment_without_cr_is_deleted_once_namespace_is_gone(
        self, namespace_read: object, expected_phases: list[str]
    ) -> None:
        """FR-003 of spec 008: the deployment is not deleted while its namespace terminates."""
        namespace_mock = (
            AsyncMock(side_effect=namespace_read)
            if isinstance(namespace_read, Exception)
            else AsyncMock(return_value=namespace_read)
        )
        with (
            patch(
                "styrmin_backend.agent.status.reporter._get_active_deployments",
                new_callable=AsyncMock,
                return_value=[(uuid4(), "deleting")],
            ),
            patch(
                "styrmin_backend.agent.status.reporter._collect_pod_statuses",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "styrmin_backend.agent.status.reporter._collect_crd_status",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "styrmin_backend.agent.status.reporter.get_namespace",
                namespace_mock,
            ),
            patch(
                "styrmin_backend.agent.status.reporter._report_pod_statuses_to_backend",
                new_callable=AsyncMock,
            ),
            patch(
                "styrmin_backend.agent.status.reporter._report_deployment_statuses_to_backend",
                new_callable=AsyncMock,
            ) as mock_crd_report,
        ):
            await _poll_once(GRAPHQL_URL)
        reports = mock_crd_report.call_args[0][1]
        assert [report.phase for report in reports] == expected_phases


class TestRunStatusReporter:
    @pytest.mark.anyio
    async def test_keeps_running_after_poll_failure(self) -> None:
        call_count = 0
        shutdown = asyncio.Event()

        async def failing_poll(url: str) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                shutdown.set()
            if call_count <= 2:
                raise RuntimeError("boom")

        with patch(
            "styrmin_backend.agent.status.reporter._poll_once",
            side_effect=failing_poll,
        ):
            await run_status_reporter(shutdown, graphql_url=GRAPHQL_URL, interval=0)

        assert call_count == 3

    @pytest.mark.anyio
    async def test_stops_on_shutdown_event(self) -> None:
        shutdown = asyncio.Event()
        shutdown.set()

        with patch(
            "styrmin_backend.agent.status.reporter._poll_once",
            new_callable=AsyncMock,
        ) as mock_poll:
            await run_status_reporter(shutdown, graphql_url=GRAPHQL_URL, interval=0)
            # shutdown was already set, so the while loop never enters
            mock_poll.assert_not_called()


class TestCollectCrdStatus:
    @pytest.mark.anyio
    async def test_crd_not_found_returns_none(self) -> None:
        with patch(
            "styrmin_backend.agent.status.reporter.get_custom_resource",
            new_callable=AsyncMock,
            side_effect=Exception("k8s error"),
        ):
            result = await _collect_crd_status("styrmin-test", "styrmin-test")
        assert result is None

    @pytest.mark.anyio
    async def test_crd_success(self) -> None:
        crd_data = {
            "spec": {
                "instanceId": "11111111-2222-3333-4444-555555555555",
            },
            "status": {
                "phase": "Ready",
                "displayState": "Running",
                "message": "All good",
                "conditions": [{"type": "Ready", "status": "True"}],
            },
        }
        with patch(
            "styrmin_backend.agent.status.reporter.get_custom_resource",
            new_callable=AsyncMock,
            return_value=crd_data,
        ):
            result = await _collect_crd_status("styrmin-test", "styrmin-test")
        assert result is not None
        assert result["phase"] == "Ready"
        assert result["message"] == "All good"
        assert result["instanceId"] == "11111111-2222-3333-4444-555555555555"

    @pytest.mark.anyio
    async def test_crd_instance_id_comes_from_the_status(self) -> None:
        # The operator writes the instance it acted on; a newer spec is not handled yet.
        crd_data = {
            "spec": {"instanceId": "11111111-2222-3333-4444-555555555555"},
            "status": {
                "phase": "Ready",
                "instanceId": "99999999-8888-7777-6666-555555555555",
            },
        }
        with patch(
            "styrmin_backend.agent.status.reporter.get_custom_resource",
            new_callable=AsyncMock,
            return_value=crd_data,
        ):
            result = await _collect_crd_status("styrmin-test", "styrmin-test")
        assert result is not None
        assert result["instanceId"] == "99999999-8888-7777-6666-555555555555"

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "status",
        [{"phase": "Ready"}, {"phase": "Ready", "instanceId": None}, None],
        ids=["no-status-instance", "null-status-instance", "no-status"],
    )
    async def test_crd_instance_id_falls_back_to_the_spec(
        self, status: dict | None
    ) -> None:
        crd_data = {
            "spec": {"instanceId": "11111111-2222-3333-4444-555555555555"},
            "status": status,
        }
        with patch(
            "styrmin_backend.agent.status.reporter.get_custom_resource",
            new_callable=AsyncMock,
            return_value=crd_data,
        ):
            result = await _collect_crd_status("styrmin-test", "styrmin-test")
        assert result is not None
        assert result["instanceId"] == "11111111-2222-3333-4444-555555555555"

    @pytest.mark.anyio
    async def test_crd_without_any_instance_id_reports_none(self) -> None:
        crd_data = {"spec": {}, "status": {"phase": "Ready"}}
        with patch(
            "styrmin_backend.agent.status.reporter.get_custom_resource",
            new_callable=AsyncMock,
            return_value=crd_data,
        ):
            result = await _collect_crd_status("styrmin-test", "styrmin-test")
        assert result is not None
        assert result["instanceId"] is None
