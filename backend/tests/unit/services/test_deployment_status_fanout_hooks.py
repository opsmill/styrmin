"""Unit tests for the status reporter hooks of the cluster config fan-out (021-cluster-config-update).

On a state change, ``report_deployment_statuses`` continues the environment's
fan-out when a dedicated ingress controller reaches ``RUNNING``, and runs the
controller removal check when a controller fails or an application reaches
``RUNNING`` or ``FAILED`` (research D4, D7). Each hook runs in a savepoint, so
its failure never fails the status report.
"""

from types import SimpleNamespace, TracebackType
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from styrmin_backend.domain.models import Deployment, DeploymentState
from styrmin_backend.services import cluster_config_fanout, deployment_status
from styrmin_backend.services.cluster_config_fanout import FanOutResult
from styrmin_backend.services.deployment_status import report_deployment_statuses
from tests.unit.services.cluster_fanout_support import (
    CLUSTER_CONFIG,
    build_graph,
    deploy,
    deploy_controller,
    task_deployment_ids,
    update_tasks,
)

INGRESS_ON = {**CLUSTER_CONFIG, "dedicated_ingress": {}}


class _RecordingSession:
    """Stands in for the session, recording the exception each savepoint rolled back on."""

    def __init__(self) -> None:
        self.savepoint_exits: list[type[BaseException] | None] = []

    def begin_nested(self) -> "_RecordingSession._Savepoint":
        return self._Savepoint(self)

    class _Savepoint:
        def __init__(self, session: "_RecordingSession") -> None:
            self._session = session

        async def __aenter__(self) -> None:
            return None

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool:
            self._session.savepoint_exits.append(exc_type)
            return False


@pytest.fixture(autouse=True)
def prefect(prefect_manager_mock: MagicMock) -> MagicMock:
    prefect_manager_mock.run_action = AsyncMock(return_value=MagicMock(id=uuid4()))
    return prefect_manager_mock


@pytest.fixture(autouse=True)
def no_operator_steps(mocker) -> None:
    # The fake unit of work has no step repository; the phase history has its own tests.
    mocker.patch.object(
        deployment_status, "_record_operator_steps", new_callable=AsyncMock
    )


@pytest.fixture(autouse=True)
def patch_crd(mocker) -> AsyncMock:
    mocker.patch(
        "styrmin_backend.services.deployment._record_delete_steps",
        new_callable=AsyncMock,
    )
    return mocker.patch(
        "styrmin_backend.services.deployment.patch_custom_resource",
        new_callable=AsyncMock,
    )


@pytest.fixture
def graph() -> SimpleNamespace:
    return build_graph()


def _report(deployment: Deployment, display_state: str) -> dict:
    instance = deployment.active_instance
    return {
        "deployment_id": deployment.id,
        "phase": "Ready",
        "display_state": display_state,
        "instance_id": instance.id if instance else None,
    }


def _continued_log_fields(log_info: MagicMock) -> list[dict[str, str]]:
    rendered = [
        call.args[0].format(*call.args[1:])
        for call in log_info.call_args_list
        if call.args
    ]
    return [
        dict(part.split("=", 1) for part in line.split()[1:])
        for line in rendered
        if line.startswith("cluster_config_fanout_continued ")
    ]


async def test_controller_running_continues_the_fan_out_and_moves_the_waiting_applications(
    graph, mocker
):
    app = await deploy(graph, graph.env_a, "app-a")
    graph.cluster.config = dict(INGRESS_ON)
    controller = await deploy_controller(
        graph, graph.env_a, status=DeploymentState.DEPLOYING
    )
    log_info = mocker.patch.object(cluster_config_fanout.logger, "info")

    await report_deployment_statuses([_report(controller, "Running")], graph.uow)

    assert controller.status == DeploymentState.RUNNING
    assert task_deployment_ids(update_tasks(graph)) == [app.id]
    assert app.status == DeploymentState.DEPLOYING
    assert graph.uow.committed
    [fields] = _continued_log_fields(log_info)
    assert fields == {
        "environment_id": str(graph.env_a.id),
        "trigger_deployment_id": str(controller.id),
        "environments": "1",
        "environments_failed": "0",
        "evaluated": "2",
        "dispatched": "1",
        "skipped_noop": "0",
        "skipped_restoring": "0",
        "skipped_waiting_for_ingress": "0",
        "evaluation_failed": "0",
        "dispatch_failed": "0",
        "ingress_controllers_created": "0",
        "ingress_controllers_redeployed": "0",
        "ingress_controllers_removed": "0",
        "ingress_controller_failed": "0",
        "ingress_controller_removal_failed": "0",
    }


async def test_controller_running_does_not_redeploy_an_application_being_deleted(graph):
    """Review F3: an application deleted while it waited for the controller is left to its teardown."""
    waiting = await deploy(graph, graph.env_a, "waiting")
    deleting = await deploy(graph, graph.env_a, "deleting")
    graph.cluster.config = dict(INGRESS_ON)
    controller = await deploy_controller(
        graph, graph.env_a, status=DeploymentState.DEPLOYING
    )
    deleting.set_status(DeploymentState.DELETING)

    await report_deployment_statuses([_report(controller, "Running")], graph.uow)

    assert task_deployment_ids(update_tasks(graph)) == [waiting.id]
    assert deleting.status == DeploymentState.DELETING


