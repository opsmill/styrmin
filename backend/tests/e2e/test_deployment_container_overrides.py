"""End-to-end coverage for component-scope container ``command``/``args``
overrides applied by post-render (022-post-render-container-overrides, #457).

Drives the full user-facing path: ``updateDeployment(input: { components: [{
name, command, args }] })`` (SDK / GraphQL) → server reconciler → FluxCD
HelmRelease ``spec.postRenderers`` strategic merge patch on the component
container → rendered pod spec on the vcluster. Asserts by reading the
resulting workload (``apps/v1.Deployment``) back from the vcluster API server
and inspecting the simple-app container's ``command``/``args``.

The reference driver (``driver/examples/simple-app``) declares the component
container (``components.server.container: simple-app``) and has no template
code for these overrides: no ``component_command``/``component_args`` filter
calls and no ``spec.container_overrides`` block. The chart renders neither
field, so the image ENTRYPOINT (``uvicorn simple_app.main:app``) and CMD
(``--host 0.0.0.0 --port 8000``) apply; the deployment fixture captures that
chart spec as the baseline before any override is set.

Scenarios:

* US1 — set ``args`` on ``server``; observe exactly that list on the rendered
  container, with the chart's ``command`` kept.
* US2 — set ``command`` alongside ``args``; both land. Then change ``command``
  and observe the new value after the reconcile.
* US3 — set ``command`` and ``args`` through
  ``scenario_driver.set_component_container_override`` (the SDK, or the Command
  and Args editors of the Settings edit drawer), then clear both; the
  container's ``command`` and ``args`` return to the baseline (FR-003, SC-003)
  and the read surface drops the override.
* US4 — invalid overrides are rejected at the mutation boundary with a precise
  typed code and no redeploy; an empty-string element is accepted.

Marker landscape: US3 runs under both variants, so ``[ui-chromium]`` sets and
clears ``command`` and ``args`` in the editor and submits through **Review &
apply**. US1, US2 and US4 are ``api_only``: they write the whole config through
``update_deployment``, whose UI driver only drives the ``scheduling`` sub-tree,
or call the GraphQL mutation directly. The editor parts that need a component
without a component container (hidden editors, "not applied" rows) are covered
by the frontend Vitest suite, because every example driver component declares
a container.
"""

from __future__ import annotations

import uuid
from typing import Any, AsyncGenerator

import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk._queries import load_query

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.helpers.workloads import (
    _wait_for_pod_template,
    container_command_args,
    container_spec,
)

pytestmark = [
    pytest.mark.shard_configuration,
]

RECONCILE_TIMEOUT_SECONDS = 480.0
SERVER_SELECTOR = "app.kubernetes.io/name=simple-app"
SERVER_CONTAINER = "simple-app"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def container_overrides_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"container-overrides-e2e-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {"environment_id": str(env.id), "client": client}


@pytest.fixture(scope="module")
async def container_overrides_deployment(
    container_overrides_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=container_overrides_environment["environment_id"],
        name="container-overrides-a",
    )
    deployment = await driver.wait_for_deployment_running(deployment_id=deployment.id)
    namespace = f"styrmin-{deployment.id}"
    # The chart's own command/args, captured before any override (FR-003 baseline).
    workload = await _server_container(
        vcluster,
        namespace,
        lambda d: container_spec(d, SERVER_CONTAINER) is not None,
        f"server workload with container {SERVER_CONTAINER!r}",
    )
    baseline_command, baseline_args = container_command_args(
        workload, container_name=SERVER_CONTAINER
    )
    return {
        "deployment_id": str(deployment.id),
        "namespace": namespace,
        "kubeconfig_path": vcluster["kubeconfig_path"],
        "baseline_command": baseline_command,
        "baseline_args": baseline_args,
    }


@pytest.fixture
def _co_driver_bound(
    container_overrides_environment: dict,
    container_overrides_deployment: dict,  # noqa: ARG001 — force fixture ordering
    scenario_driver: ScenarioDriver,
) -> None:
    scenario_driver.attach_to_deployment(
        environment_id=container_overrides_environment["environment_id"]
    )


async def _read_overrides(client: StyrminClient, deployment_id: str) -> dict[str, dict]:
    raw = await client._transport.execute(
        load_query("get_deployment_component_container_overrides_full"),
        {"deploymentId": deployment_id},
    )
    assert "errors" not in raw, raw
    return {
        row["component"]: row
        for row in raw["data"]["deployment"]["componentContainerOverrides"]
    }


