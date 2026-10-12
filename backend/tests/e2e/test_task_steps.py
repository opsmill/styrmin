"""E2E coverage for the four SC-001 failure types of spec 019 (steps and failure causes).

One module-scoped deployment of the ``failing-actions`` test driver
(``fixtures/drivers/failing-actions``, served by the git-server fixture) hosts
every scenario, because failing the shared simple-app deployment would break
later tests of the shard. The driver's upgrade action chooses its failure from
the target version:

* ``RAISE_VERSION``: the action raises an error (the hook step fails with it);
* ``COMMAND_VERSION``: the action runs a command that prints two lines and
  exits with 3 (the hook step keeps the end of the output).

The prerequisites scenario fills a ``ResourceQuota`` so the operator cannot
re-create a network policy, and the HelmRelease scenario applies a manifest
with ``apply(wait=True)`` whose image override cannot be pulled. The HelmRelease
scenario runs last in the module, because it leaves the deployment failed.

The first three tests are ``api_only``: they read the steps through the SDK,
and the frontend component tests (``StepListFailures.test.tsx``) cover how each
failure looks on the page. The HelmRelease test runs under both entrypoints.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator

import pytest
from kubernetes_asyncio import client as kubeclient
from styrmin_sdk import StyrminClient
from styrmin_sdk._queries import load_query
from styrmin_sdk.exceptions import StyrminError
from styrmin_sdk.graphql._generated import GetStepOutput, GetStepOutputStep
from styrmin_sdk.graphql._generated.enums import Role
from styrmin_sdk.models import EnvVarInput, ResolvedManifest, UpdateDeploymentInput

from tests.e2e.drivers.api_driver import ApiScenarioDriver

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from tests.e2e.drivers import ScenarioDriver, StepRef, TimelineEntry

pytestmark = [
    pytest.mark.shard_task_steps,
]

_LOG = logging.getLogger(__name__)

# Kept in step with fixtures/drivers/failing-actions/actions.py. PEP 440 local
# versions: the backend parses versions with ``packaging``, which rejects "0.9.0-raise".
RAISE_VERSION = "0.9.0+raise"
COMMAND_VERSION = "0.9.0+command"
RAISE_MESSAGE = "failing-actions: the upgrade action raised on purpose"

UPGRADE_HOOK = "hook:upgrade:core"
PREREQUISITES = "operator:prerequisites"
HELMRELEASE = "operator:helmrelease"

STYRMIN_MANAGED_SELECTOR = "app.kubernetes.io/managed-by=styrmin"
NETWORK_POLICY_COUNT = "count/networkpolicies.networking.k8s.io"
QUOTA_NAME = "task-steps-network-policies"

# An image in the reserved ``.invalid`` domain: every pull fails at once.
MISSING_IMAGE = "registry.invalid/styrmin-e2e/simple-app:missing"

HOOK_FAILURE_TIMEOUT = 300.0
PREREQUISITE_ATTEMPTS_TIMEOUT = 240.0
# The operator's readiness timeout (210 s in the E2E values, so it fails before
# FluxCD's 4-minute timeout and rollback), its 5-second check, the agent report and
# the page refresh, with margin.
HELMRELEASE_FAILURE_BUDGET = 360.0
READ_ONLY_MATCH_TIMEOUT = 60.0
# FluxCD rolls the upgrade back at its timeout, about 30 s after the operator's
# readiness timeout, and then reconciles the rolled-back release again.
ROLLBACK_TIMEOUT = 240.0
# About 10 s after the rollback FluxCD reports the rolled-back release Ready, and the
# operator answers on its next 5-second tick with Ready=False RolledBack.
ROLLED_BACK_TIMEOUT = 120.0
# Three more operator ticks in which the failure must stay.
AFTER_ROLLED_BACK_WATCH = 15.0
# Below uvicorn's 5-second keep-alive timeout, so a read never reuses a connection
# that the server closes at that moment.
POLL_INTERVAL = 3.0

CR_GROUP = "styrmin.io"
CR_VERSION = "v1alpha1"
CR_PLURAL = "styrmindeployments"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def failing_actions_deployment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    git_server: dict[str, str],
    simple_app_image: str,  # noqa: ARG001 — the chart and the command Job run this image
    vcluster: dict,
) -> dict[str, Any]:
    """A running ``failing-actions`` deployment at 0.1.0 in an environment of its own."""
    driver, client = session_scenario_driver
    await driver.load_driver_version(
        git_url=git_server["failing-actions"], ref="master"
    )
    environment = await driver.create_environment(
        name=f"task-steps-e2e-{uuid.uuid4().hex[:8]}",
        cluster_id=styrmin_resources["cluster_id"],
        config={},
    )
    deployment = await driver.create_deployment(
        driver="failing-actions",
        version="0.1.0",
        environment_id=environment.id,
        name="task-steps",
    )
    deployment = await driver.wait_for_deployment_running(deployment_id=deployment.id)
    return {
        "deployment_id": str(deployment.id),
        "environment_id": str(environment.id),
        "namespace": f"styrmin-{deployment.id}",
        "client": client,
        "api": vcluster["api"],
    }


@pytest.fixture
async def read_only_client(
    failing_actions_deployment: dict[str, Any],
    styrmin_deployment: str,
) -> AsyncGenerator[StyrminClient, None]:
    """An SDK client logged in as a new ``READ_ONLY`` user (SC-004)."""
    admin: StyrminClient = failing_actions_deployment["client"]
    suffix = uuid.uuid4().hex[:8]
    username = f"task-steps-reader-{suffix}"
    password = f"task-steps-pw-{suffix}"
    user = await admin.users.create(
        username=username,
        password=password,
        display_name=f"Task steps reader {suffix}",
        role=Role.READ_ONLY,
    )
    try:
        async with StyrminClient(server_address=styrmin_deployment) as anonymous:
            login = await anonymous.auth.login(username=username, password=password)
        async with StyrminClient(
            server_address=styrmin_deployment, token=login.token
        ) as reader:
            yield reader
    finally:
        try:
            await admin.users.delete(user.id)
        except StyrminError as exc:
            _LOG.warning("Could not delete the READ_ONLY user %s: %s", username, exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wait_for_step(
    read_timeline: Callable[[], Awaitable[list[TimelineEntry]]],
    is_task: Callable[[TimelineEntry], bool],
    key: str,
    done: Callable[[TimelineEntry, StepRef], bool],
    *,
    timeout: float,
    interval: float = 3.0,
) -> tuple[TimelineEntry, StepRef]:
    """Read the timeline until the step ``key`` of the task that ``is_task`` picks is ``done``."""
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while True:
        for entry in await read_timeline():
            if not is_task(entry):
                continue
            step = next((step for step in entry.steps if step.key == key), None)
            if step is not None and done(entry, step):
                return entry, step
            seen = [f"result {entry.result}"] + [
                f"{s.key}={s.status} (attempts {s.attempt_count})" for s in entry.steps
            ]
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"step {key} not done within {timeout}s; the task: {seen or 'no task yet'}"
            )
        await asyncio.sleep(interval)


def _timeline_reader(
    client: StyrminClient, deployment_id: str
) -> Callable[[], Awaitable[list[TimelineEntry]]]:
    driver = ApiScenarioDriver(client)
    return lambda: driver.get_deployment_timeline(deployment_id=deployment_id)


async def _step_output(client: StyrminClient, step_id: str) -> GetStepOutputStep:
    raw = await client._transport.execute(
        load_query("get_step_output"), {"stepId": step_id}
    )
    assert "errors" not in raw, raw
    step = GetStepOutput.model_validate(raw["data"]).step
    assert step is not None, f"step {step_id} is not readable"
    return step


async def _upgrade_hook_failure(
    client: StyrminClient, deployment_id: str, version: str
) -> StepRef:
    """Upgrade through the SDK and return the upgrade's failed hook step once its task failed.

    The task result stays ``RUNNING`` until the operator has finished the rollout
    of the CR that the upgrade wrote before its hook (research D8).
    """
    task = await client.deployments.update_version(deployment_id, version)
    assert task is not None, f"upgrade to {version} dispatched no task"
    entry, hook = await _wait_for_step(
        _timeline_reader(client, deployment_id),
        lambda entry: entry.task_id == str(task.id),
        UPGRADE_HOOK,
        lambda entry, step: (
            step.status == "FAILED"
            and entry.task_status == "failed"
            and entry.result != "RUNNING"
        ),
        timeout=HOOK_FAILURE_TIMEOUT,
    )
    assert entry.task_type == "upgrade_instance", entry
    assert entry.result == "FAILED", entry
    assert hook.name == "Run the upgrade hook", hook
    assert hook.kind == "HOOK", hook
    assert hook.attempt_count == 1, hook
    assert hook.errors, f"the failed hook step has no error: {hook}"
    return hook


async def _wait_for_quota(core: kubeclient.CoreV1Api, namespace: str) -> None:
    """Wait until the quota controller has counted the network policies.

    Until then the quota admission rejects creations for an unknown status
    instead of for the exceeded count.
    """
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        quota = await core.read_namespaced_resource_quota(
            name=QUOTA_NAME, namespace=namespace
        )
        if quota.status is not None and NETWORK_POLICY_COUNT in (
            quota.status.used or {}
        ):
            return
        await asyncio.sleep(1.0)
    raise AssertionError(f"ResourceQuota {QUOTA_NAME} has no usage after 60s")


def _steps_by_task(timeline: list[TimelineEntry]) -> dict[str, tuple[StepRef, ...]]:
    return {entry.task_id: entry.steps for entry in timeline}


async def _styrmin_deployment_status(api: Any, namespace: str) -> dict[str, Any]:
    """The status of the deployment's StyrminDeployment, which is named after its namespace."""
    resource = await kubeclient.CustomObjectsApi(api).get_namespaced_custom_object(
        group=CR_GROUP,
        version=CR_VERSION,
        namespace=namespace,
        plural=CR_PLURAL,
        name=namespace,
    )
    return resource.get("status") or {}


