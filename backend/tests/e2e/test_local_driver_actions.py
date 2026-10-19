"""E2E coverage for spec 029: the actions of a driver version loaded from a local directory (#372).

The ``local-actions`` test driver (``fixtures/drivers/local-actions``) is in
the Styrmin image at ``LOCAL_ACTIONS_PATH``. The server loads it from that
path with ``load-local-version``. The agent's Prefect process worker runs each
action from the same path in the agent pod, which runs the Styrmin image too.
Its ``pre_setup``, ``post_setup`` and ``upgrade`` actions only log a marker.

User story 1 (``test_local_driver_actions_run_on_create_and_upgrade``): the
load registers the three actions in Prefect, a create runs the setup actions
as the ``hook:setup:pre`` and ``hook:setup:post`` steps of its task, and an
upgrade runs the upgrade action as the ``hook:upgrade:core`` step. Each
marker is in the logs of its action's flow run.

User story 2: the variant ``local-actions-check`` of the driver is copied
into the server pod at a path of the session and loaded from there. When the
agent pod holds other files at that path
(``test_changed_local_driver_fails_with_the_fingerprint_error``), the check of
the files fails the ``hook:setup:pre`` step of the create with the provenance
fingerprint error. When the agent pod does not hold the path
(``test_driver_missing_from_the_action_image_fails_with_the_missing_files_error``),
the check fails the step with the missing files error. No action code runs.
Each test then deletes its deployment with ``deleteDeployment``. The create
failed before it wrote the ``StyrminDeployment``, so the cluster holds
nothing of the deployment, and the deployment reaches ``deleted`` without
an operator teardown (T052).

User story 3 (``test_missing_registration_fails_and_loading_again_repairs_it``)
reuses the deployment of user story 1 at ``UPGRADE_VERSION``, so it runs after
that test in the same session. It deletes the Prefect deployments of the
driver version's actions. A version change to ``CREATE_VERSION`` then returns
a failed task whose ``hook:upgrade:core`` step names the action without a
registered flow, and the deployment keeps ``UPGRADE_VERSION``. Loading the
driver again registers the actions, and the same request runs the upgrade
action. The test deletes the deployment at its end.

The module-scoped ``local_actions_deployment`` keeps the deployment for the
later tests of the module and deletes it when the module ends, unless a test
deleted it already. Every create and version change pins the
driver version, so the latest-wins rule cannot bind the deployment to another
driver version (research R-011).

The tests are ``api_only``: they read tasks, steps and Prefect logs through
the SDK and the Prefect API.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import kr8s.asyncio
import pytest
import yaml
from kr8s.asyncio.objects import Service as AsyncService
from prefect.client.orchestration import PrefectClient
from prefect.client.schemas.filters import (
    DeploymentFilter,
    DeploymentFilterId,
    DeploymentFilterTags,
    LogFilter,
    LogFilterFlowRunId,
    LogFilterTimestamp,
)
from styrmin_backend.services.driver.hash import compute_driver_directory_fingerprint
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminError
from styrmin_sdk.graphql._generated.enums import StepStatus, TaskResult

from tests.e2e.conftest import (
    _INGRESS_TEARDOWN_ERROR,
    FIXTURES_DIR,
    _portforward,
    _wait_for_http,
)
from tests.e2e.helpers.drivers import (
    AGENT_CONTAINER,
    _agent_pod_name,
    _kubectl_cp,
    _styrmin_pod_name,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator
    from pathlib import Path

    from prefect.client.schemas.responses import DeploymentResponse
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
# The steps of a delete_deployment task.
DELETE_REQUEST_STEP = "resource:delete-request"
TEARDOWN_STEP = "operator:teardown"

# The variant of the driver that user story 2 loads from paths of the session.
CHECK_DRIVER_NAME = "local-actions-check"
LOCAL_ACTIONS_DIR = FIXTURES_DIR / "drivers" / DRIVER_NAME
# The default names of the driver files (STYRMIN_DRIVER_* settings).
SPEC_FILE = "driver.styrmin.yml"
VALUES_TEMPLATE = "values.j2.yml"
ACTIONS_FILE = "actions.py"

# A create or an upgrade runs one or two action Jobs and a Helm rollout.
TASK_TIMEOUT = 600.0
INGRESS_TEARDOWN_TIMEOUT = 300.0
LOG_TIMEOUT = 120.0
RUNNING_TIMEOUT = 120.0
DELETE_TIMEOUT = 120.0
POLL_INTERVAL = 3.0


def marker(action: str, code: str = "A") -> str:
    """The line that ``action`` logs (fixtures/drivers/local-actions/actions.py).

    The fixture driver logs ``code=A``; a variant of user story 2 can log another code.
    """
    return f"LOCAL-ACTIONS-MARKER {action} code={code}"


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
    driver: str = DRIVER_NAME,
) -> str:
    """Create a deployment of ``driver`` at ``CREATE_VERSION`` pinned to the driver version.

    Returns the id of the create task. Retries only while the environment's
    ingress controller is being removed because an earlier test deleted its
    last deployment (#252).
    """
    deadline = time.monotonic() + INGRESS_TEARDOWN_TIMEOUT
    while True:
        try:
            task = await client.deployments.create(
                driver=driver,
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


def _write_check_variant(directory: Path, *, code: str) -> Path:
    """Write the ``local-actions-check`` variant of the fixture driver into ``directory``.

    Each action of the variant logs its marker with ``code=<code>``, and sets
    no ``image:``.
    """
    directory.mkdir(parents=True)
    spec = yaml.safe_load((LOCAL_ACTIONS_DIR / SPEC_FILE).read_text())
    spec["metadata"]["name"] = CHECK_DRIVER_NAME
    (directory / SPEC_FILE).write_text(yaml.safe_dump(spec, sort_keys=False))
    shutil.copyfile(LOCAL_ACTIONS_DIR / VALUES_TEMPLATE, directory / VALUES_TEMPLATE)
    actions = (LOCAL_ACTIONS_DIR / ACTIONS_FILE).read_text()
    assert marker("pre_setup") in actions, "the fixture driver no longer logs code=A"
    (directory / ACTIONS_FILE).write_text(actions.replace(" code=A", f" code={code}"))
    return directory


@pytest.fixture(scope="module")
def check_session_hex() -> str:
    """A hex string that keeps the paths of this session apart from other sessions'."""
    return uuid.uuid4().hex[:8]


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


def _failed_step_error(task: GetTaskTask, key: str) -> str:
    """The error of the step ``key`` of a failed task, which must have failed."""
    assert task.result == TaskResult.FAILED, _describe(task)
    step = next((step for step in task.steps if step.key == key), None)
    assert step is not None, f"no {key} step: {_describe(task)}"
    assert step.status == StepStatus.FAILED, _describe(task)
    assert step.error, f"the failed {key} step has no error: {_describe(task)}"
    return step.error


def _assert_steps_succeeded(task: GetTaskTask, *keys: str) -> None:
    assert task.result == TaskResult.SUCCEEDED, _describe(task)
    steps = {step.key: step for step in task.steps}
    for key in keys:
        assert key in steps, f"no {key} step: {_describe(task)}"
        assert steps[key].status == StepStatus.SUCCEEDED, _describe(task)


async def _delete_and_wait_for_tombstone(
    client: StyrminClient, deployment_id: str
) -> None:
    """Delete the deployment with ``deleteDeployment`` and read it until it is ``deleted``.

    For a deployment whose create failed before it wrote the
    ``StyrminDeployment``, the agent's status reporter finds no
    ``StyrminDeployment`` and reports the deployment as deleted, which
    succeeds the teardown step of the delete task.
    """
    task = await client.deployments.delete(deployment_id)
    assert task.type_ == "delete_deployment", task
    assert task.status == "success", task
    deadline = time.monotonic() + DELETE_TIMEOUT
    while True:
        deployment = await client.deployments.get(deployment_id)
        if deployment.status == "deleted":
            break
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Deployment {deployment_id} is not deleted after {DELETE_TIMEOUT}s: "
                f"status={deployment.status}"
            )
        await asyncio.sleep(POLL_INTERVAL)
    assert deployment.deleted_at is not None, deployment
    delete_task = await client.tasks.get(str(task.id))
    _assert_steps_succeeded(delete_task, DELETE_REQUEST_STEP, TEARDOWN_STEP)


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


