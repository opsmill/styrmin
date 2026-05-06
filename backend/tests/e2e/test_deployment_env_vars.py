"""End-to-end coverage for deployment environment variables (008 / US1+).

Drives the full user-facing path: ``updateDeployment(config: { env_vars: ... })``
(SDK / GraphQL) → server reconciler → FluxCD HelmRelease post-renderers →
rendered pod spec on the vcluster. Asserts by reading the resulting
``apps/v1.Deployment`` back from the vcluster API server and inspecting
the container ``env`` block.

US1 scenario corresponds to Quickstart Step 1: deploy ``simple-app``, set
``LOG_LEVEL=debug`` on the deployment, observe the env entry on every
container's ``env:`` list. The flow is API/SDK-only (no UI page navigation),
hence the ``api_only`` marker per AGENTS.md "Dual-entrypoint scope".
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncGenerator, Callable

import pytest
from kubernetes_asyncio import client as kubeclient
from styrmin_sdk import StyrminClient

from tests.e2e.drivers import ScenarioDriver

RECONCILE_TIMEOUT_SECONDS = 480.0
RECONCILE_POLL_INTERVAL = 3.0


async def _wait_for_pod_template(
    vcluster: dict,
    *,
    namespace: str,
    label_selector: str,
    predicate: Callable[[Any], bool],
    description: str,
    timeout: float = RECONCILE_TIMEOUT_SECONDS,
) -> Any:
    apps = kubeclient.AppsV1Api(vcluster["api"])
    deadline = time.time() + timeout
    last_seen: str = "(no matching Deployments)"
    while time.time() < deadline:
        resp = await apps.list_namespaced_deployment(
            namespace=namespace, label_selector=label_selector
        )
        deployments = list(resp.items)
        for dep in deployments:
            try:
                if predicate(dep):
                    return dep
            except Exception:
                continue
        if deployments:
            last_seen = f"{len(deployments)} deployment(s) did not satisfy predicate"
        await asyncio.sleep(RECONCILE_POLL_INTERVAL)
    raise TimeoutError(
        f"Timed out waiting for {description} in namespace {namespace} "
        f"(selector={label_selector!r}): {last_seen}"
    )


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
        "API/SDK-only flow (Quickstart Step 1); no UI page navigation. "
        "The [ui-chromium] variant would just re-run the same SDK call."
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

    # Every container in the pod template should have received the entry
    # (FR-026 strategic-merge wildcard injection).
    for container in dep.spec.template.spec.containers or []:
        names = {entry.name for entry in container.env or []}
        assert "LOG_LEVEL" in names, (
            f"container {container.name!r} missing LOG_LEVEL env entry"
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
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=env_vars_environment["environment_id"],
        name="env-vars-b",
    )
    deployment = await driver.wait_for_deployment_running(deployment_id=deployment.id)
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


@pytest.mark.api_only(
    reason=(
        "API/SDK-only flow (Quickstart Step 2); no UI page navigation. "
        "The [ui-chromium] variant would just re-run the same SDK calls."
    )
)
@pytest.mark.ci
async def test_us2_environment_level_env_var_propagates_to_all_deployments(
    env_vars_environment: dict,
    env_vars_deployment: dict,
    env_vars_second_deployment: dict,
    vcluster: dict,
    scenario_driver: ScenarioDriver,
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
    await client.environments.update(
        environment_id=environment_id,
        config={"env_vars": {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.staging"}},
    )
    # The two deployments may need to reconcile; their fixtures already
    # parked them in RUNNING. Wait until the env var lands on each.
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_a_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_b_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )

    dep_a = await _wait_for_pod_template(
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
    )
    dep_b = await _wait_for_pod_template(
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
        "API/SDK-only flow (Quickstart Step 3); no UI page navigation. "
        "The [ui-chromium] variant would just re-run the same SDK call. "
        "The Step 4 negative case (UnknownComponentEnvVarError) is covered "
        "by the propagation test in test_env_vars_propagation.py since it "
        "exercises only the GraphQL mutation rejection path and does not "
        "require a real cluster."
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


_DRIVER_ENV_VAR_DOCS_QUERY = """
query GetDriverEnvVarDocs($applicationDriverId: UUID!) {
    applicationDriver(applicationDriverId: $applicationDriverId) {
        id
        name
        versions {
            id
            version
            envVars {
                name
                description
                level
                components
            }
        }
    }
}
"""


@pytest.mark.api_only(
    reason=(
        "API/SDK-only flow (Quickstart Step 5); the assertion is on the "
        "GraphQL response shape for ``ApplicationDriverVersion.envVars`` — "
        "no UI page navigation. The [ui-chromium] variant would just "
        "re-run the same SDK call."
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
        _DRIVER_ENV_VAR_DOCS_QUERY,
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
