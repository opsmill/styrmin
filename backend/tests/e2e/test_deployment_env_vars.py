"""End-to-end coverage for deployment environment variables (008 / US1+).

Drives the full user-facing path: ``updateDeployment(config: { env_vars: ... })``
(SDK / GraphQL) → server reconciler → FluxCD HelmRelease post-renderers →
rendered pod spec on the vcluster. Asserts by reading the resulting
workload (``apps/v1.Deployment`` / ``StatefulSet`` / ``DaemonSet``) back
from the vcluster API server and inspecting the container ``env`` block.

US1 scenario corresponds to Quickstart Step 1: deploy ``simple-app``, set
``LOG_LEVEL=debug`` on the deployment, observe the env entry on every
container's ``env:`` list.

Marker landscape (audited under 011/US4): every scenario in this file
keeps its ``api_only`` marker. Although ``scenario_driver.update_deployment``
is a dual-entrypoint method, the UI driver's implementation only accepts
the ``scheduling`` sub-tree (see ``UiScenarioDriver.update_deployment``);
the deployment-detail page exposes no env-vars editor today, so a
``[ui-chromium]`` variant of these scenarios would raise
``ScenarioActionError`` immediately. The driver-docs scenario is a pure
GraphQL read with no UI surface either. Each retained marker carries an
inline FR-015 rationale; the markers will retire as the deployment-level
env-vars UI lands in a future iteration. The 011/US4 audit's marker-count
reduction therefore comes entirely from the environment-update tests
where ``scenario_driver.update_environment_via_form`` is now wired
up.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncGenerator

import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk._queries import load_query

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.helpers.workloads import _wait_for_pod_template

pytestmark = [
    pytest.mark.shard_env_vars,
]

RECONCILE_TIMEOUT_SECONDS = 480.0


def _container_envs(dep: Any) -> list[dict[str, str]]:
    """Return the flattened list of ``env`` entries across every container in
    the rendered pod template, normalised to plain ``{name, value}`` dicts.
    """
    envs: list[dict[str, str]] = []
    for container in dep.spec.template.spec.containers or []:
        for entry in container.env or []:
            envs.append(
                {
                    "name": entry.name,
                    "value": entry.value if entry.value is not None else "",
                }
            )
    return envs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def env_vars_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"env-vars-e2e-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {
        "environment_id": str(env.id),
        "client": client,
    }


@pytest.fixture(scope="module")
async def env_vars_deployment(
    env_vars_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=env_vars_environment["environment_id"],
        name="env-vars-a",
    )
    deployment = await driver.wait_for_deployment_running(deployment_id=deployment.id)
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


@pytest.fixture
def _env_vars_driver_bound(
    env_vars_environment: dict,
    env_vars_deployment: dict,  # noqa: ARG001 — force fixture ordering
    scenario_driver: ScenarioDriver,
) -> None:
    scenario_driver.attach_to_deployment(
        environment_id=env_vars_environment["environment_id"]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        # 011/US4 audit (FR-015): the UI driver's update_deployment only
        # supports the ``scheduling`` sub-tree (see UiScenarioDriver
        # rejection at drivers/ui_driver.py); there is no UI surface for
        # ``deployment.config.env_vars``. Until the deployment-detail
        # page grows an env-vars editor, the ``[ui-chromium]`` variant
        # cannot drive this flow.
        "Drives scenario_driver.update_deployment with env_vars; the UI "
        "driver only accepts the 'scheduling' sub-tree today (no "
        "deployment-detail env-vars form exists yet)."
    )
)
@pytest.mark.ci
async def test_us1_deployment_level_env_var(
    env_vars_environment: dict,
    env_vars_deployment: dict,
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _env_vars_driver_bound: None,
) -> None:
    """Quickstart Step 1: set ``LOG_LEVEL=debug`` at deployment scope and
    assert the entry reaches every container's ``env:`` block.
    """
    deployment_id = env_vars_deployment["deployment_id"]
    namespace = env_vars_deployment["namespace"]

    await scenario_driver.update_deployment(
        deployment_id=deployment_id,
        config={"env_vars": {"LOG_LEVEL": "debug"}},
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    dep = await _wait_for_pod_template(
        vcluster,
        namespace=namespace,
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=lambda d: any(
            entry.name == "LOG_LEVEL" and entry.value == "debug"
            for container in d.spec.template.spec.containers or []
            for entry in container.env or []
        ),
        description="LOG_LEVEL=debug to land on every container",
    )

    envs = _container_envs(dep)
    assert {"name": "LOG_LEVEL", "value": "debug"} in envs

    # FR-014a (010-driver-env-var-consumption): chart-default env entries
    # MUST be preserved alongside operator-set ones. The
    # ``STYRMIN_CHART_DEFAULT`` marker is sourced from the simple-app
    # chart's ``values.yaml`` and rendered by the chart's own
    # ``deployment.yaml`` template (see
    # ``driver/examples/simple-app/src/helm/``). DO NOT remove the marker
    # from the chart without updating this assertion; the marker is the
    # load-bearing assertion vs 008's broken behaviour where chart-default
    # entries were clobbered by the post-render injection layer.
    chart_default_names = {entry["name"] for entry in envs}
    assert "STYRMIN_CHART_DEFAULT" in chart_default_names, (
        "chart-default env entry was clobbered by env-vars consumption — "
        "the platform must NOT modify chart-rendered env entries (FR-014a / "
        f"SC-002). Observed env entries on the simple-app container: {envs}"
    )


# ---------------------------------------------------------------------------
# US2 — Environment-scoped baseline env vars (T037 / Quickstart Step 2)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def env_vars_second_deployment(
    env_vars_environment: dict,
    env_vars_deployment: dict,  # noqa: ARG001 — force fixture ordering
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    """Second deployment in the same environment — used to assert that an
    environment-scope env var propagates to a peer deployment that has no
    deployment-level env vars set of its own (FR-001 / Quickstart Step 2).
    """
    driver, _ = session_scenario_driver
    # Both deployments in this module share `env_vars_environment` and use the
    # `simple-app` driver, which declares a service named `simple-app`. The
    # platform enforces service-name uniqueness within an environment, so the
    # second deployment must rename its service (see also
    # `test_pod_scheduling.py::scheduling_second_deployment` for the same
    # pattern, and `conftest.py::scenario_environment` for the rationale).
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=env_vars_environment["environment_id"],
        name="env-vars-b",
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": "simple-app-b"}
        ],
    )
    deployment = await driver.wait_for_deployment_running(deployment_id=deployment.id)
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


@pytest.mark.api_only(
    reason=(
        # 011/US4 audit (FR-015): the second half of this scenario calls
        # ``scenario_driver.update_deployment`` with an env_vars override
        # which the UI driver rejects (scheduling-only); no deployment-
        # detail env-vars editor exists yet.
        "Drives scenario_driver.update_deployment with env_vars in the "
        "deployment-level override step; the UI driver only accepts "
        "the 'scheduling' sub-tree today."
    )
)
@pytest.mark.ci
async def test_us2_environment_level_env_var_propagates_to_all_deployments(
    env_vars_environment: dict,
    env_vars_deployment: dict,
    env_vars_second_deployment: dict,
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    driver_mode: str,
    _env_vars_driver_bound: None,
) -> None:
    """Quickstart Step 2: set ``OTEL_EXPORTER_OTLP_ENDPOINT`` at the
    environment scope and assert every deployment in that environment
    receives the entry on its containers (FR-001 / FR-020).

    Then set a deployment-level override on one deployment and assert the
    divergence (FR-002 deepest-wins, per-key).
    """
    client: StyrminClient = env_vars_environment["client"]
    environment_id = env_vars_environment["environment_id"]
    deployment_a_id = env_vars_deployment["deployment_id"]
    deployment_a_namespace = env_vars_deployment["namespace"]
    deployment_b_id = env_vars_second_deployment["deployment_id"]
    deployment_b_namespace = env_vars_second_deployment["namespace"]

    # 1) Set an environment-scope env var. Both deployments must pick it up.
    from styrmin_sdk.graphql._generated.input_types import (
        EnvVarInput,
        UpdateEnvironmentInput,
    )

    await client.environments.update(
        environment_id=environment_id,
        input=UpdateEnvironmentInput(
            env_vars=[
                EnvVarInput(
                    name="OTEL_EXPORTER_OTLP_ENDPOINT",
                    value="https://otel.staging",
                )
            ],
        ),
    )
    # The two deployments may need to reconcile; their fixtures already
    # parked them in RUNNING. Wait until the env var lands on each. In
    # API mode wait in parallel — the task-worker reconciles them
    # concurrently. In UI mode wait_for_deployment_running drives
    # ``page.goto`` on the session-scoped Playwright Page; parallel calls
    # would race with ``net::ERR_ABORTED``, so fall back to serial.
    if driver_mode == "api":
        await asyncio.gather(
            scenario_driver.wait_for_deployment_running(
                deployment_id=deployment_a_id, timeout=RECONCILE_TIMEOUT_SECONDS
            ),
            scenario_driver.wait_for_deployment_running(
                deployment_id=deployment_b_id, timeout=RECONCILE_TIMEOUT_SECONDS
            ),
        )
    else:
        await scenario_driver.wait_for_deployment_running(
            deployment_id=deployment_a_id, timeout=RECONCILE_TIMEOUT_SECONDS
        )
        await scenario_driver.wait_for_deployment_running(
            deployment_id=deployment_b_id, timeout=RECONCILE_TIMEOUT_SECONDS
        )

    dep_a, dep_b = await asyncio.gather(
        _wait_for_pod_template(
            vcluster,
            namespace=deployment_a_namespace,
            label_selector="app.kubernetes.io/name=simple-app",
            predicate=lambda d: any(
                entry.name == "OTEL_EXPORTER_OTLP_ENDPOINT"
                and entry.value == "https://otel.staging"
                for container in d.spec.template.spec.containers or []
                for entry in container.env or []
            ),
            description=(
                "OTEL_EXPORTER_OTLP_ENDPOINT to land on deployment A from the "
                "environment scope"
            ),
        ),
        _wait_for_pod_template(
            vcluster,
            namespace=deployment_b_namespace,
            label_selector="app.kubernetes.io/name=simple-app",
            predicate=lambda d: any(
                entry.name == "OTEL_EXPORTER_OTLP_ENDPOINT"
                and entry.value == "https://otel.staging"
                for container in d.spec.template.spec.containers or []
                for entry in container.env or []
            ),
            description=(
                "OTEL_EXPORTER_OTLP_ENDPOINT to land on peer deployment B "
                "without any per-deployment env vars set"
            ),
        ),
    )

    envs_a = _container_envs(dep_a)
    envs_b = _container_envs(dep_b)
    assert {
        "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
        "value": "https://otel.staging",
    } in envs_a
    assert {
        "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
        "value": "https://otel.staging",
    } in envs_b

    # 2) Override on deployment A only. Deployment B keeps the env value.
    await scenario_driver.update_deployment(
        deployment_id=deployment_a_id,
        config={"env_vars": {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.local"}},
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_a_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    dep_a_overridden = await _wait_for_pod_template(
        vcluster,
        namespace=deployment_a_namespace,
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=lambda d: any(
            entry.name == "OTEL_EXPORTER_OTLP_ENDPOINT"
            and entry.value == "https://otel.local"
            for container in d.spec.template.spec.containers or []
            for entry in container.env or []
        ),
        description=(
            "deployment-level override to win on deployment A "
            "(FR-002 per-key deepest-wins)"
        ),
    )
    envs_a_after = _container_envs(dep_a_overridden)
    assert {
        "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
        "value": "https://otel.local",
    } in envs_a_after
    # The environment-scope value must NOT linger on deployment A's pods.
    assert {
        "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
        "value": "https://otel.staging",
    } not in envs_a_after

    # Re-read deployment B and confirm it still carries the env-scope value.
    dep_b_after = await _wait_for_pod_template(
        vcluster,
        namespace=deployment_b_namespace,
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=lambda d: any(
            entry.name == "OTEL_EXPORTER_OTLP_ENDPOINT"
            and entry.value == "https://otel.staging"
            for container in d.spec.template.spec.containers or []
            for entry in container.env or []
        ),
        description=(
            "deployment B still serves the environment-scope value after "
            "deployment A's per-key override"
        ),
    )
    envs_b_after = _container_envs(dep_b_after)
    assert {
        "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
        "value": "https://otel.staging",
    } in envs_b_after


# ---------------------------------------------------------------------------
# US3 — Per-component scoping with deepest-wins precedence (T046 / Step 3)
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        # 011/US4 audit (FR-015): drives
        # scenario_driver.update_deployment with both env_vars and
        # per-component env_vars; the UI driver only accepts the
        # 'scheduling' sub-tree, and per-component env_var editing has
        # no UI surface today.
        "Drives scenario_driver.update_deployment with env_vars and "
        "per-component env_vars; the UI driver only accepts the "
        "'scheduling' sub-tree today, and there is no per-component "
        "env-vars editor in the frontend."
    )
)
@pytest.mark.ci
async def test_us3_per_component_env_var_overrides_deployment_level(
    env_vars_environment: dict,
    env_vars_deployment: dict,
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _env_vars_driver_bound: None,
) -> None:
    """Quickstart Step 3: deployment-level + per-component env vars on a
    multi-component driver. The ``server`` component inherits the
    deployment-level ``LOG_LEVEL=info``; the ``database`` component
    overrides ``LOG_LEVEL=debug`` and adds ``DB_POOL_SIZE=5`` only to its
    own pods. Asserts FR-002 (deepest-wins) and that peer components are
    unaffected by another component's block.
    """
    deployment_id = env_vars_deployment["deployment_id"]
    namespace = env_vars_deployment["namespace"]

    # Reset the environment-scope OTEL endpoint so it doesn't pollute the
    # baseline assertions (US2's earlier test left it set).
    await scenario_driver.update_deployment(
        deployment_id=deployment_id,
        config={
            "env_vars": {"LOG_LEVEL": "info"},
            "components": {
                "database": {
                    "env_vars": {"LOG_LEVEL": "debug", "DB_POOL_SIZE": "5"},
                }
            },
        },
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    # ``server`` pods carry LOG_LEVEL=info inherited from the deployment
    # scope and must NOT carry DB_POOL_SIZE.
    server_dep = await _wait_for_pod_template(
        vcluster,
        namespace=namespace,
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=lambda d: any(
            entry.name == "LOG_LEVEL" and entry.value == "info"
            for container in d.spec.template.spec.containers or []
            for entry in container.env or []
        ),
        description="LOG_LEVEL=info to land on server pods (deployment scope)",
    )
    server_envs = _container_envs(server_dep)
    server_names = {entry["name"] for entry in server_envs}
    assert {"name": "LOG_LEVEL", "value": "info"} in server_envs
    assert "DB_POOL_SIZE" not in server_names, (
        "server pods must not receive component-scoped env vars meant for database"
    )

    # ``database`` pods override LOG_LEVEL and gain DB_POOL_SIZE.
    database_dep = await _wait_for_pod_template(
        vcluster,
        namespace=namespace,
        label_selector="app.kubernetes.io/name=postgresql",
        predicate=lambda d: any(
            entry.name == "LOG_LEVEL" and entry.value == "debug"
            for container in d.spec.template.spec.containers or []
            for entry in container.env or []
        ),
        description=(
            "LOG_LEVEL=debug to land on database pods via component scope "
            "(FR-002 deepest-wins)"
        ),
    )
    database_envs = _container_envs(database_dep)
    assert {"name": "LOG_LEVEL", "value": "debug"} in database_envs
    assert {"name": "DB_POOL_SIZE", "value": "5"} in database_envs
    # The deployment-scope LOG_LEVEL=info must NOT linger on database pods.
    assert {"name": "LOG_LEVEL", "value": "info"} not in database_envs


# ---------------------------------------------------------------------------
# US4 — Driver-side env var documentation surfaced via GraphQL (T055 / Step 5)
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        # 011/US4 audit (FR-015): pure GraphQL read of
        # ApplicationDriverVersion.envVars; no scenario_driver mutation,
        # no UI surface to drive (the driver-detail page does not yet
        # render the env-vars docs). The [ui-chromium] variant would
        # only re-run the same SDK call without exercising any UI.
        "Pure GraphQL read of ApplicationDriverVersion.envVars (no "
        "scenario_driver mutation); the driver-detail page does not "
        "render env-var docs today, so there is no UI surface to drive."
    )
)
@pytest.mark.ci
async def test_us4_driver_env_var_docs_surfaced_via_graphql(
    styrmin_resources: dict,
) -> None:
    """Quickstart Step 5: query the driver detail and assert the seeded
    ``spec.env_vars`` block (one deployment-level + one component-level
    entry, see ``driver/examples/simple-app/driver.styrmin.yml``) is
    returned with correct ``level`` / ``components`` per
    :class:`DriverEnvVarDoc` (FR-018).

    Drives the raw GraphQL transport because the SDK exposes no high-level
    ``get_driver`` helper today; mirrors the pattern in
    ``test_pod_scheduling.py``.
    """
    client: StyrminClient = styrmin_resources["client"]
    driver_id = styrmin_resources["driver_id"]
    raw = await client._transport.execute(
        load_query("get_driver_env_var_docs"),
        {"applicationDriverId": str(driver_id)},
    )
    assert "errors" not in raw, raw
    versions = raw["data"]["applicationDriver"]["versions"]
    assert len(versions) >= 1
    # The fixture loads exactly one version of the simple-app driver.
    docs = versions[0]["envVars"]
    by_name = {d["name"]: d for d in docs}
    assert "LOG_LEVEL" in by_name
    assert "DB_POOL_SIZE" in by_name

    log_level = by_name["LOG_LEVEL"]
    assert log_level["level"] == "DEPLOYMENT"
    assert log_level["components"] == []
    assert "log verbosity" in log_level["description"].lower()

    db_pool = by_name["DB_POOL_SIZE"]
    assert db_pool["level"] == "COMPONENT"
    assert db_pool["components"] == ["database"]
    assert "pool size" in db_pool["description"].lower()


# ---------------------------------------------------------------------------
# US5 — Visible orphan tracking across driver upgrades (T061 / Step 6)
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Requires a second simple-app driver version that renames or removes "
        "a component (e.g. ``database`` → ``db``) so the per-component env "
        "var block becomes orphaned across the upgrade. The current fixture "
        "(``simple_app_image_v2``) only ships an application-code bump and "
        "keeps the component map identical, so the orphan transition cannot "
        "be exercised end-to-end. Tracked alongside the multi-version driver "
        "fixture work — once a renamed-component driver version exists, "
        "remove this skip and run the scenario as written below."
    )
)
@pytest.mark.api_only(
    reason=(
        # 011/US4 audit (FR-015): currently @pytest.mark.skip'd. When
        # unskipped, the test will drive scenario_driver.update_deployment
        # with per-component env_vars (no UI surface) plus
        # scenario_driver.upgrade_deployment, and assert on
        # componentEnvVars.isOrphaned / timeline.contextDiff GraphQL
        # fields — neither has a UI surface today.
        "Drives scenario_driver.update_deployment with per-component "
        "env_vars plus an upgrade, then asserts on the "
        "componentEnvVars.isOrphaned and timeline.contextDiff GraphQL "
        "shapes — neither has a UI surface today."
    )
)
@pytest.mark.ci
async def test_us5_orphan_visible_across_driver_upgrade(
    env_vars_environment: dict,
    env_vars_deployment: dict,
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _env_vars_driver_bound: None,
    simple_app_image_v2: str,  # noqa: ARG001 — builds the renamed-component v2 image
) -> None:
    """Quickstart Step 6: upgrade a deployment to a driver version whose
    component map renames the ``database`` component (e.g. to ``db``).

    Asserts (FR-029..FR-033):

    1. ``Deployment.componentEnvVars`` lists the leftover ``database`` block
       with ``isOrphaned: true`` after the upgrade settles.
    2. The renamed component's pods do NOT carry the orphaned env vars
       (post-010, the resolver does not produce a per-component dict for
       components the current driver no longer declares, so the driver's
       values template has nothing to render — see ADR-013).
    3. ``Deployment.timeline.contextDiff`` records the orphan transition
       once on the upgrade Task entry.
    """
    deployment_id = env_vars_deployment["deployment_id"]
    namespace = env_vars_deployment["namespace"]
    client: StyrminClient = env_vars_environment["client"]

    # 1) Set a per-component env var on ``database`` (live in v0.1.0).
    await scenario_driver.update_deployment(
        deployment_id=deployment_id,
        config={
            "components": {
                "database": {
                    "env_vars": {"DB_POOL_SIZE": "5", "DB_LOG_LEVEL": "debug"},
                },
            },
        },
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    # 2) Upgrade to a driver version that renames ``database`` → ``db``.
    #    The version string here matches the future renamed-component
    #    fixture; update both when the fixture lands.
    await scenario_driver.upgrade_deployment(
        deployment_id=deployment_id, version="0.3.0"
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    # 3) Query ``componentEnvVars`` — the ``database`` block must surface
    #    as orphaned with the stored values intact.
    raw = await client._transport.execute(
        load_query("get_deployment_component_env_vars_full"),
        {"deploymentId": deployment_id},
    )
    assert "errors" not in raw, raw
    rows = {
        row["component"]: row for row in raw["data"]["deployment"]["componentEnvVars"]
    }
    assert "database" in rows, rows
    database = rows["database"]
    assert database["isOrphaned"] is True
    db_pairs = {ev["name"]: ev["value"] for ev in database["envVars"]}
    assert db_pairs == {"DB_POOL_SIZE": "5", "DB_LOG_LEVEL": "debug"}

    # 4) The renamed component's pods must NOT carry the orphaned values.
    db_dep = await _wait_for_pod_template(
        vcluster,
        namespace=namespace,
        # The new driver version uses ``app.kubernetes.io/name=db`` for
        # the renamed component (mirrors driver naming convention).
        label_selector="app.kubernetes.io/name=db",
        predicate=lambda d: True,  # any pod template snapshot
        description="renamed db component pods to roll out after upgrade",
    )
    db_envs = _container_envs(db_dep)
    db_names = {entry["name"] for entry in db_envs}
    assert "DB_POOL_SIZE" not in db_names, (
        "orphaned env vars must NOT leak onto renamed component's pods"
    )
    assert "DB_LOG_LEVEL" not in db_names

    # 5) Timeline must record the orphan transition exactly once on the
    #    upgrade Task. ``contextDiff`` is the existing machinery — no new
    #    event type for orphans.
    raw_timeline = await client._transport.execute(
        load_query("get_deployment_timeline_context_diff"),
        {"deploymentId": deployment_id},
    )
    assert "errors" not in raw_timeline, raw_timeline
    entries = raw_timeline["data"]["deploymentTimeline"]
    upgrade_entries = [
        e
        for e in entries
        if e.get("applicationVersion") == "0.3.0" and e.get("contextDiff") is not None
    ]
    # Exactly one upgrade Task carries a context_diff that records the
    # orphan transition (subsequent reconciles share the upgraded context
    # and therefore have no diff).
    assert len(upgrade_entries) == 1, upgrade_entries
    diff_paths = {
        change["path"] for change in upgrade_entries[0]["contextDiff"]["changes"]
    }
    # The orphan transition manifests as a path change touching the
    # ``components.database.env_vars`` slot (the diff machinery surfaces
    # the operator-set block as removed/orphaned across the upgrade).
    assert any("database" in p and "env_vars" in p for p in diff_paths), (
        f"context_diff did not record the orphan transition: {diff_paths}"
    )