async def test_application_settling_off_the_controller_removes_it(graph, patch_crd):
    """The controller goes only after the application's redeploy to the shared class finished."""
    app = await deploy(graph, graph.env_a, "app-a", status=DeploymentState.DEPLOYING)
    controller = await deploy_controller(graph, graph.env_a)

    await report_deployment_statuses([_report(app, "Running")], graph.uow)

    assert app.status == DeploymentState.RUNNING
    assert controller.status == DeploymentState.DELETING
    patch_crd.assert_awaited_once()


async def test_application_failing_off_the_controller_keeps_it(graph, patch_crd):
    """Review: Flux rolls the failed upgrade back to a release whose Ingress can still use the controller."""
    app = await deploy(graph, graph.env_a, "app-a", status=DeploymentState.DEPLOYING)
    controller = await deploy_controller(graph, graph.env_a)

    await report_deployment_statuses([_report(app, "Error")], graph.uow)

    assert app.status == DeploymentState.FAILED
    assert controller.status == DeploymentState.RUNNING
    patch_crd.assert_not_awaited()


@pytest.mark.parametrize("display_state", ["Running", "Error"])
async def test_controller_turned_off_during_its_creation_is_removed_once_it_settles(
    graph, patch_crd, display_state
):
    """Critique E3: the removal check runs again when the controller reaches RUNNING or FAILED."""
    await deploy(graph, graph.env_a, "app-a")
    controller = await deploy_controller(
        graph, graph.env_a, status=DeploymentState.DEPLOYING
    )

    await report_deployment_statuses([_report(controller, display_state)], graph.uow)

    assert controller.status == DeploymentState.DELETING
    patch_crd.assert_awaited_once()


@pytest.mark.parametrize(
    ("internal", "before", "display_state", "expected_hook"),
    [
        (True, DeploymentState.DEPLOYING, "Running", "continue"),
        (True, DeploymentState.DEPLOYING, "Error", "removal"),
        (False, DeploymentState.DEPLOYING, "Running", "removal"),
        (False, DeploymentState.DEPLOYING, "Error", "removal"),
        (False, DeploymentState.RUNNING, "Error", "removal"),
        (True, DeploymentState.RUNNING, "Deploying", None),
        (False, DeploymentState.RUNNING, "Deploying", None),
        (True, DeploymentState.RUNNING, "Running", None),
        (False, DeploymentState.RUNNING, "Running", None),
        (True, DeploymentState.FAILED, "Error", None),
        (False, DeploymentState.FAILED, "Error", None),
        (False, DeploymentState.DELETING, "Deleted", "removal"),
        (True, DeploymentState.DELETING, "Deleted", None),
    ],
)
async def test_hooks_run_only_on_their_state_change(
    graph, mocker, internal, before, display_state, expected_hook
):
    subject = await deploy(
        graph, graph.env_a, "subject", internal=internal, status=before
    )
    continuation = mocker.patch.object(
        deployment_status,
        "continue_environment_fan_out",
        new_callable=AsyncMock,
        return_value=FanOutResult(),
    )
    removal = mocker.patch.object(
        deployment_status,
        "tear_down_unused_ingress_controller",
        new_callable=AsyncMock,
        return_value=0,
    )

    await report_deployment_statuses([_report(subject, display_state)], graph.uow)

    if expected_hook == "continue":
        continuation.assert_awaited_once_with(
            graph.env_a.id, graph.uow, trigger_deployment_id=subject.id
        )
    else:
        continuation.assert_not_awaited()
    if expected_hook == "removal":
        removal.assert_awaited_once_with(environment_id=graph.env_a.id, uow=graph.uow)
    else:
        removal.assert_not_awaited()


@pytest.mark.parametrize(
    ("internal", "hook", "before", "display_state", "after"),
    [
        (
            True,
            "continue_environment_fan_out",
            DeploymentState.DEPLOYING,
            "Running",
            DeploymentState.RUNNING,
        ),
        (
            False,
            "tear_down_unused_ingress_controller",
            DeploymentState.DEPLOYING,
            "Running",
            DeploymentState.RUNNING,
        ),
        (
            False,
            "tear_down_unused_ingress_controller",
            DeploymentState.DELETING,
            "Deleted",
            DeploymentState.DELETED,
        ),
    ],
    ids=["continuation", "removal-check", "removal-check-after-deletion"],
)
async def test_failing_hook_is_logged_and_rolled_back_and_the_report_still_commits(
    graph, mocker, internal, hook, before, display_state, after
):
    subject = await deploy(
        graph, graph.env_a, "subject", internal=internal, status=before
    )
    mocker.patch.object(
        deployment_status,
        hook,
        new_callable=AsyncMock,
        side_effect=RuntimeError("simulated hook failure"),
    )
    session = _RecordingSession()
    graph.uow.session = session
    log_exception = mocker.patch.object(deployment_status.logger, "exception")

    statuses_updated, deployments_updated = await report_deployment_statuses(
        [_report(subject, display_state)], graph.uow
    )

    assert (statuses_updated, deployments_updated) == (1, 1)
    assert subject.status == after
    assert await graph.uow.deployment_statuses.find_by_deployment(subject.id)
    assert graph.uow.committed
    assert session.savepoint_exits == [RuntimeError]
    log_exception.assert_called_once()