def _is_true(status: dict[str, Any], condition_type: str) -> bool:
    return any(
        condition.get("type") == condition_type and condition.get("status") == "True"
        for condition in status.get("conditions") or ()
    )


async def _wait_for_rollback(api: Any, namespace: str) -> dict[str, Any]:
    """Wait until the operator records FluxCD's rollback; return the StyrminDeployment status."""
    deadline = time.monotonic() + ROLLBACK_TIMEOUT
    while True:
        status = await _styrmin_deployment_status(api, namespace)
        if _is_true(status, "HelmReleaseRemediated"):
            return status
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"FluxCD's rollback not recorded within {ROLLBACK_TIMEOUT}s: {status}"
            )
        await asyncio.sleep(3.0)


def _ready_reason(status: dict[str, Any]) -> str | None:
    return next(
        (
            condition.get("reason")
            for condition in status.get("conditions") or ()
            if condition.get("type") == "Ready"
        ),
        None,
    )


async def _assert_failure_stays(
    read_timeline: Callable[[], Awaitable[list[TimelineEntry]]],
    task_id: str,
    api: Any,
    namespace: str,
) -> dict[str, Any]:
    """Read the task until the operator answers FluxCD's Ready with RolledBack, then for a few ticks.

    Its result and HelmRelease step stay FAILED on every read. Returns the last
    StyrminDeployment status.
    """
    deadline = time.monotonic() + ROLLED_BACK_TIMEOUT
    rolled_back_at: float | None = None
    while True:
        entry = next(e for e in await read_timeline() if e.task_id == task_id)
        step = next(s for s in entry.steps if s.key == HELMRELEASE)
        assert step.status == "FAILED", step
        assert entry.result == "FAILED", entry
        status = await _styrmin_deployment_status(api, namespace)
        now = time.monotonic()
        if rolled_back_at is None and _ready_reason(status) == "RolledBack":
            rolled_back_at = now
        if (
            rolled_back_at is not None
            and now - rolled_back_at >= AFTER_ROLLED_BACK_WATCH
        ):
            return status
        if rolled_back_at is None and now >= deadline:
            raise AssertionError(
                f"The operator did not answer FluxCD's Ready with RolledBack within"
                f" {ROLLED_BACK_TIMEOUT}s: {status}"
            )
        await asyncio.sleep(POLL_INTERVAL)


