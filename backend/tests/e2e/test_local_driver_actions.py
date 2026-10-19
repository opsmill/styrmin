"""E2E coverage for spec 029: the actions of a driver version loaded from a local directory (#372).

The ``local-actions`` test driver (``fixtures/drivers/local-actions``) is in
the Styrmin image at ``LOCAL_ACTIONS_PATH``. The server loads it from that
path with ``load-local-version``, and each action runs from the same path in
its Job, which runs the Styrmin image. Its ``pre_setup``, ``post_setup`` and
``upgrade`` actions only log a marker.

User story 1 (``test_local_driver_actions_run_on_create_and_upgrade``): the
load registers the three actions in Prefect, a create runs the setup actions
as the ``hook:setup:pre`` and ``hook:setup:post`` steps of its task, and an
upgrade runs the upgrade action as the ``hook:upgrade:core`` step. Each
marker is in the logs of its action's flow run.

The module-scoped ``local_actions_deployment`` keeps the deployment for the
later tests of the module (user story 3 reuses it at ``UPGRADE_VERSION``) and
deletes it when the module ends. Every create and version change pins the
driver version, so the latest-wins rule cannot bind the deployment to another
driver version (research R-011).

The tests are ``api_only``: they read tasks, steps and Prefect logs through
the SDK and the Prefect API.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService
from prefect.client.orchestration import PrefectClient
from prefect.client.schemas.filters import (
    DeploymentFilter,
    DeploymentFilterId,
    DeploymentFilterTags,
    LogFilter,
    LogFilterFlowRunId,
)
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminError
from styrmin_sdk.graphql._generated.enums import StepStatus, TaskResult

from tests.e2e.conftest import _INGRESS_TEARDOWN_ERROR, _portforward, _wait_for_http

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

    from styrmin_sdk.graphql._generated.get_task import GetTaskTask

pytestmark = [
    pytest.mark.ci,
    pytest.mark.shard_general,
]

_LOG = logging.getLogger(__name__)

API_ONLY_REASON = (
    "The change is in which actions run; the deploy and upgrade UI flows are covered "
    "by test_deploy_app"
)

DRIVER_NAME = "local-actions"
# The path of fixtures/drivers/local-actions in the Styrmin image (docker/Dockerfile).
LOCAL_ACTIONS_PATH = "/source/backend/tests/e2e/fixtures/drivers/local-actions"
# The tag of the Prefect deployments of the actions of a driver version loaded from LOCAL_ACTIONS_PATH.
DIRECTORY_TAG = f"directory/{LOCAL_ACTIONS_PATH}"

CREATE_VERSION = "0.1.0"
UPGRADE_VERSION = "0.2.0"

# The hook and mode of each action of the driver (fixtures/drivers/local-actions/driver.styrmin.yml).
ACTION_HOOKS = {
    "pre_setup": ("setup", "pre"),
    "post_setup": ("setup", "post"),
    "upgrade": ("upgrade", "core"),
}

SETUP_PRE_HOOK = "hook:setup:pre"
SETUP_POST_HOOK = "hook:setup:post"
UPGRADE_CORE_HOOK = "hook:upgrade:core"

# A create or an upgrade runs one or two action Jobs and a Helm rollout.
TASK_TIMEOUT = 600.0
INGRESS_TEARDOWN_TIMEOUT = 300.0
LOG_TIMEOUT = 120.0
RUNNING_TIMEOUT = 120.0
POLL_INTERVAL = 3.0


def marker(action: str) -> str:
    """The line that ``action`` logs (fixtures/drivers/local-actions/actions.py)."""
    return f"LOCAL-ACTIONS-MARKER {action} code=A"


@dataclass(frozen=True)
class LocalActionsDeployment:
    """The deployment of the driver version loaded from ``LOCAL_ACTIONS_PATH``."""

    client: StyrminClient
    deployment_id: str
    driver_version_id: str
    driver_path: str
    create_task_id: str


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _create_pinned_deployment(
    client: StyrminClient,
    *,
    environment_id: str,
    driver_version_id: str,
    name: str,
) -> str:
    """Create a deployment of ``local-actions`` at ``CREATE_VERSION`` pinned to the driver version.

    Returns the id of the create task. Retries only while the environment's
    ingress controller is being removed because an earlier test deleted its
    last deployment (#252).
    """
    deadline = time.monotonic() + INGRESS_TEARDOWN_TIMEOUT
    while True:
        try:
            task = await client.deployments.create(
                driver=DRIVER_NAME,
                version=CREATE_VERSION,
                environment_id=environment_id,
                name=name,
                # Service names are unique per environment, and the session
                # simple-app deployment uses the driver's service name.
                service_name_overrides=[
                    {"driverServiceName": "simple-app", "overrideName": name}
                ],
                driver_version_id=driver_version_id,
            )
        except StyrminError as exc:
            if _INGRESS_TEARDOWN_ERROR not in str(exc) or time.monotonic() > deadline:
                raise
            _LOG.warning("Deploy rejected during ingress teardown, retrying: %s", exc)
            await asyncio.sleep(5.0)
            continue
        assert task.deployment_id is not None, task
        assert task.type_ == "create_instance", task
        return str(task.id)


@pytest.fixture(scope="module")
async def local_actions_deployment(
    styrmin_resources: dict,
    scenario_environment_id: str,
    chart_server: str,  # noqa: ARG001 — serves the simple-app chart the driver names
    simple_app_image: str,  # noqa: ARG001 — the image of the server component
    simple_app_image_v2: str,  # noqa: ARG001 — builds the image of the upgrade target
) -> AsyncGenerator[LocalActionsDeployment, None]:
    """Load ``local-actions`` from its path in the Styrmin image and create a deployment pinned to it.

    Yields as soon as the create is requested; the tests read its task. The
    deployment stays for the later tests of the module and is deleted when
    the module ends.
    """
    client: StyrminClient = styrmin_resources["client"]
    loaded = await client.drivers.load_local_version(LOCAL_ACTIONS_PATH)
    driver_version_id = str(loaded.id)
    create_task_id = await _create_pinned_deployment(
        client,
        environment_id=scenario_environment_id,
        driver_version_id=driver_version_id,
        name=f"{DRIVER_NAME}-{uuid.uuid4().hex[:6]}",
    )
    create_task = await client.tasks.get(create_task_id)
    assert create_task.deployment_id is not None, create_task
    deployment_id = str(create_task.deployment_id)
    try:
        yield LocalActionsDeployment(
            client=client,
            deployment_id=deployment_id,
            driver_version_id=driver_version_id,
            driver_path=LOCAL_ACTIONS_PATH,
            create_task_id=create_task_id,
        )
    finally:
        try:
            await client.deployments.delete(deployment_id)
        except StyrminError as exc:
            # A test of the module may have deleted it already.
            _LOG.warning("Could not delete deployment %s: %s", deployment_id, exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _describe(task: GetTaskTask) -> str:
    steps = ", ".join(
        f"{step.key}={step.status.value}" + (f" ({step.error})" if step.error else "")
        for step in task.steps
    )
    return f"task {task.id} ({task.type_}) result={task.result.value}: {steps}"


async def _wait_for_task_end(client: StyrminClient, task_id: str) -> GetTaskTask:
    """Read the task until its result is no longer ``RUNNING``.

    The result of a create or an upgrade stays ``RUNNING`` until the operator
    has finished the rollout.
    """
    deadline = time.monotonic() + TASK_TIMEOUT
    while True:
        task = await client.tasks.get(task_id)
        if task.result != TaskResult.RUNNING:
            return task
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Still running after {TASK_TIMEOUT}s: {_describe(task)}"
            )
        await asyncio.sleep(POLL_INTERVAL)


def _assert_steps_succeeded(task: GetTaskTask, *keys: str) -> None:
    assert task.result == TaskResult.SUCCEEDED, _describe(task)
    steps = {step.key: step for step in task.steps}
    for key in keys:
        assert key in steps, f"no {key} step: {_describe(task)}"
        assert steps[key].status == StepStatus.SUCCEEDED, _describe(task)


async def _wait_for_running(
    client: StyrminClient, deployment_id: str, version: str
) -> None:
    """Read the deployment until it is ``running`` at ``version``."""
    deadline = time.monotonic() + RUNNING_TIMEOUT
    while True:
        deployment = await client.deployments.get(deployment_id)
        if deployment.status == "running" and deployment.application_version == version:
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Deployment {deployment_id} is not running at {version} after "
                f"{RUNNING_TIMEOUT}s: status={deployment.status} "
                f"version={deployment.application_version}"
            )
        await asyncio.sleep(POLL_INTERVAL)


@asynccontextmanager
async def _prefect(vcluster: dict) -> AsyncIterator[PrefectClient]:
    """A Prefect client on a port-forward to the vCluster's Prefect server."""
    kr8s_api = await kr8s.asyncio.api(kubeconfig=vcluster["kubeconfig_path"])
    prefect_service = await AsyncService.get(
        "prefect-server", namespace="styrmin", api=kr8s_api
    )
    async with _portforward(prefect_service, remote_port=4200) as port:
        prefect_url = f"http://localhost:{port}/api"
        await _wait_for_http(f"{prefect_url}/health", timeout=60.0)
        async with PrefectClient(api=prefect_url) as prefect:
            yield prefect


async def _action_log_messages(prefect: PrefectClient, action: str) -> list[str]:
    """The log messages of the flow runs of ``action`` of the driver version at ``LOCAL_ACTIONS_PATH``."""
    hook, mode = ACTION_HOOKS[action]
    deployments = await prefect.read_deployments(
        deployment_filter=DeploymentFilter(
            tags=DeploymentFilterTags(
                all_=[DIRECTORY_TAG, f"hook/{hook}", f"mode/{mode}"]
            )
        )
    )
    assert len(deployments) == 1, [deployment.name for deployment in deployments]
    runs = await prefect.read_flow_runs(
        deployment_filter=DeploymentFilter(
            id=DeploymentFilterId(any_=[deployments[0].id])
        )
    )
    if not runs:
        return []
    logs = await prefect.read_logs(
        log_filter=LogFilter(
            flow_run_id=LogFilterFlowRunId(any_=[run.id for run in runs])
        )
    )
    return [log.message for log in logs]


async def _wait_for_markers(vcluster: dict, *actions: str) -> None:
    """Read the flow run logs of each action until they contain its marker."""
    async with _prefect(vcluster) as prefect:
        for action in actions:
            deadline = time.monotonic() + LOG_TIMEOUT
            while True:
                messages = await _action_log_messages(prefect, action)
                if any(marker(action) in message for message in messages):
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError(
                        f"{marker(action)!r} is not in the flow run logs of {action} "
                        f"after {LOG_TIMEOUT}s: {messages}"
                    )
                await asyncio.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.api_only(reason=API_ONLY_REASON)
async def test_local_driver_actions_run_on_create_and_upgrade(
    local_actions_deployment: LocalActionsDeployment,
    vcluster: dict,
) -> None:
    """User story 1: the setup and upgrade actions of a local driver version run (FR-001, FR-002)."""
    client = local_actions_deployment.client
    deployment_id = local_actions_deployment.deployment_id
    driver_version_id = local_actions_deployment.driver_version_id

    # The load registered the three actions of the driver version.
    async with _prefect(vcluster) as prefect:
        registered = await prefect.read_deployments(
            deployment_filter=DeploymentFilter(
                tags=DeploymentFilterTags(all_=[DIRECTORY_TAG])
            )
        )
    assert len(registered) == 3, [deployment.name for deployment in registered]

    # The create ran the setup actions as the hook steps of its task.
    create_task = await _wait_for_task_end(
        client, local_actions_deployment.create_task_id
    )
    _assert_steps_succeeded(create_task, SETUP_PRE_HOOK, SETUP_POST_HOOK)
    await _wait_for_running(client, deployment_id, CREATE_VERSION)

    # The upgrade ran the upgrade action as the upgrade hook step of its task.
    upgrade = await client.deployments.update_version(
        deployment_id, UPGRADE_VERSION, driver_version_id=driver_version_id
    )
    assert upgrade is not None, f"the upgrade to {UPGRADE_VERSION} started no task"
    upgrade_task = await _wait_for_task_end(client, str(upgrade.id))
    assert upgrade_task.type_ == "upgrade_instance", _describe(upgrade_task)
    _assert_steps_succeeded(upgrade_task, UPGRADE_CORE_HOOK)
    await _wait_for_running(client, deployment_id, UPGRADE_VERSION)
    deployment = await client.deployments.get(deployment_id)
    assert str(deployment.application_driver_version_id) == driver_version_id

    # Each action ran its own code: the marker is in the logs of its flow run.
    await _wait_for_markers(vcluster, "pre_setup", "post_setup", "upgrade")
