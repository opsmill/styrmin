import asyncio
import contextlib
import subprocess
import time
import warnings
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminAPIError
from tests.e2e.conftest import (
    _portforward,
    _wait_for_http,
    create_deployment_after_ingress_teardown,
)
from tests.e2e.drivers import ScenarioDriver, StepRef, TaskLinkRef, TimelineEntry
from tests.e2e.pages.environments import EnvironmentDetailPage, EnvironmentsListPage

if TYPE_CHECKING:
    from playwright.async_api import Page

pytestmark = [
    pytest.mark.shard_general,
]

# Flow steps of the upgrade, in order, with their kinds (spec 019 data-model).
UPGRADE_FLOW_STEPS = {
    "plan": "PLAN",
    "resource:styrmindeployment": "RESOURCE_WRITE",
    "hook:upgrade:core": "HOOK",
}
OPERATOR_STEPS = (
    "operator:prerequisites",
    "operator:helmrelease",
    "operator:services",
    "operator:ready",
)
FINAL_RESULTS = {"FAILED", "SUCCEEDED", "SUPERSEDED"}
#: SC-002: a user views each step change within 15 seconds, plus 2 for clock differences.
STEP_VISIBLE_WITHIN = timedelta(seconds=15 + 2)
#: This step starts at FluxCD's Ready time, which the operator reads every 60 seconds.
FLUXCD_TIMED_STEPS = {"operator:services": timedelta(seconds=60)}
TIMELINE_POLL_INTERVAL = 2.0


@pytest.mark.ci
async def test_deploy_simple_app(
    deployed_simple_app: dict,
    vcluster: dict,
) -> None:
    # Read-only observation of a running simple-app. Reuses the session-
    # scoped deployment (parametrized by driver_mode via
    # ``session_scenario_driver``) instead of deploying per-test — a deploy
    # costs ~30–60s and this test doesn't mutate the running state.
    kubeconfig_path = vcluster["kubeconfig_path"]
    namespace = deployed_simple_app["namespace"]

    # External-state assertion — identical across both entrypoints.
    # Target the driver's default service name directly; fuzzy substring
    # match picks up cross-namespace ``ExternalName`` aliases from other
    # tests' deployments that share the env.
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    simple_app_svc = await AsyncService.get(
        "simple-app", namespace=namespace, api=kr8s_api
    )
    assert simple_app_svc is not None, "simple-app service not found"

    async with _portforward(simple_app_svc, remote_port=8000) as local_port:
        # Wait for the simple-app to be reachable
        await _wait_for_http(
            f"http://localhost:{local_port}/health",
            timeout=10.0,
            interval=3.0,
        )

        # Check the /count endpoint
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(
                f"http://localhost:{local_port}/count", timeout=10
            )
            assert response.status_code == 200


async def _assert_upgrade_action_succeeded(
    scenario_driver: ScenarioDriver,
    deployment_id: str,
    version: str,
    timeout: float = 300.0,
) -> None:
    """Wait for the upgrade's tasks to finish and assert none failed (#381).

    The simple-app ``upgrade`` action calls ``stop_components`` and
    ``start_components``, which add two tasks at ``version`` next to the
    upgrade's own task. Seeing three means the action ran and the API
    accepted its calls; a failed task means a step was rejected.
    """
    deadline = time.time() + timeout
    entries = []
    while time.time() < deadline:
        timeline = await scenario_driver.get_deployment_timeline(
            deployment_id=deployment_id
        )
        entries = [e for e in timeline if e.application_version == version]
        failed = [e for e in entries if e.task_status == "failed"]
        assert not failed, f"upgrade to {version} has failed tasks: {failed}"
        if len(entries) >= 3 and all(e.task_status == "success" for e in entries):
            return
        await asyncio.sleep(3.0)
    raise AssertionError(
        f"upgrade to {version} did not finish its action within {timeout}s: {entries}"
    )


def _created(entry: TimelineEntry) -> datetime:
    assert entry.created_on is not None, f"timeline entry without created_on: {entry}"
    return datetime.fromisoformat(entry.created_on)