async def _manifest_with_image(
    client: StyrminClient, deployment: dict[str, Any], image: str
) -> ResolvedManifest:
    """The deployment's current state as an apply manifest, with ``image`` on the server component."""
    stored = await client.deployments.get(deployment["deployment_id"])
    environment = await client.environments.get(
        environment_id=deployment["environment_id"]
    )
    config = stored.config or {}
    # The manifest replaces the whole config, so it must carry every stored key.
    assert set(config) <= {"env_vars", "components"}, config
    env_vars = config.get("env_vars") or {}
    return ResolvedManifest(
        name=stored.name,
        driver="failing-actions",
        version=stored.application_version,
        environment=environment.name,
        config={
            "env_vars": [
                {"name": name, "value": value} for name, value in env_vars.items()
            ],
            "components": [{"name": "server", "image": image}],
        },
        source_path=Path("task-steps.yaml"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        "Upgrades and reads the steps through the SDK; StepListFailures.test.tsx covers how "
        "a failed hook step looks on the page, so the [ui-chromium] variant adds no coverage."
    )
)
@pytest.mark.ci
async def test_hook_action_error_shows_failed_step(
    failing_actions_deployment: dict[str, Any],
) -> None:
    """SC-001 (a): the upgrade action raises; the hook step fails with the error (US2 scenario 5)."""
    client: StyrminClient = failing_actions_deployment["client"]
    hook = await _upgrade_hook_failure(
        client, failing_actions_deployment["deployment_id"], RAISE_VERSION
    )

    assert any(RAISE_MESSAGE in error.message for error in hook.errors), hook.errors
    assert not hook.has_output, hook