async def _copy_driver_to_server(vcluster: dict, driver_dir: Path, path: str) -> None:
    """Copy the driver files in ``driver_dir`` into the Styrmin server pod at ``path``.

    ``path`` must not exist in the pod: ``kubectl cp`` then creates it with
    the files of ``driver_dir``. The server loads the driver from there.
    """
    kubeconfig = vcluster["kubeconfig_path"]
    pod = await asyncio.to_thread(_styrmin_pod_name, kubeconfig)
    await asyncio.to_thread(_kubectl_cp, kubeconfig, driver_dir, pod, path)


async def _copy_driver_to_agent(vcluster: dict, driver_dir: Path, path: str) -> None:
    """Copy the driver files in ``driver_dir`` into the agent pod at ``path``.

    The agent's Prefect process worker runs the actions, so the check reads
    the files at ``path`` in this pod. ``path`` must not exist in the pod.
    """
    kubeconfig = vcluster["kubeconfig_path"]
    pod = await asyncio.to_thread(_agent_pod_name, kubeconfig)
    await asyncio.to_thread(
        _kubectl_cp, kubeconfig, driver_dir, pod, path, container=AGENT_CONTAINER
    )


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


async def _action_deployment(
    prefect: PrefectClient, action: str, *, directory: str
) -> DeploymentResponse:
    """The Prefect deployment of ``action`` of the driver version loaded from ``directory``."""
    hook, mode = ACTION_HOOKS[action]
    deployments = await prefect.read_deployments(
        deployment_filter=DeploymentFilter(
            tags=DeploymentFilterTags(
                all_=[f"directory/{directory}", f"hook/{hook}", f"mode/{mode}"]
            )
        )
    )
    assert len(deployments) == 1, [deployment.name for deployment in deployments]
    return deployments[0]


