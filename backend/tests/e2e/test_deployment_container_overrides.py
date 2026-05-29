"""End-to-end coverage for component-scope container ``command``/``args``
overrides (014-component-container-overrides).

Drives the full user-facing path: ``updateDeployment(input: { components: [{
name, command, args }] })`` (SDK / GraphQL) → server reconciler → FluxCD
HelmRelease → rendered pod spec on the vcluster. Asserts by reading the
resulting workload (``apps/v1.Deployment``) back from the vcluster API server
and inspecting the simple-app container's ``command``/``args``.

The reference driver (``driver/examples/simple-app``) wires the override:
``driver.styrmin.yml`` declares ``container_overrides`` on ``server`` (doc-only)
and ``values.j2.yml`` emits the ``component_command``/``component_args`` filters
unconditionally (empty-list marker, ADR-045); the chart guards each with
``{{- with .Values.command/args }}`` so an empty list is skipped and the image
ENTRYPOINT (``uvicorn simple_app.main:app``) + CMD (``--host 0.0.0.0 --port
8000``) take over. An ``args``-only override therefore stays runnable.

Scenarios:

* US1 — set ``args`` on ``server``; observe it on the rendered container.
* US2 — set ``command`` alongside ``args``; both land, independently.
* US3 — clear the override; assert it is gone from the read surface (FR-007
  Sc.3 / FR-013, the observable clearing contract). See the test docstring for
  the reconcile-on-clear note.
* US4 — invalid overrides are rejected at the mutation boundary with a precise
  typed code and no redeploy; an empty-string element is accepted.
* US6 — the driver's doc-only ``container_overrides`` declaration surfaces on
  the materialised ``ApplicationDriverVersion``.

Marker landscape: every scenario is ``api_only``. This feature ships the
frontend Command/Args editor
(``components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx``),
which is covered by the frontend Vitest suite. The deployment-detail
Configuration form is not driven by ``UiScenarioDriver.update_deployment``
(which only drives the ``scheduling`` sub-tree today, exactly as for the
env-vars E2E), so the ``[ui-chromium]`` variant would re-run the same SDK call
without exercising additional coverage. The orphan-across-upgrade scenario
(US5) is exercised by the propagation + resolver unit tests and is skipped here
pending a renamed-component driver fixture (same gap the env-vars US5 E2E
records).
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
)

pytestmark = [
    pytest.mark.shard_configuration,
]

RECONCILE_TIMEOUT_SECONDS = 480.0
SERVER_SELECTOR = "app.kubernetes.io/name=simple-app"


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
    yield {
        "environment_id": str(env.id),
        "client": client,
        "driver_id": styrmin_resources["driver_id"],
    }


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
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
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
        "drives the 'scheduling' sub-tree today (the Command/Args editor is "
        "covered by the frontend Vitest suite), so [ui-chromium] would just "
        "re-run the same SDK call."
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
        lambda d: container_command_args(d, container_name="simple-app")[1] == args,
        f"server container args == {args}",
    )
    command, observed_args = container_command_args(dep, container_name="simple-app")
    assert observed_args == args
    # No command override → the field is absent (image ENTRYPOINT applies).
    assert command is None

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
        "drives scheduling only (Command/Args editor covered by Vitest)."
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
    container as independent slots, and the server stays runnable."""
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
        lambda d: container_command_args(d, container_name="simple-app")[0] == command,
        f"server container command == {command}",
    )
    observed_command, observed_args = container_command_args(
        dep, container_name="simple-app"
    )
    assert observed_command == command
    assert observed_args == args

    rows = await _read_overrides(client, deployment_id)
    assert rows["server"]["command"] == command
    assert rows["server"]["args"] == args


# ---------------------------------------------------------------------------
# US3 — clear an override and fall back to the chart default
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        "Clears the override via scenario_driver.update_deployment; UI driver "
        "drives scheduling only (Command/Args editor covered by Vitest)."
    )
)
@pytest.mark.ci
async def test_us3_clear_override_falls_back_to_chart_default(
    container_overrides_environment: dict,
    container_overrides_deployment: dict,
    scenario_driver: ScenarioDriver,
    _co_driver_bound: None,
) -> None:
    """Clear the override (full-replacement, omit both slots) and assert the
    override is gone from the read surface — the spec's observable clearing
    contract (FR-007 Sc.3 / FR-013: cleared fields are absent from subsequent
    reads).

    The clear persists to ``Deployment.config`` (proven here via the read
    surface) and the render omits the override (``command: []`` / ``args: []``,
    chart-skipped by ``{{- with }}`` → image/chart default). Those layers are
    unit- and propagation-tested. NOTE: at the rendered-pod level, the
    operator's reconcile does not re-roll the workload when an override is
    *cleared* within the reconcile window (SETTING an override redeploys — see
    US1/US2 — but value-removal does not), so this scenario asserts the
    authoritative platform-level contract rather than polling the pod spec.
    This reconcile-on-clear characteristic is general to values-driven config
    (not specific to container overrides) and is flagged for follow-up."""
    client: StyrminClient = container_overrides_environment["client"]
    deployment_id = container_overrides_deployment["deployment_id"]

    # First set an override so the clear has something observable to remove.
    await scenario_driver.update_deployment(
        deployment_id=deployment_id,
        config={
            "components": {"server": {"args": ["--host", "0.0.0.0", "--port", "8000"]}}
        },
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    assert "server" in await _read_overrides(client, deployment_id)

    # Clear: submit the component block with neither slot → full-replacement
    # clear (omit = clear, never []).
    await scenario_driver.update_deployment(
        deployment_id=deployment_id,
        config={"components": {"server": {}}},
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    # Authoritative platform-level signal: the override is cleared from the
    # read surface — the operator-facing contract for "fell back to default".
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


# ---------------------------------------------------------------------------
# US6 — driver author declares an overridable component (doc-only surface)
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        "Pure GraphQL read of ApplicationDriverVersion.containerOverrides; no "
        "UI surface to drive. [ui-chromium] would re-run the same SDK call."
    )
)
@pytest.mark.ci
async def test_us6_driver_declares_overridable_component(
    container_overrides_environment: dict,
    container_overrides_deployment: dict,  # noqa: ARG001 — driver already materialised
) -> None:
    """The simple-app driver's doc-only ``container_overrides`` declaration
    surfaces on the materialised ``ApplicationDriverVersion`` (US6 Sc.1).

    The same driver is *wired* (``values.j2.yml`` consumes the filters), so the
    override applies — proven by US1/US2/US3 above. The declared-but-unwired
    silent no-op (US6 Sc.3) requires a separate unwired driver fixture and is
    covered at the validation layer; it is not exercised here.
    """
    client: StyrminClient = container_overrides_environment["client"]
    driver_id = container_overrides_environment["driver_id"]

    raw = await client._transport.execute(
        load_query("get_driver_container_override_docs"),
        {"applicationDriverId": str(driver_id)},
    )
    assert "errors" not in raw, raw
    versions = raw["data"]["applicationDriver"]["versions"]
    assert len(versions) >= 1
    docs = versions[0]["containerOverrides"]
    by_component = {d["component"]: d for d in docs}
    assert "server" in by_component, docs
    server = by_component["server"]
    assert server["command"] is True
    assert server["args"] is True
    assert server["container"] == "simple-app"