@pytest.mark.api_only(
    reason=(
        "Upgrades and reads the step output through the SDK; StepListFailures.test.tsx covers "
        "the output block on the page, so the [ui-chromium] variant adds no coverage."
    )
)
@pytest.mark.ci
async def test_command_output_on_failed_step(
    failing_actions_deployment: dict[str, Any],
) -> None:
    """SC-001 (b): a command run by the action exits with 3; the hook step keeps its output (US2 scenario 3)."""
    client: StyrminClient = failing_actions_deployment["client"]
    hook = await _upgrade_hook_failure(
        client, failing_actions_deployment["deployment_id"], COMMAND_VERSION
    )

    assert hook.has_output, f"the failed hook step has no output: {hook}"
    output = await _step_output(client, hook.id)
    assert output.output is not None
    assert "step-output-1" in output.output, output.output
    assert "step-output-2" in output.output, output.output
    assert not output.output_truncated, output


@pytest.mark.api_only(
    reason=(
        "Breaks a prerequisite with Kubernetes objects and reads the steps through the SDK; "
        "StepListFailures.test.tsx covers the attempts on the page."
    )
)
@pytest.mark.ci
async def test_prerequisite_failure_shows_attempts(
    failing_actions_deployment: dict[str, Any],
) -> None:
    """SC-001 (d): the operator cannot re-create a network policy; one step lists every attempt (US2 scenario 6).

    The quota allows exactly the network policies left after one is deleted, so the
    operator's re-creation fails, and its retry 30 seconds later fails again.
    """
    client: StyrminClient = failing_actions_deployment["client"]
    deployment_id = failing_actions_deployment["deployment_id"]
    namespace = failing_actions_deployment["namespace"]
    await ApiScenarioDriver(client).wait_for_deployment_running(
        deployment_id=deployment_id
    )

    networking = kubeclient.NetworkingV1Api(failing_actions_deployment["api"])
    core = kubeclient.CoreV1Api(failing_actions_deployment["api"])
    policies = (
        await networking.list_namespaced_network_policy(namespace=namespace)
    ).items
    styrmin_policies = (
        await networking.list_namespaced_network_policy(
            namespace=namespace, label_selector=STYRMIN_MANAGED_SELECTOR
        )
    ).items
    assert styrmin_policies, (
        f"no network policy of the operator in {namespace}: {[p.metadata.name for p in policies]}"
    )
    victim = styrmin_policies[0].metadata.name

    # The quota comes first, so the operator's drift check cannot re-create the policy.
    await core.create_namespaced_resource_quota(
        namespace=namespace,
        body=kubeclient.V1ResourceQuota(
            metadata=kubeclient.V1ObjectMeta(name=QUOTA_NAME),
            spec=kubeclient.V1ResourceQuotaSpec(
                hard={NETWORK_POLICY_COUNT: str(len(policies) - 1)}
            ),
        ),
    )
    try:
        await _wait_for_quota(core, namespace)
        await networking.delete_namespaced_network_policy(
            name=victim, namespace=namespace
        )

        task = await client.deployments.update(
            deployment_id,
            input=UpdateDeploymentInput(
                envVars=[EnvVarInput(name="TASK_STEPS_E2E", value="prerequisites")]
            ),
        )
        assert task is not None, "the update dispatched no task"
        entry, step = await _wait_for_step(
            _timeline_reader(client, deployment_id),
            lambda entry: entry.task_id == str(task.id),
            PREREQUISITES,
            lambda _, step: step.status == "FAILED" and step.attempt_count > 1,
            timeout=PREREQUISITE_ATTEMPTS_TIMEOUT,
        )
    finally:
        await core.delete_namespaced_resource_quota(
            name=QUOTA_NAME, namespace=namespace
        )

    assert entry.task_type == "update_instance", entry
    assert step.name == "Create network policies and secrets", step
    # The attempt count can be one above the operator's retries, so only require
    # errors from more than one attempt.
    assert len({error.attempt for error in step.errors}) > 1, step.errors
    for error in step.errors:
        assert "exceeded quota" in error.message, error
        assert QUOTA_NAME in error.message, error
    # The steps after the prerequisites wait for them.
    later = {
        s.key: s.status
        for s in entry.steps
        if s.key.startswith("operator:") and s.key != PREREQUISITES
    }
    assert set(later.values()) == {"PENDING"}, later