def _family_summary(upgrade: TimelineEntry, by_id: dict[str, TimelineEntry]) -> str:
    lines = []
    for entry in (upgrade, *(by_id.get(t.id) for t in upgrade.started_tasks)):
        if entry is None:
            continue
        steps = ", ".join(
            f"{s.key}={s.status}"
            + (f" (superseded by {s.superseded_by})" if s.superseded_by else "")
            for s in entry.steps
        )
        lines.append(f"{entry.task_type} {entry.task_id} {entry.result}: {steps}")
    return "\n".join(lines)


async def _wait_for_upgrade_family(
    scenario_driver: ScenarioDriver,
    deployment_id: str,
    version: str,
    timeout: float = 120.0,
) -> tuple[TimelineEntry, dict[str, TimelineEntry]]:
    """Read the timeline until the upgrade and the tasks its hook started have a final result.

    The upgrade is the oldest task at ``version`` that no step started. Results
    settle after the last operator report, which can come after ``RUNNING``.
    """
    deadline = time.time() + timeout
    while True:
        timeline = await scenario_driver.get_deployment_timeline(
            deployment_id=deployment_id
        )
        by_id = {entry.task_id: entry for entry in timeline}
        upgrades = [
            e
            for e in timeline
            if e.application_version == version and e.started_by is None
        ]
        upgrade = min(upgrades, key=_created) if upgrades else None
        if upgrade is not None:
            family = [upgrade, *(by_id.get(t.id) for t in upgrade.started_tasks)]
            if all(e is not None and e.result in FINAL_RESULTS for e in family):
                return upgrade, by_id
        if time.time() >= deadline:
            summary = _family_summary(upgrade, by_id) if upgrade else "no upgrade task"
            raise AssertionError(
                f"upgrade to {version} has no final result within {timeout}s:\n{summary}"
            )
        await asyncio.sleep(3.0)


def _assert_upgrade_steps(upgrade: TimelineEntry, started_ids: set[str]) -> StepRef:
    """The upgrade's steps are in order; returns its upgrade hook step.

    The prerequisites step starts when the CR write ends, so it is listed before
    the hook. A task the hook started can interrupt the upgrade's own rollout.
    """
    keys = [step.key for step in upgrade.steps]
    steps = {step.key: step for step in upgrade.steps}
    assert [k for k in keys if k in UPGRADE_FLOW_STEPS] == list(UPGRADE_FLOW_STEPS), (
        f"upgrade flow steps out of order: {keys}"
    )
    assert [k for k in keys if k.startswith("operator:")] == list(OPERATOR_STEPS), (
        f"upgrade operator steps out of order: {keys}"
    )
    for key, kind in UPGRADE_FLOW_STEPS.items():
        assert steps[key].kind == kind, steps[key]
        assert steps[key].status == "SUCCEEDED", steps[key]

    cr_written = datetime.fromisoformat(
        steps["resource:styrmindeployment"].ended_at or ""
    )
    for key in OPERATOR_STEPS:
        step = steps[key]
        assert step.kind == "OPERATOR_PHASE", step
        # A sibling's interruption is the upgrade's own work (research D8).
        assert step.status == "SUCCEEDED" or (
            step.status == "SUPERSEDED" and step.superseded_by in started_ids
        ), step
        if step.started_at is not None:
            assert datetime.fromisoformat(step.started_at) >= cr_written, step

    # Started steps in start-time order, steps that never started last.
    started = [s.started_at for s in upgrade.steps if s.started_at is not None]
    assert keys[: len(started)] == [
        s.key for s in upgrade.steps if s.started_at is not None
    ], f"a step that never started is listed before a started one: {keys}"
    assert [datetime.fromisoformat(t) for t in started] == sorted(
        datetime.fromisoformat(t) for t in started
    ), f"steps not in start-time order: {keys}"
    return steps["hook:upgrade:core"]


