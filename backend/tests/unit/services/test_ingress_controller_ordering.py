"""Unit tests for the dedicated ingress controller ordering (021-cluster-config-update, User Story 2).

Covers the controller actions and the per-application rule of the cluster
config fan-out (research D4) and the extended controller removal rule
(research D5, data-model §4). Deployments and redeploys run the real context
generation, ``redeploy_for_environment_update`` and ``apply_state`` against the
fakes; only Prefect and the StyrminDeployment patch are mocked.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from styrmin_backend.context.models.config import (
    DedicatedIngressConfig,
    IngressServiceConfig,
)
from styrmin_backend.domain.models import (
    Deployment,
    DeploymentState,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services import cluster_config_fanout, deployment_status
from styrmin_backend.services.cluster_config_fanout import (
    FanOutCounts,
    continue_environment_fan_out,
    fan_out_cluster_config,
)
from styrmin_backend.services.clusters import update_cluster
from styrmin_backend.services.deployment import tear_down_unused_ingress_controller
from styrmin_backend.services.deployment_status import report_deployment_statuses
from styrmin_backend.services.environments import update_environment
from tests.unit.services.cluster_fanout_support import (
    CLUSTER_CONFIG,
    USER_ID,
    build_graph,
    deploy,
    deploy_controller,
    task_deployment_ids,
    tasks_of,
    update_tasks,
)

INGRESS_ON = {**CLUSTER_CONFIG, "dedicated_ingress": {}}
INGRESS_ON_CHANGED = {
    **CLUSTER_CONFIG,
    "dedicated_ingress": {"service": {"annotations": {"example.com/pool": "edge"}}},
}
INGRESS_OFF = dict(CLUSTER_CONFIG)


@pytest.fixture(autouse=True)
def prefect(prefect_manager_mock: MagicMock) -> MagicMock:
    prefect_manager_mock.run_action = AsyncMock(return_value=MagicMock(id=uuid4()))
    return prefect_manager_mock


@pytest.fixture(autouse=True)
def patch_crd(mocker) -> AsyncMock:
    # The fake unit of work has no step repository; the delete steps have their own tests.
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


async def _fan_out(graph: SimpleNamespace, config: dict) -> FanOutCounts:
    graph.cluster.config = dict(config)
    return await fan_out_cluster_config(graph.cluster, graph.uow, USER_ID)


def _controllers(graph: SimpleNamespace, environment) -> list[Deployment]:
    return [
        deployment
        for deployment in graph.uow.deployments._deployments
        if deployment.internal and deployment.environment_id == environment.id
    ]


def _rendered_dedicated_ingress(
    deployment: Deployment,
) -> DedicatedIngressConfig | None:
    instance = deployment.active_instance
    assert instance is not None
    return instance.context.instance.config.dedicated_ingress


# ---------------------------------------------------------------------------
# Controller actions and the per-application rule (research D4)
# ---------------------------------------------------------------------------


class TestControllerActions:
    async def test_turning_on_creates_the_controller_and_the_applications_wait(
        self, graph
    ):
        """US2 scenario 1, first half: the controller first, attributed to the administrator."""
        app_a = await deploy(graph, graph.env_a, "app-a")
        app_b = await deploy(graph, graph.env_b, "app-b")
        administrator = uuid4()
        graph.cluster.config = dict(INGRESS_ON)

        counts = await fan_out_cluster_config(graph.cluster, graph.uow, administrator)

        for environment in (graph.env_a, graph.env_b):
            [controller] = _controllers(graph, environment)
            assert controller.created_by_user_id == administrator
            assert [task.type for task in tasks_of(graph, controller)] == [
                TaskType.CREATE_INSTANCE
            ]
            assert _rendered_dedicated_ingress(controller) == DedicatedIngressConfig()
        assert update_tasks(graph) == []
        assert _rendered_dedicated_ingress(app_a) is None
        assert app_b.status == DeploymentState.RUNNING
        assert counts.ingress_controllers_created == 2
        assert counts.skipped_waiting_for_ingress == 2
        assert counts.dispatched == 0

    async def test_changed_controller_values_redeploy_the_controller_and_the_applications_wait(
        self, graph
    ):
        """US2 scenario 3: the controller is redeployed with the new values first."""
        graph.cluster.config = dict(INGRESS_ON)
        app = await deploy(graph, graph.env_a, "app-a")
        controller = await deploy_controller(graph, graph.env_a)

        counts = await _fan_out(graph, INGRESS_ON_CHANGED)

        assert task_deployment_ids(update_tasks(graph)) == [controller.id]
        assert controller.status == DeploymentState.DEPLOYING
        assert _rendered_dedicated_ingress(controller) == DedicatedIngressConfig(
            service=IngressServiceConfig(annotations={"example.com/pool": "edge"})
        )
        assert tasks_of(graph, app) == []
        assert counts.ingress_controllers_redeployed == 1
        assert counts.skipped_waiting_for_ingress == 1
        assert counts.dispatched == 0

    async def test_failed_controller_redeploy_keeps_the_applications_waiting(
        self, graph, mocker
    ):
        """Review F6: a RUNNING controller still rendered with the old values is not ready."""
        graph.cluster.config = dict(INGRESS_ON)
        app = await deploy(graph, graph.env_a, "app-a")
        controller = await deploy_controller(graph, graph.env_a)
        redeploy = cluster_config_fanout.redeploy_for_environment_update

        async def _fail_for_the_controller(
            deployment: Deployment, uow: object
        ) -> object:
            if deployment.internal:
                raise RuntimeError("simulated dispatch failure")
            return await redeploy(deployment, uow)

        mocker.patch.object(
            cluster_config_fanout,
            "redeploy_for_environment_update",
            side_effect=_fail_for_the_controller,
        )

        counts = await _fan_out(graph, INGRESS_ON_CHANGED)

        assert graph.uow.tasks.models == []
        assert tasks_of(graph, app) == []
        assert controller.status == DeploymentState.RUNNING
        assert counts.ingress_controllers_redeployed == 0
        assert counts.dispatch_failed == 1
        assert counts.skipped_waiting_for_ingress == 1
        assert counts.dispatched == 0

    async def test_applications_move_once_the_controller_runs_with_the_new_values(
        self, graph
    ):
        """US2 scenario 1, second half: a RUNNING controller with the new values lets them move."""
        app = await deploy(graph, graph.env_a, "app-a")
        graph.cluster.config = dict(INGRESS_ON)
        controller = await deploy_controller(graph, graph.env_a)

        counts = await fan_out_cluster_config(graph.cluster, graph.uow, USER_ID)

        assert task_deployment_ids(update_tasks(graph)) == [app.id]
        assert _rendered_dedicated_ingress(app) == DedicatedIngressConfig()
        assert tasks_of(graph, controller) == []
        assert counts.dispatched == 1
        assert counts.skipped_waiting_for_ingress == 0
        assert counts.ingress_controllers_created == 0
        assert counts.ingress_controllers_redeployed == 0

    async def test_applications_already_on_a_failed_controller_are_redeployed_and_it_is_left_alone(
        self, graph
    ):
        """Clarifications: the value does not change, so the applications are redeployed as usual."""
        graph.cluster.config = dict(INGRESS_ON)
        app = await deploy(graph, graph.env_a, "app-a")
        controller = await deploy_controller(
            graph, graph.env_a, status=DeploymentState.FAILED
        )

        counts = await _fan_out(graph, {**INGRESS_ON, "ingress_class": "nginx"})

        assert task_deployment_ids(update_tasks(graph)) == [app.id]
        assert controller.status == DeploymentState.FAILED
        assert tasks_of(graph, controller) == []
        assert counts.dispatched == 1
        assert counts.ingress_controllers_redeployed == 0

    async def test_resubmission_after_a_failed_turn_on_retries_the_controller_and_keeps_the_applications(
        self, graph
    ):
        """Critique E1: applications never move onto a failed controller."""
        app = await deploy(graph, graph.env_a, "app-a")
        graph.cluster.config = dict(INGRESS_ON)
        controller = await deploy_controller(
            graph, graph.env_a, status=DeploymentState.FAILED
        )

        counts = await fan_out_cluster_config(graph.cluster, graph.uow, USER_ID)

        assert task_deployment_ids(update_tasks(graph)) == [controller.id]
        assert controller.status == DeploymentState.DEPLOYING
        assert tasks_of(graph, app) == []
        assert _rendered_dedicated_ingress(app) is None
        assert counts.ingress_controllers_redeployed == 1
        assert counts.skipped_waiting_for_ingress == 1
        assert counts.dispatched == 0

    async def test_controller_being_removed_gets_no_second_controller_and_the_applications_wait(
        self, graph
    ):
        app = await deploy(graph, graph.env_a, "app-a")
        controller = await deploy_controller(
            graph, graph.env_a, status=DeploymentState.DELETING
        )

        counts = await _fan_out(graph, INGRESS_ON)

        assert _controllers(graph, graph.env_a) == [controller]
        assert graph.uow.tasks.models == []
        assert app.status == DeploymentState.RUNNING
        assert counts.ingress_controllers_created == 0
        assert counts.ingress_controllers_redeployed == 0
        assert counts.skipped_waiting_for_ingress == 1

    @pytest.mark.parametrize(
        "off_config",
        [INGRESS_OFF, {**CLUSTER_CONFIG, "dedicated_ingress": None}],
        ids=["key-left-out", "null"],
    )
    async def test_turning_off_redeploys_the_applications_now_and_keeps_the_controller_until_they_move(
        self, graph, patch_crd, off_config
    ):
        """US2 scenario 2, first half: the applications go back to the shared class first."""
        graph.cluster.config = dict(INGRESS_ON)
        app = await deploy(graph, graph.env_a, "app-a")
        controller = await deploy_controller(graph, graph.env_a)

        counts = await _fan_out(graph, off_config)

        assert task_deployment_ids(update_tasks(graph)) == [app.id]
        assert _rendered_dedicated_ingress(app) is None
        assert controller.status == DeploymentState.RUNNING
        patch_crd.assert_not_awaited()
        assert counts.dispatched == 1
        assert counts.ingress_controllers_removed == 0

    async def test_turning_off_removes_a_failed_controller_its_applications_never_moved_onto(
        self, graph, patch_crd
    ):
        """The applications are already on the shared class, so the controller goes at once."""
        app = await deploy(graph, graph.env_a, "app-a")
        graph.cluster.config = dict(INGRESS_ON)
        controller = await deploy_controller(
            graph, graph.env_a, status=DeploymentState.FAILED
        )

        counts = await _fan_out(graph, INGRESS_OFF)

        assert update_tasks(graph) == []
        assert app.status == DeploymentState.RUNNING
        assert controller.status == DeploymentState.DELETING
        patch_crd.assert_awaited_once()
        assert counts.skipped_noop == 1
        assert counts.ingress_controllers_removed == 1

    @pytest.mark.parametrize(
        ("before", "after"),
        [(INGRESS_OFF, INGRESS_ON), (INGRESS_ON, INGRESS_OFF)],
        ids=["cluster-turns-on", "cluster-turns-off"],
    )
    async def test_environment_with_its_own_dedicated_ingress_is_left_alone(
        self, graph, patch_crd, before, after
    ):
        """US2 scenario 4."""
        graph.cluster.config = dict(before)
        graph.env_b.config = {"dedicated_ingress": {}}
        app = await deploy(graph, graph.env_b, "app-b")
        controller = await deploy_controller(graph, graph.env_b)

        counts = await _fan_out(graph, after)

        assert graph.uow.tasks.models == []
        assert _controllers(graph, graph.env_b) == [controller]
        assert controller.status == DeploymentState.RUNNING
        assert app.status == DeploymentState.RUNNING
        patch_crd.assert_not_awaited()
        assert counts.skipped_noop == 1
        assert counts.ingress_controllers_created == 0
        assert counts.ingress_controllers_redeployed == 0
        assert counts.ingress_controllers_removed == 0

    async def test_environment_without_applications_gets_no_controller(self, graph):
        """US2 scenario 5: the first deploy creates it, as today."""
        counts = await _fan_out(graph, INGRESS_ON)

        assert graph.uow.deployments._deployments == []
        assert counts.ingress_controllers_created == 0

    async def test_file_without_dedicated_ingress_turns_it_off_and_removes_the_controller_after_the_move(
        self, graph, patch_crd
    ):
        """US2 scenario 6, through ``update_cluster``."""
        graph.cluster.config = dict(INGRESS_ON)
        app = await deploy(graph, graph.env_a, "app-a")
        controller = await deploy_controller(graph, graph.env_a)

        await update_cluster(
            graph.uow, graph.cluster.id, {"ingress_class": "traefik"}, USER_ID
        )

        assert "dedicated_ingress" not in graph.cluster.config
        assert task_deployment_ids(update_tasks(graph)) == [app.id]
        assert controller.status == DeploymentState.RUNNING

        app.set_status(DeploymentState.RUNNING)
        removed = await tear_down_unused_ingress_controller(graph.env_a.id, graph.uow)

        assert removed == 1
        assert controller.status == DeploymentState.DELETING
        patch_crd.assert_awaited_once()

    async def test_continuation_creates_no_controller(self, graph):
        """No administrator acts in the status reporter, so no controller is created there."""
        app = await deploy(graph, graph.env_a, "app-a")
        graph.cluster.config = dict(INGRESS_ON)

        counts = await continue_environment_fan_out(
            graph.env_a.id, graph.uow, trigger_deployment_id=uuid4()
        )

        assert _controllers(graph, graph.env_a) == []
        assert tasks_of(graph, app) == []
        assert counts.environments == 1
        assert counts.ingress_controllers_created == 0
        assert counts.skipped_waiting_for_ingress == 1


# ---------------------------------------------------------------------------
# Controller removal rule (research D5, data-model §4)
# ---------------------------------------------------------------------------


class TestControllerRemovalRule:
    @pytest.mark.parametrize(
        "app_state", [DeploymentState.PENDING, DeploymentState.DEPLOYING]
    )
    async def test_not_removed_while_an_application_is_rolling_out(
        self, graph, patch_crd, app_state
    ):
        await deploy(graph, graph.env_a, "app-a", status=app_state)
        controller = await deploy_controller(graph, graph.env_a)

        removed = await tear_down_unused_ingress_controller(graph.env_a.id, graph.uow)

        assert removed == 0
        assert controller.status == DeploymentState.RUNNING
        patch_crd.assert_not_awaited()

    async def test_not_removed_while_an_application_still_has_dedicated_ingress(
        self, graph, patch_crd
    ):
        graph.cluster.config = dict(INGRESS_ON)
        await deploy(graph, graph.env_a, "app-a")
        controller = await deploy_controller(graph, graph.env_a)
        graph.cluster.config = dict(INGRESS_OFF)

        removed = await tear_down_unused_ingress_controller(graph.env_a.id, graph.uow)

        assert removed == 0
        assert controller.status == DeploymentState.RUNNING
        patch_crd.assert_not_awaited()

    @pytest.mark.parametrize(
        "controller_state", [DeploymentState.PENDING, DeploymentState.DEPLOYING]
    )
    async def test_not_removed_while_the_controller_is_rolling_out(
        self, graph, patch_crd, controller_state
    ):
        """Critique E3: its creation flow would write the StyrminDeployment after the deletion."""
        await deploy(graph, graph.env_a, "app-a")
        controller = await deploy_controller(
            graph, graph.env_a, status=controller_state
        )

        removed = await tear_down_unused_ingress_controller(graph.env_a.id, graph.uow)

        assert removed == 0
        assert controller.status == controller_state
        patch_crd.assert_not_awaited()

    async def test_not_removed_while_the_environment_takes_dedicated_ingress(
        self, graph, patch_crd
    ):
        """Applications that wait to move onto the controller keep it."""
        await deploy(graph, graph.env_a, "app-a")
        graph.cluster.config = dict(INGRESS_ON)
        controller = await deploy_controller(graph, graph.env_a)

        removed = await tear_down_unused_ingress_controller(graph.env_a.id, graph.uow)

        assert removed == 0
        assert controller.status == DeploymentState.RUNNING
        patch_crd.assert_not_awaited()

    @pytest.mark.parametrize(
        "controller_state", [DeploymentState.RUNNING, DeploymentState.FAILED]
    )
    async def test_removed_once_every_application_is_off_it_and_settled(
        self, graph, patch_crd, controller_state
    ):
        await deploy(graph, graph.env_a, "running-app")
        await deploy(graph, graph.env_a, "failed-app", status=DeploymentState.FAILED)
        controller = await deploy_controller(
            graph, graph.env_a, status=controller_state
        )

        removed = await tear_down_unused_ingress_controller(graph.env_a.id, graph.uow)

        assert removed == 1
        assert controller.status == DeploymentState.DELETING
        assert controller.deleted_at is None
        patch_crd.assert_awaited_once()
        assert patch_crd.call_args.kwargs["reference"] == f"styrmin-{controller.id}"
        assert [task.type for task in tasks_of(graph, controller)] == [
            TaskType.DELETE_DEPLOYMENT
        ]

    async def test_last_application_deleted_rule_is_unchanged(self, graph, patch_crd):
        """#252: no application left removes the controller whatever its state or the config."""
        graph.cluster.config = dict(INGRESS_ON)
        controller = await deploy_controller(
            graph, graph.env_a, status=DeploymentState.PENDING
        )

        removed = await tear_down_unused_ingress_controller(graph.env_a.id, graph.uow)

        assert removed == 1
        assert controller.status == DeploymentState.DELETING
        patch_crd.assert_awaited_once()

    async def test_environment_update_turning_its_own_dedicated_ingress_off_removes_the_controller_after_the_move(
        self, graph, patch_crd, mocker
    ):
        """Critique E2: the state-based rule also acts after ``updateEnvironment``."""
        mocker.patch.object(
            deployment_status, "_record_operator_steps", new_callable=AsyncMock
        )
        graph.env_a.config = {"dedicated_ingress": {}}
        app = await deploy(graph, graph.env_a, "app-a")
        controller = await deploy_controller(graph, graph.env_a)

        await update_environment(graph.env_a.id, graph.uow, config={})

        [task] = tasks_of(graph, app)
        assert task.type == TaskType.UPDATE_INSTANCE
        assert controller.status == DeploymentState.RUNNING
        patch_crd.assert_not_awaited()

        task.status = TaskStatus.SUCCESS
        await report_deployment_statuses(
            [
                {
                    "deployment_id": app.id,
                    "phase": "Ready",
                    "display_state": "Running",
                    "instance_id": task.instance_id,
                }
            ],
            graph.uow,
        )

        assert app.status == DeploymentState.RUNNING
        assert controller.status == DeploymentState.DELETING
        patch_crd.assert_awaited_once()