async def _registered_action_deployments(
    prefect: PrefectClient,
) -> list[DeploymentResponse]:
    """The Prefect deployments of the actions of the driver version loaded from ``LOCAL_ACTIONS_PATH``."""
    return await prefect.read_deployments(
        deployment_filter=DeploymentFilter(
            tags=DeploymentFilterTags(all_=[DIRECTORY_TAG])
        )
    )


async def _action_log_messages(
    prefect: PrefectClient,
    action: str,
    *,
    directory: str = LOCAL_ACTIONS_PATH,
    since: datetime | None = None,
) -> list[str]:
    """The log messages of the flow runs of ``action`` of the driver version loaded from ``directory``.

    With ``since``, only the messages logged after that time.
    """
    deployment = await _action_deployment(prefect, action, directory=directory)
    runs = await prefect.read_flow_runs(
        deployment_filter=DeploymentFilter(id=DeploymentFilterId(any_=[deployment.id]))
    )
    if not runs:
        return []
    logs = await prefect.read_logs(
        log_filter=LogFilter(
            flow_run_id=LogFilterFlowRunId(any_=[run.id for run in runs]),
            timestamp=LogFilterTimestamp(after_=since) if since else None,
        )
    )
    return [log.message for log in logs]


async def _default_action_image(
    prefect: PrefectClient, action: str, *, directory: str
) -> str:
    """The image that the check names for ``action`` of the driver version loaded from ``directory``.

    The action sets no ``image:``, so the check names the default image of the
    work pool of the action's Prefect deployment. In the E2E install, that is
    the Styrmin image, which the agent that runs the action runs too.
    """
    deployment = await _action_deployment(prefect, action, directory=directory)
    assert not deployment.job_variables.get("image"), deployment.job_variables
    assert deployment.work_pool_name, deployment
    work_pool = await prefect.read_work_pool(deployment.work_pool_name)
    image = work_pool.base_job_template["variables"]["properties"]["image"]["default"]
    assert image, work_pool.base_job_template
    return str(image)


async def _wait_for_markers(
    vcluster: dict, *actions: str, since: datetime | None = None
) -> None:
    """Read the flow run logs of each action until they contain its marker.

    With ``since``, only a marker logged after that time counts.
    """
    async with _prefect(vcluster) as prefect:
        for action in actions:
            deadline = time.monotonic() + LOG_TIMEOUT
            while True:
                messages = await _action_log_messages(prefect, action, since=since)
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