def _assert_upgrade_family(
    upgrade: TimelineEntry, by_id: dict[str, TimelineEntry]
) -> None:
    """Spec 019 US3: the hook's started tasks, their links and the task results."""
    summary = _family_summary(upgrade, by_id)
    assert upgrade.task_type == "upgrade_instance", summary
    started_ids = {task.id for task in upgrade.started_tasks}
    hook = _assert_upgrade_steps(upgrade, started_ids)

    # The action's upgrade_deployment_version asks for the version the upgrade
    # already set, a no-op that starts no task (spec 014).
    started = [by_id[task.id] for task in upgrade.started_tasks]
    assert sorted(e.task_type for e in started) == [
        "start_components",
        "stop_components",
    ], summary
    for link, entry in zip(upgrade.started_tasks, started, strict=True):
        # The hook step lists each task with its result, and each task links back.
        assert link.type == entry.task_type and link.result == entry.result, (
            link,
            entry,
        )
        assert entry.started_by_step_id == hook.id, entry
        assert entry.started_by == TaskLinkRef(
            id=upgrade.task_id, type="upgrade_instance", result=None
        ), entry

    assert upgrade.result == "SUCCEEDED", summary
    last, *earlier = sorted(started, key=_created, reverse=True)
    assert last.task_type == "start_components", summary
    assert last.result == "SUCCEEDED", summary
    for entry in earlier:
        assert entry.result in ("SUCCEEDED", "SUPERSEDED"), summary
        superseded = [s for s in entry.steps if s.status == "SUPERSEDED"]
        if entry.result == "SUPERSEDED":
            assert superseded, summary
        siblings = started_ids - {entry.task_id}
        assert all(s.superseded_by in siblings for s in superseded), summary


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class _StepObserver:
    """Reads the timeline every 2 seconds and notes when each new step is first seen started.

    Spec 019 US4, SC-002 (T083). Steps already started on entry are ignored.
    """

    def __init__(self, driver: ScenarioDriver, deployment_id: str) -> None:
        self._driver = driver
        self._deployment_id = deployment_id
        self._known: set[str] = set()
        self._poller: asyncio.Task[None] | None = None
        self.started_on = datetime.now(UTC)
        self.first_seen: dict[str, tuple[StepRef, datetime]] = {}

    async def __aenter__(self) -> "_StepObserver":
        self.started_on = datetime.now(UTC)
        self._known = {step.id for step in await self._started_steps()}
        self._poller = asyncio.create_task(self._poll_until_stopped())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._poller is not None:  # The test failed before ``stop``.
            self._poller.cancel()

    async def stop(self) -> None:
        """Stop polling, then read once more for steps started since the last read."""
        assert self._poller is not None, "observer is not polling"
        poller, self._poller = self._poller, None
        poller.cancel()
        # Re-raises an error that stopped the poller early.
        with contextlib.suppress(asyncio.CancelledError):
            await poller
        await self._poll()

    async def _started_steps(self) -> list[StepRef]:
        timeline = await self._driver.get_deployment_timeline(
            deployment_id=self._deployment_id
        )
        return [s for e in timeline for s in e.steps if s.started_at is not None]

    async def _poll(self) -> None:
        steps = await self._started_steps()
        seen_at = datetime.now(UTC)
        for step in steps:
            if step.id not in self._known and step.id not in self.first_seen:
                self.first_seen[step.id] = (step, seen_at)

    async def _poll_until_stopped(self) -> None:
        while True:
            began = time.monotonic()
            await self._poll()
            elapsed = time.monotonic() - began
            await asyncio.sleep(max(0.0, TIMELINE_POLL_INTERVAL - elapsed))


def _assert_steps_seen_in_time(
    observer: _StepObserver, upgrade: TimelineEntry, by_id: dict[str, TimelineEntry]
) -> None:
    """SC-002: each step the upgrade started was in the timeline within 15 seconds."""
    if _utc(upgrade.created_on or "") < observer.started_on:
        # The upgrade is idempotent: an earlier test upgraded the shared deployment.
        warnings.warn(
            f"upgrade {upgrade.task_id} predates the observer; step latency not checked",
            stacklevel=2,
        )
        return
    family = [upgrade, *(by_id[t.id] for t in upgrade.started_tasks)]
    started = [s for e in family for s in e.steps if s.started_at is not None]
    unseen = [s.key for s in started if s.id not in observer.first_seen]
    assert not unseen, f"started steps never observed by the poller: {unseen}"

    report = []
    late = []
    for step, seen_at in observer.first_seen.values():
        delay = seen_at - _utc(step.started_at or "")
        limit = STEP_VISIBLE_WITHIN + FLUXCD_TIMED_STEPS.get(step.key, timedelta())
        report.append(f"{step.key} {step.id}: {delay.total_seconds():.1f}s")
        if delay > limit:
            late.append(f"{step.key} {step.id}: {delay} > {limit}")
    print("time from startedAt to first observation:\n" + "\n".join(report))
    assert not late, "steps observed late:\n" + "\n".join(late)


