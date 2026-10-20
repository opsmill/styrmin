"""E2E check: the bundled ``infrahub`` driver, loaded from a local directory, runs its actions (#372).

Spec 029, SC-001: the operator loads the bundled driver from
``/styrmin/drivers/infrahub``, the path where the Styrmin image holds it, as
the documentation says. A create then runs the driver's ``pre_setup`` and
``post_setup`` actions, and an upgrade runs its ``upgrade`` action. That action
stops the Infrahub server and task workers, changes the deployment's version,
runs ``infrahub upgrade`` in a Job (``execute_commands``) and starts the
components again.

Not in CI: this test has no ``ci`` marker, because it boots a full Infrahub
stack (about 10 to 15 minutes) and the ``shard_infrahub`` shard already boots
one. ``test_local_driver_actions.py`` covers the same code paths in CI with a
small test driver. Run it by hand after a change to how actions run, and
record the run in ``specs/029-local-driver-actions/e2e-evidence.md``::

    sleep infinity | uv run pytest \\
        backend/tests/e2e/test_infrahub_local_driver_actions.py -v -s --pdb
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING

import pytest
from kubernetes_asyncio import client as kubeclient
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminError
from styrmin_sdk.graphql._generated.enums import StepStatus, TaskResult

if TYPE_CHECKING:
    from styrmin_sdk.graphql._generated.get_task import GetTaskTask

_LOG = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.api_only(
        reason="Checks which actions run and reads tasks, steps and the Job through "
        "the SDK and the Kubernetes API; the deploy and upgrade UI flows are covered "
        "by test_deploy_app"
    ),
]

# Where the Styrmin image holds the bundled drivers (docker/Dockerfile).
INFRAHUB_PATH = "/styrmin/drivers/infrahub"
CREATE_VERSION = "1.6.0"
UPGRADE_VERSION = "1.7.0"

SETUP_PRE_HOOK = "hook:setup:pre"
SETUP_POST_HOOK = "hook:setup:post"
UPGRADE_CORE_HOOK = "hook:upgrade:core"

# Infrahub has many components; the upgrade action stops and starts them and runs a migration.
CREATE_TIMEOUT = 900.0
UPGRADE_TIMEOUT = 1200.0
POLL_INTERVAL = 10.0


def _describe(task: GetTaskTask) -> str:
    steps = ", ".join(
        f"{step.key}={step.status.value}" + (f" ({step.error})" if step.error else "")
        for step in task.steps
    )
    return f"task {task.id} ({task.type_}) result={task.result.value}: {steps}"


async def _wait_for_task_end(
    client: StyrminClient, task_id: str, timeout: float
) -> GetTaskTask:
    """Read the task until its result is no longer ``RUNNING``."""
    deadline = time.monotonic() + timeout
    while True:
        task = await client.tasks.get(task_id)
        if task.result != TaskResult.RUNNING:
            _LOG.info("Task ended: %s", _describe(task))
            return task
        if time.monotonic() >= deadline:
            raise AssertionError(f"Still running after {timeout}s: {_describe(task)}")
        await asyncio.sleep(POLL_INTERVAL)


def _assert_steps_succeeded(task: GetTaskTask, *keys: str) -> None:
    assert task.result == TaskResult.SUCCEEDED, _describe(task)
    steps = {step.key: step for step in task.steps}
    for key in keys:
        assert key in steps, f"no {key} step: {_describe(task)}"
        assert steps[key].status == StepStatus.SUCCEEDED, _describe(task)


async def _wait_for_running(
    client: StyrminClient, deployment_id: str, version: str, timeout: float
) -> None:
    deadline = time.monotonic() + timeout
    while True:
        deployment = await client.deployments.get(deployment_id)
        if deployment.status == "running" and deployment.application_version == version:
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Deployment {deployment_id} is not running at {version} after "
                f"{timeout}s: status={deployment.status} "
                f"version={deployment.application_version}"
            )
        await asyncio.sleep(POLL_INTERVAL)


async def test_bundled_infrahub_driver_loaded_from_a_local_directory_runs_its_actions(
    styrmin_resources: dict,
    vcluster: dict,
) -> None:
    client: StyrminClient = styrmin_resources["client"]
    environment_id: str = styrmin_resources["environment_id"]
    loaded = await client.drivers.load_local_version(INFRAHUB_PATH)
    assert loaded.content_hash is not None, loaded
    _LOG.info(
        "Loaded infrahub from %s: driver version %s (%s)",
        INFRAHUB_PATH,
        loaded.id,
        loaded.content_hash[:7],
    )

    name = f"infrahub-local-{uuid.uuid4().hex[:6]}"
    create = await client.deployments.create(
        driver="infrahub",
        version=CREATE_VERSION,
        environment_id=environment_id,
        name=name,
        # Service names are unique per environment; other Infrahub tests use the driver's.
        service_name_overrides=[
            {"driverServiceName": "infrahub", "overrideName": name},
            {"driverServiceName": "task-manager", "overrideName": f"{name}-tasks"},
        ],
        driver_version_id=str(loaded.id),
    )
    assert create.deployment_id is not None, create
    deployment_id = str(create.deployment_id)
    try:
        # The create runs the setup actions as the hook steps of its task.
        create_task = await _wait_for_task_end(
            client, str(create.id), timeout=CREATE_TIMEOUT
        )
        _assert_steps_succeeded(create_task, SETUP_PRE_HOOK, SETUP_POST_HOOK)
        await _wait_for_running(
            client, deployment_id, CREATE_VERSION, timeout=CREATE_TIMEOUT
        )

        # The upgrade runs the upgrade action as the upgrade hook step of its task.
        upgrade = await client.deployments.update_version(
            deployment_id, UPGRADE_VERSION, driver_version_id=str(loaded.id)
        )
        assert upgrade is not None, f"the upgrade to {UPGRADE_VERSION} started no task"
        upgrade_task = await _wait_for_task_end(
            client, str(upgrade.id), timeout=UPGRADE_TIMEOUT
        )
        assert upgrade_task.type_ == "upgrade_instance", _describe(upgrade_task)
        _assert_steps_succeeded(upgrade_task, UPGRADE_CORE_HOOK)
        await _wait_for_running(
            client, deployment_id, UPGRADE_VERSION, timeout=UPGRADE_TIMEOUT
        )

        # The upgrade action ran ``infrahub upgrade`` in its Job, in the target image.
        namespace = f"styrmin-{deployment_id}"
        job_name = f"{namespace}-job"
        batch = kubeclient.BatchV1Api(vcluster["api"])
        job = await batch.read_namespaced_job(name=job_name, namespace=namespace)
        assert job.status.succeeded == 1, f"Job {namespace}/{job_name}: {job.status}"
        assert job.metadata.labels["styrmin.io/action-job"] == "true", job.metadata
        (container,) = job.spec.template.spec.containers
        assert container.image.endswith(f"/infrahub:{UPGRADE_VERSION}"), container
        core = kubeclient.CoreV1Api(vcluster["api"])
        pods = await core.list_namespaced_pod(
            namespace, label_selector=f"batch.kubernetes.io/job-name={job_name}"
        )
        for pod in pods.items:
            log = await core.read_namespaced_pod_log(
                name=pod.metadata.name, namespace=namespace, tail_lines=20
            )
            _LOG.info("End of the output of %s:\n%s", pod.metadata.name, log)
    finally:
        try:
            await client.deployments.delete(deployment_id)
        except StyrminError as exc:
            _LOG.warning("Could not delete deployment %s: %s", deployment_id, exc)