@pytest.mark.api_only(reason=API_ONLY_REASON)
async def test_changed_local_driver_fails_with_the_fingerprint_error(
    styrmin_resources: dict,
    scenario_environment_id: str,
    check_session_hex: str,
    vcluster: dict,
    tmp_path: Path,
) -> None:
    """User story 2: the files where the actions run differ from the loaded files (FR-003).

    The server loads the variant with ``code=A``. The agent pod, where the
    agent's Prefect process worker runs the actions, holds the variant at the
    same path with an edited ``actions.py`` (``code=B``). The check fails the
    ``hook:setup:pre`` step with the provenance fingerprint error, and neither
    code runs. ``deleteDeployment`` then deletes the deployment of the failed
    create (T052).
    """
    client: StyrminClient = styrmin_resources["client"]
    path = f"/tmp/{CHECK_DRIVER_NAME}-{check_session_hex}"
    loaded_dir = _write_check_variant(tmp_path / "loaded", code="A")
    changed_dir = _write_check_variant(tmp_path / "changed", code="B")
    await _copy_driver_to_server(vcluster, loaded_dir, path)
    await _copy_driver_to_agent(vcluster, changed_dir, path)
    changed_fingerprint = compute_driver_directory_fingerprint(
        changed_dir,
        spec_file=SPEC_FILE,
        values_template=VALUES_TEMPLATE,
        actions_file=ACTIONS_FILE,
        include_actions=True,
    )
    loaded = await client.drivers.load_local_version(path)
    loaded_fingerprint = loaded.content_hash
    assert loaded_fingerprint is not None, loaded
    assert loaded_fingerprint != changed_fingerprint

    create_task_id = await _create_pinned_deployment(
        client,
        environment_id=scenario_environment_id,
        driver_version_id=str(loaded.id),
        name=f"{CHECK_DRIVER_NAME}-{uuid.uuid4().hex[:6]}",
        driver=CHECK_DRIVER_NAME,
    )
    create_task = await _wait_for_task_end(client, create_task_id)
    assert create_task.deployment_id is not None, create_task
    error = _failed_step_error(create_task, SETUP_PRE_HOOK)
    async with _prefect(vcluster) as prefect:
        image = await _default_action_image(prefect, "pre_setup", directory=path)
        messages = {
            action: await _action_log_messages(prefect, action, directory=path)
            for action in ACTION_HOOKS
        }
    assert path in error, error
    assert f"in the image {image}" in error, error
    assert loaded_fingerprint[:7] in error, error
    assert changed_fingerprint[:7] in error, error
    assert "Rebuild the image" in error, error

    # No code of the variant ran: neither the loaded code nor the changed one.
    # The logs are read: the check logged its error in the flow run of pre_setup.
    assert any("Rebuild the image" in message for message in messages["pre_setup"]), (
        messages
    )
    for action, action_messages in messages.items():
        for code in ("A", "B"):
            assert not any(
                marker(action, code) in message for message in action_messages
            ), (action, code, action_messages)

    await _delete_and_wait_for_tombstone(client, str(create_task.deployment_id))


@pytest.mark.api_only(reason=API_ONLY_REASON)
async def test_driver_missing_from_the_action_image_fails_with_the_missing_files_error(
    styrmin_resources: dict,
    scenario_environment_id: str,
    check_session_hex: str,
    vcluster: dict,
    tmp_path: Path,
) -> None:
    """User story 2: the driver is only in the server pod (FR-004).

    The agent pod, where the actions run, does not hold the path that the
    server loaded the driver from. The variant sets no ``image:``, so the
    error names the default image of the work pool, the Styrmin image that
    the agent runs. ``deleteDeployment`` then deletes the deployment of the
    failed create (T052).
    """
    client: StyrminClient = styrmin_resources["client"]
    path = f"/tmp/local-actions-missing-{check_session_hex}"
    driver_dir = _write_check_variant(tmp_path / "driver", code="A")
    await _copy_driver_to_server(vcluster, driver_dir, path)
    loaded = await client.drivers.load_local_version(path)

    create_task_id = await _create_pinned_deployment(
        client,
        environment_id=scenario_environment_id,
        driver_version_id=str(loaded.id),
        name=f"{CHECK_DRIVER_NAME}-{uuid.uuid4().hex[:6]}",
        driver=CHECK_DRIVER_NAME,
    )
    create_task = await _wait_for_task_end(client, create_task_id)
    assert create_task.deployment_id is not None, create_task
    error = _failed_step_error(create_task, SETUP_PRE_HOOK)
    async with _prefect(vcluster) as prefect:
        image = await _default_action_image(prefect, "pre_setup", directory=path)
    assert path in error, error
    assert f"in the image {image}" in error, error

    await _delete_and_wait_for_tombstone(client, str(create_task.deployment_id))