@pytest.mark.ci
async def test_upgrade_simple_app(
    scenario_driver: ScenarioDriver,
    deployed_simple_app: dict,
    simple_app_image_v2: str,  # noqa: ARG001 — v0.2.0 image
    vcluster: dict,
    driver_mode: str,
) -> None:
    # Upgrade the shared session deployment in place. ``upgrade_deployment``
    # is idempotent — if another test already bumped the version, this is a
    # no-op and we go straight to the /version check.
    deployment_id = deployed_simple_app["deployment_id"]
    namespace = deployed_simple_app["namespace"]
    async with contextlib.AsyncExitStack() as stack:
        # API variant only: the poll reads the timeline through the SDK (T083).
        observer = (
            await stack.enter_async_context(
                _StepObserver(scenario_driver, deployment_id)
            )
            if driver_mode == "api"
            else None
        )
        await scenario_driver.upgrade_deployment(
            deployment_id=deployment_id, version="0.2.0"
        )
        await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)
        await _assert_upgrade_action_succeeded(scenario_driver, deployment_id, "0.2.0")
        upgrade, by_id = await _wait_for_upgrade_family(
            scenario_driver, deployment_id, "0.2.0"
        )
        if observer is not None:
            await observer.stop()
    _assert_upgrade_family(upgrade, by_id)
    if observer is not None:
        _assert_steps_seen_in_time(observer, upgrade, by_id)

    kubeconfig_path = vcluster["kubeconfig_path"]
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    simple_app_svc = await AsyncService.get(
        "simple-app", namespace=namespace, api=kr8s_api
    )
    assert simple_app_svc is not None, "simple-app service not found"

    async with _portforward(simple_app_svc, remote_port=8000) as local_port:
        await _wait_for_http(
            f"http://localhost:{local_port}/health",
            timeout=60.0,
            interval=3.0,
        )

        # The operator flips displayState=Running once HelmRelease is Ready,
        # which does not wait for the k8s rolling update to complete. Port-
        # forward may hit an old v0.1.0 pod still in the Service endpoints
        # until the rollout finishes, and requests in flight while a pod
        # terminates surface as ``RemoteProtocolError`` / ``ReadError`` /
        # ``ConnectError``. Poll until the Service returns the new version,
        # treating transport errors as "try again".
        deadline = time.time() + 120.0
        last_version: str | None = None
        async with httpx.AsyncClient() as http_client:
            while time.time() < deadline:
                try:
                    response = await http_client.get(
                        f"http://localhost:{local_port}/version", timeout=10
                    )
                except httpx.HTTPError:
                    await asyncio.sleep(3.0)
                    continue
                if response.status_code != 200:
                    await asyncio.sleep(3.0)
                    continue
                last_version = response.json()["version"]
                if last_version == "0.2.0":
                    break
                await asyncio.sleep(3.0)
            assert last_version == "0.2.0", (
                f"Service still serving {last_version!r} after 120s; "
                "rolling update to 0.2.0 did not complete"
            )


#: A PEP 440 prerelease in a non-canonical spelling (the canonical one is
#: ``0.2.0b1``), so that "stored as typed" is a real assertion (#591, FR-003).
PRERELEASE_VERSION = "0.2.0-beta.1"


@pytest.fixture(scope="module")
def simple_app_prerelease_image(simple_app_image_v2: str) -> Iterator[str]:
    """The 0.2.0 build under the tag of the prerelease; the vcluster nodes read the host daemon.

    The simple-app values template uses the application version as the image
    tag, so a deployment of ``0.2.0-beta.1`` needs this tag. Starts from the
    0.2.0 image because a prerelease of 0.2.0 is the build that precedes it.
    """
    target = f"simple-app:{PRERELEASE_VERSION}"
    subprocess.run(["docker", "tag", simple_app_image_v2, target], check=True)
    yield target
    # Removes only this tag: the session images keep theirs.
    subprocess.run(["docker", "rmi", target], check=False, capture_output=True)