@pytest.mark.ci
async def test_helmrelease_failure_shows_fluxcd_reason(
    scenario_driver: ScenarioDriver,
    failing_actions_deployment: dict[str, Any],
    read_only_client: StyrminClient,
) -> None:
    """SC-001 (c): FluxCD cannot roll out an image that does not exist (US2 scenario 1, SC-004, US5 scenario 3).

    Runs last in the module: it applies an image override that cannot be pulled with
    ``apply(wait=True)``. The HelmRelease step fails at the operator's readiness
    timeout with FluxCD's reason as its detail and the pods' ``ImagePullBackOff`` in
    its error, and the apply's ``failure_reason`` names that step. A ``READ_ONLY``
    user then reads the same steps, errors and command output as the admin. After
    FluxCD's rollback, the operator fails the rollout, so the step, the task result
    and the deployment stay failed.
    """
    admin: StyrminClient = failing_actions_deployment["client"]
    deployment_id = failing_actions_deployment["deployment_id"]
    scenario_driver.attach_to_deployment(
        environment_id=failing_actions_deployment["environment_id"]
    )
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)
    admin_timeline = _timeline_reader(admin, deployment_id)
    earlier_tasks = {entry.task_id for entry in await admin_timeline()}

    manifest = await _manifest_with_image(
        admin, failing_actions_deployment, MISSING_IMAGE
    )
    started = time.monotonic()
    applying = asyncio.create_task(admin.deployments.apply(manifest, wait=True))
    try:
        entry, step = await _wait_for_step(
            lambda: scenario_driver.get_deployment_timeline(
                deployment_id=deployment_id
            ),
            lambda entry: (
                entry.task_type == "update_instance"
                and entry.task_id not in earlier_tasks
            ),
            HELMRELEASE,
            # The UI reads the result and the steps one after the other, so both must agree.
            lambda entry, step: step.status == "FAILED" and entry.result != "RUNNING",
            timeout=HELMRELEASE_FAILURE_BUDGET - (time.monotonic() - started),
            interval=POLL_INTERVAL,
        )
        outcome = await applying
    finally:
        applying.cancel()

    # US3 scenario 1: the HelmRelease failure fails the task whose flow succeeded.
    assert entry.result == "FAILED", entry
    assert step.name == "Install or upgrade the HelmRelease", step
    assert step.detail, f"the HelmRelease step has no FluxCD reason: {step}"
    assert any("ImagePullBackOff" in error.message for error in step.errors), (
        step.errors
    )
    steps = {s.key: s.status for s in entry.steps}
    assert steps[PREREQUISITES] == "SUCCEEDED", steps

    # US5 scenario 3: the wait read the failed step when it saw the failure.
    assert outcome.action == "failed", outcome
    assert str(outcome.task_id) == entry.task_id, outcome
    # Errors are only ever appended, so the reason's error is in a later read.
    errors = next(
        s.errors
        for s in _steps_by_task(await admin_timeline())[entry.task_id]
        if s.id == step.id
    )
    assert outcome.failure_reason in {
        f'step "{step.name}" failed: {error.message}' for error in errors
    }, (outcome.failure_reason, errors)

    # SC-004: a READ_ONLY user reads the same steps, errors and output. A step can
    # change between two reads, so the views are read again until they match.
    reader_timeline = _timeline_reader(read_only_client, deployment_id)
    deadline = time.monotonic() + READ_ONLY_MATCH_TIMEOUT
    while True:
        expected = _steps_by_task(await admin_timeline())
        actual = _steps_by_task(await reader_timeline())
        if actual == expected or time.monotonic() >= deadline:
            break
        await asyncio.sleep(3.0)
    assert actual == expected, "the READ_ONLY user reads other steps than the admin"
    # Errors are only ever appended, so the reader sees the failure the driver saw.
    read = next(s for s in actual[entry.task_id] if s.id == step.id)
    assert read.errors[: len(step.errors)] == step.errors, read.errors
    for task_steps in expected.values():
        for with_output in (s for s in task_steps if s.has_output):
            assert await _step_output(
                read_only_client, with_output.id
            ) == await _step_output(admin, with_output.id)

    # FluxCD rolls the upgrade back and then reports the rolled-back release Ready,
    # because the post-render override is not part of the chart or values it compares.
    # The rollout stays failed.
    namespace = failing_actions_deployment["namespace"]
    api = failing_actions_deployment["api"]
    await _wait_for_rollback(api, namespace)
    cr_status = await _assert_failure_stays(
        admin_timeline, entry.task_id, api, namespace
    )
    assert cr_status.get("phase") == "Failed", cr_status
    assert cr_status.get("displayState") == "Error", cr_status
    assert "rolled the release back" in (cr_status.get("message") or ""), cr_status
    assert not _is_true(cr_status, "Ready"), cr_status
    deployment = await admin.deployments.get(deployment_id)
    assert deployment.status == "failed", deployment.status
    final = next(
        e
        for e in await scenario_driver.get_deployment_timeline(
            deployment_id=deployment_id
        )
        if e.task_id == entry.task_id
    )
    assert final.result == "FAILED", final
    assert {s.key: s.status for s in final.steps}[HELMRELEASE] == "FAILED", final