@pytest.mark.api_only(reason=API_ONLY_REASON)
async def test_missing_registration_fails_and_loading_again_repairs_it(
    local_actions_deployment: LocalActionsDeployment,
    vcluster: dict,
) -> None:
    """User story 3: an action without a registered flow fails its hook step, and loading again repairs it (FR-005 to FR-007).

    Runs after ``test_local_driver_actions_run_on_create_and_upgrade`` in the
    same session, which leaves the deployment running at ``UPGRADE_VERSION``.
    The version change back to ``CREATE_VERSION`` runs the upgrade hook.
    """
    client = local_actions_deployment.client
    deployment_id = local_actions_deployment.deployment_id
    driver_version_id = local_actions_deployment.driver_version_id

    deployment = await client.deployments.get(deployment_id)
    if (
        deployment.status != "running"
        or deployment.application_version != UPGRADE_VERSION
    ):
        pytest.fail(
            f"Deployment {deployment_id} must be running at {UPGRADE_VERSION}, but it is "
            f"{deployment.status} at {deployment.application_version}. Run "
            "test_local_driver_actions_run_on_create_and_upgrade before this test in "
            "the same session: it creates the deployment and upgrades it."
        )

    # Delete the registered flows of the driver version's actions.
    async with _prefect(vcluster) as prefect:
        registered = await _registered_action_deployments(prefect)
        assert len(registered) == 3, [item.name for item in registered]
        for item in registered:
            await prefect.delete_deployment(item.id)
        assert await _registered_action_deployments(prefect) == []

    # The version change fails at the upgrade hook step and changes nothing.
    failed = await client.deployments.update_version(
        deployment_id, CREATE_VERSION, driver_version_id=driver_version_id
    )
    assert failed is not None, f"the version change to {CREATE_VERSION} started no task"
    assert failed.type_ == "upgrade_instance", failed
    assert failed.status == "failed", failed
    assert failed.message is not None, failed
    assert "Load the driver again" in failed.message, failed.message
    failed_task = await client.tasks.get(str(failed.id))
    error = _failed_step_error(failed_task, UPGRADE_CORE_HOOK)
    assert f"Driver version {DRIVER_NAME} " in error, error
    assert "the action upgrade " in error, error
    assert "the upgrade hook" in error, error
    assert "mode core" in error, error
    assert "Load the driver again" in error, error
    assert f"styrminctl drivers load-local-version {LOCAL_ACTIONS_PATH}" in error, error
    assert "request the change again" in error, error
    deployment = await client.deployments.get(deployment_id)
    assert deployment.application_version == UPGRADE_VERSION, deployment
    assert deployment.status == "running", deployment
    assert str(deployment.application_driver_version_id) == driver_version_id

    # Loading the driver again registers its actions. The files did not
    # change, so the load returns the same driver version.
    reloaded = await client.drivers.load_local_version(LOCAL_ACTIONS_PATH)
    assert str(reloaded.id) == driver_version_id, reloaded
    async with _prefect(vcluster) as prefect:
        registered = await _registered_action_deployments(prefect)
    assert len(registered) == 3, [item.name for item in registered]

    # The same request now runs the upgrade action and changes the version.
    since = datetime.now(UTC)
    repaired = await client.deployments.update_version(
        deployment_id, CREATE_VERSION, driver_version_id=driver_version_id
    )
    assert repaired is not None, (
        f"the version change to {CREATE_VERSION} started no task"
    )
    assert repaired.id != failed.id, repaired
    repaired_task = await _wait_for_task_end(client, str(repaired.id))
    assert repaired_task.type_ == "upgrade_instance", _describe(repaired_task)
    _assert_steps_succeeded(repaired_task, UPGRADE_CORE_HOOK)
    await _wait_for_running(client, deployment_id, CREATE_VERSION)
    await _wait_for_markers(vcluster, "upgrade", since=since)

    deleted = await client.deployments.delete(deployment_id)
    assert deleted.type_ == "delete_deployment", deleted