@pytest.mark.ci
async def test_deploy_prerelease_simple_app(
    scenario_driver: ScenarioDriver,
    deployed_simple_app: dict,  # noqa: ARG001 — keeps the environment's ingress controller
    scenario_environment_id: str,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    styrmin_resources: dict,
    simple_app_prerelease_image: str,  # noqa: ARG001 — tags the image of the prerelease
) -> None:
    """#591: a prerelease whose numbers fit the range of the driver version deploys.

    The session ``simple-app`` driver supports ``>=0.1,<1.0``, which names no
    prerelease. The version is stored as typed, not in its canonical form. The
    deployment is then upgraded to the release, ``0.2.0``. Last, a prerelease
    of the excluded upper bound, ``1.0.0b1``, is refused with and without a pin
    (FR-004): the message names the version and the range and creates nothing.
    """
    _, client = session_scenario_driver
    deployment_id: str | None = None
    try:
        deployment = await create_deployment_after_ingress_teardown(
            scenario_driver,
            driver="simple-app",
            version=PRERELEASE_VERSION,
            environment_id=scenario_environment_id,
            # The environment is shared: the session deployment holds the default name.
            service_name_overrides=[
                {"driverServiceName": "simple-app", "overrideName": "beta-app"}
            ],
        )
        deployment_id = deployment.id
        running = await scenario_driver.wait_for_deployment_running(
            deployment_id=deployment_id
        )
        assert running.application_version == PRERELEASE_VERSION, running

        stored = await client.deployments.get(deployment_id)
        assert stored.status == "running", stored
        assert stored.application_version == PRERELEASE_VERSION, stored

        # Follow the prerelease to its release: ``0.2.0`` is above ``0.2.0-beta.1``
        # and fits the same range, so the upgrade is accepted (FR-002).
        await scenario_driver.upgrade_deployment(
            deployment_id=deployment_id, version="0.2.0"
        )
        await _assert_upgrade_action_succeeded(scenario_driver, deployment_id, "0.2.0")
        upgraded = await scenario_driver.wait_for_deployment_running(
            deployment_id=deployment_id
        )
        assert upgraded.application_version == "0.2.0", upgraded

        stored = await client.deployments.get(deployment_id)
        assert stored.status == "running", stored
        assert stored.application_version == "0.2.0", stored

        # ``1.0.0b1`` precedes the excluded upper bound ``1.0``, so it is outside
        # ``>=0.1,<1.0`` and both requests are refused with the same listing.
        refused_version = "1.0.0b1"
        deployments_before = sorted(
            deployment.id
            for deployment in await client.deployments.list(scenario_environment_id)
        )
        for pin in (None, styrmin_resources["driver_version_id"]):
            with pytest.raises(StyrminAPIError) as refused:
                await client.deployments.create(
                    driver="simple-app",
                    version=refused_version,
                    environment_id=scenario_environment_id,
                    name="refused-prerelease",
                    driver_version_id=pin,
                )
            message = str(refused.value)
            assert refused_version in message, message
            assert ">=0.1,<1.0" in message, message
            assert "prerelease" not in message.lower(), message
            deployments_after = sorted(
                deployment.id
                for deployment in await client.deployments.list(scenario_environment_id)
            )
            assert deployments_after == deployments_before, (pin, message)
    finally:
        # The environment is shared with the other tests of the file: do not leave
        # an extra deployment behind. Best effort, so that a cleanup failure does
        # not hide the failure of the test.
        if deployment_id is not None:
            with contextlib.suppress(Exception):
                await client.deployments.delete(deployment_id)