async def _server_container(vcluster: dict, namespace: str, predicate: Any, desc: str):
    return await _wait_for_pod_template(
        vcluster,
        namespace=namespace,
        label_selector=SERVER_SELECTOR,
        predicate=predicate,
        description=desc,
    )


# ---------------------------------------------------------------------------
# US1 — override args on a single component (MVP)
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        "Sets args via scenario_driver.update_deployment; the UI driver only "
        "drives the 'scheduling' sub-tree today, so [ui-chromium] would just "
        "re-run the same SDK call. US3 drives the Command and Args editors."
    )
)
@pytest.mark.ci
async def test_us1_override_args_on_server(
    container_overrides_environment: dict,
    container_overrides_deployment: dict,
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _co_driver_bound: None,
) -> None:
    """Set ``args`` on ``server`` and assert the rendered container reports
    exactly that list; read the override back through the API."""
    client: StyrminClient = container_overrides_environment["client"]
    deployment_id = container_overrides_deployment["deployment_id"]
    namespace = container_overrides_deployment["namespace"]
    args = ["--host", "0.0.0.0", "--port", "8000", "--log-level", "debug"]

    await scenario_driver.update_deployment(
        deployment_id=deployment_id,
        config={"components": {"server": {"args": args}}},
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    dep = await _server_container(
        vcluster,
        namespace,
        lambda d: container_command_args(d, container_name=SERVER_CONTAINER)[1] == args,
        f"server container args == {args}",
    )
    command, observed_args = container_command_args(
        dep, container_name=SERVER_CONTAINER
    )
    assert observed_args == args
    # An args-only override keeps the chart's command.
    assert command == container_overrides_deployment["baseline_command"]

    rows = await _read_overrides(client, deployment_id)
    assert rows["server"]["args"] == args
    assert rows["server"]["command"] is None
    assert rows["server"]["isOrphaned"] is False


# ---------------------------------------------------------------------------
# US2 — command independent of args
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        "Sets command+args via scenario_driver.update_deployment; UI driver "
        "drives scheduling only. US3 drives the Command and Args editors."
    )
)
@pytest.mark.ci
async def test_us2_command_independent_of_args(
    container_overrides_environment: dict,
    container_overrides_deployment: dict,
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _co_driver_bound: None,
) -> None:
    """Set ``command`` while carrying ``args`` forward; both land on the
    container as independent slots, and the server stays runnable. Changing
    ``command`` afterwards lands after the next reconcile."""
    client: StyrminClient = container_overrides_environment["client"]
    deployment_id = container_overrides_deployment["deployment_id"]
    namespace = container_overrides_deployment["namespace"]
    command = ["uvicorn", "simple_app.main:app"]
    args = ["--host", "0.0.0.0", "--port", "8000", "--log-level", "debug"]

    await scenario_driver.update_deployment(
        deployment_id=deployment_id,
        config={"components": {"server": {"command": command, "args": args}}},
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    dep = await _server_container(
        vcluster,
        namespace,
        lambda d: (
            container_command_args(d, container_name=SERVER_CONTAINER)[0] == command
        ),
        f"server container command == {command}",
    )
    observed_command, observed_args = container_command_args(
        dep, container_name=SERVER_CONTAINER
    )
    assert observed_command == command
    assert observed_args == args

    rows = await _read_overrides(client, deployment_id)
    assert rows["server"]["command"] == command
    assert rows["server"]["args"] == args

    # Change command only; the next reconcile replaces it and keeps args.
    changed_command = ["python", "-m", "uvicorn", "simple_app.main:app"]
    await scenario_driver.update_deployment(
        deployment_id=deployment_id,
        config={"components": {"server": {"command": changed_command, "args": args}}},
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    dep = await _server_container(
        vcluster,
        namespace,
        lambda d: (
            container_command_args(d, container_name=SERVER_CONTAINER)[0]
            == changed_command
        ),
        f"server container command == {changed_command}",
    )
    observed_command, observed_args = container_command_args(
        dep, container_name=SERVER_CONTAINER
    )
    assert observed_command == changed_command
    assert observed_args == args

    rows = await _read_overrides(client, deployment_id)
    assert rows["server"]["command"] == changed_command
    assert rows["server"]["args"] == args


# ---------------------------------------------------------------------------
# US3 — clear an override and fall back to the chart default
# ---------------------------------------------------------------------------


@pytest.mark.ci
async def test_us3_set_and_clear_command_and_args(
    container_overrides_environment: dict,
    container_overrides_deployment: dict,
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _co_driver_bound: None,
) -> None:
    """Set ``command`` and ``args``, then clear both, through the SDK or the
    Command and Args editors. The container gets both lists, then returns to the
    chart's values captured before any override was set (FR-003, SC-003), and the
    override is gone from the read surface.

    A clear removes the ``command``/``args`` patch from the HelmRelease
    ``spec.postRenderers``, so helm-controller re-renders the workload without it.
    """
    client: StyrminClient = container_overrides_environment["client"]
    deployment_id = container_overrides_deployment["deployment_id"]
    namespace = container_overrides_deployment["namespace"]
    baseline = (
        container_overrides_deployment["baseline_command"],
        container_overrides_deployment["baseline_args"],
    )
    command = ["uvicorn", "simple_app.main:app"]
    args = ["--host", "0.0.0.0", "--port", "8000"]

    await scenario_driver.set_component_container_override(
        deployment_id=deployment_id, component="server", command=command, args=args
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    await _server_container(
        vcluster,
        namespace,
        lambda d: (
            container_command_args(d, container_name=SERVER_CONTAINER)
            == (command, args)
        ),
        f"server container (command, args) == {(command, args)}",
    )
    rows = await _read_overrides(client, deployment_id)
    assert rows["server"]["command"] == command
    assert rows["server"]["args"] == args
    assert rows["server"]["isApplicable"] is True

    await scenario_driver.set_component_container_override(
        deployment_id=deployment_id, component="server", command=None, args=None
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    dep = await _server_container(
        vcluster,
        namespace,
        lambda d: (
            container_command_args(d, container_name=SERVER_CONTAINER) == baseline
        ),
        f"server container (command, args) == baseline {baseline}",
    )
    assert container_command_args(dep, container_name=SERVER_CONTAINER) == baseline

    rows = await _read_overrides(client, deployment_id)
    assert "server" not in rows, rows


# ---------------------------------------------------------------------------
# US4 — safe rejection of invalid overrides
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        "Drives the GraphQL mutation boundary directly to assert typed "
        "rejection codes; no UI flow. [ui-chromium] would re-run the same "
        "GraphQL call."
    )
)
@pytest.mark.ci
async def test_us4_invalid_overrides_rejected(
    container_overrides_environment: dict,
    container_overrides_deployment: dict,
    scenario_driver: ScenarioDriver,
    _co_driver_bound: None,
) -> None:
    """Invalid overrides are rejected at the mutation boundary with a precise
    typed code before any reconcile; an empty-string element is accepted."""
    client: StyrminClient = container_overrides_environment["client"]
    deployment_id = container_overrides_deployment["deployment_id"]

    async def _update_raw(components: list[dict]) -> dict:
        return await client._transport.execute(
            load_query("update_deployment"),
            {"deploymentId": deployment_id, "input": {"components": components}},
        )

    # (a) Unknown component → UNKNOWN_COMPONENT_CONTAINER_OVERRIDE.
    raw = await _update_raw([{"name": "ghost", "args": ["--x"]}])
    ext = (raw.get("errors") or [{}])[0].get("extensions") or {}
    assert ext.get("code") == "UNKNOWN_COMPONENT_CONTAINER_OVERRIDE", raw
    assert "server" in (ext.get("known_components") or [])

    # (b) Empty command list → INVALID_CONTAINER_COMMAND.
    raw = await _update_raw([{"name": "server", "command": []}])
    ext = (raw.get("errors") or [{}])[0].get("extensions") or {}
    assert ext.get("code") == "INVALID_CONTAINER_COMMAND", raw

    # (c) Empty args list → INVALID_CONTAINER_ARGS.
    raw = await _update_raw([{"name": "server", "args": []}])
    ext = (raw.get("errors") or [{}])[0].get("extensions") or {}
    assert ext.get("code") == "INVALID_CONTAINER_ARGS", raw

    # (d) Empty-string element is accepted (mirrors Kubernetes). Assert the
    #     mutation succeeds and the value persists; do NOT wait for the pod
    #     (an `sh -c ""` entrypoint would exit immediately).
    raw = await _update_raw([{"name": "server", "command": ["sh", "-c", ""]}])
    assert "errors" not in raw, raw
    rows = await _read_overrides(client, deployment_id)
    assert rows["server"]["command"] == ["sh", "-c", ""]

    # Restore a healthy state so teardown / re-runs leave a runnable pod.
    await scenario_driver.update_deployment(
        deployment_id=deployment_id,
        config={"components": {"server": {}}},
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