@pytest.mark.api_only(
    reason=(
        "Asserts createdBy attribution by reading the deployment through the SDK; "
        "no UI flow exercised — the [ui-chromium] variant would just re-run the "
        "same SDK call."
    ),
)
@pytest.mark.ci
async def test_deployment_records_created_by(
    deployed_simple_app: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> None:
    """Issue #190: createDeployment records the calling user as
    ``Deployment.createdBy``. The session-scoped client is the seeded
    admin (per ``authenticated_styrmin_client``), so ``createdBy`` should
    surface that user's id and username through the SDK projection.
    """
    _, client = session_scenario_driver
    deployment_id = deployed_simple_app["deployment_id"]

    deployment = await client.deployments.get(deployment_id)
    me = await client.auth.current_user()
    assert me is not None, "session client must be authenticated"
    assert deployment.created_by is not None
    assert deployment.created_by.id == me.id
    assert deployment.created_by.username == me.username
    assert deployment.created_by.display_name == me.display_name


@pytest.mark.ci
async def test_deployed_service_external_url_includes_port(
    deployed_simple_app: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> None:
    """Deployed services expose URL fields that reflect the cluster's configured
    external scheme/port.

    The session fixture configures the cluster with
    ``external_url_scheme=http`` / ``external_url_port=8080`` (matching the
    one-command demo on macOS where Traefik is reached via ``kubectl
    port-forward 8080:80``). Without these fields the frontend would render
    ``http://<host>`` (no port), which is unreachable.
    """
    _, client = session_scenario_driver
    deployment_id = deployed_simple_app["deployment_id"]

    deployment = await client.deployments.get(deployment_id)

    assert deployment.deployed_services, (
        "simple-app should expose at least one deployed service"
    )
    for svc in deployment.deployed_services:
        # Both URL forms must include the cluster's configured external port
        # so the rendered link is actually reachable from a browser on the host.
        assert svc.primary_url is not None, (
            f"primary_url should be populated for service {svc.driver_service_name!r}"
        )
        assert svc.primary_url.startswith("http://"), (
            f"primary_url should use the configured http scheme, got: {svc.primary_url}"
        )
        assert svc.primary_url.endswith(":8080"), (
            f"primary_url should include the cluster's external port (8080), got: {svc.primary_url}"
        )
        if svc.human_readable_url is not None:
            assert svc.human_readable_url.endswith(":8080"), (
                f"human_readable_url should include the cluster's external port (8080), got: {svc.human_readable_url}"
            )


def _expected_environment_status(statuses: list[str]) -> str:
    """The status rule of ``frontend/src/lib/environment-health.ts``."""
    if not statuses:
        return "pending"
    if any(status in {"FAILED", "failed"} for status in statuses):
        return "failed"
    if any(status in {"PENDING", "pending", "in_progress"} for status in statuses):
        return "pending"
    return "active"


@pytest.mark.ci
@pytest.mark.ui_only(
    reason="Asserts what the environment list and detail pages render for an "
    "environment with an internal ingress controller; the SDK has no "
    "environment status or application count."
)
async def test_environment_views_hide_ingress_controller(
    deployed_simple_app: dict,
    scenario_environment_id: str,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    session_ui_page: "Page",
) -> None:
    """#253: the environment pages list, count and summarise only the
    applications users deployed, not the internal ingress controller that the
    dedicated-ingress cluster adds to the environment."""
    _, client = session_scenario_driver

    every_deployment = await client.deployments.list(
        scenario_environment_id, include_internal=True
    )
    applications = await client.deployments.list(scenario_environment_id)
    application_ids = {str(d.id) for d in applications}
    controller_ids = {str(d.id) for d in every_deployment} - application_ids
    assert len(controller_ids) == 1, (
        "the dedicated-ingress environment should own one internal ingress "
        f"controller, got {controller_ids!r}"
    )
    assert deployed_simple_app["deployment_id"] in application_ids
    expected_status = _expected_environment_status([d.status for d in applications])

    detail = EnvironmentDetailPage(session_ui_page)
    await detail.goto(environment_id=scenario_environment_id)
    await detail.wait_for_row_to_appear(
        deployment_id=deployed_simple_app["deployment_id"]
    )
    assert await detail.read_listed_deployment_ids() == application_ids
    assert await detail.read_application_count() == len(application_ids)
    assert await detail.read_environment_status() == expected_status
    assert await session_ui_page.get_by_text("Show internal").count() == 0

    environments = EnvironmentsListPage(session_ui_page)
    await environments.goto()
    assert await environments.read_card_summary(
        environment_id=scenario_environment_id
    ) == (expected_status, len(application_ids))
