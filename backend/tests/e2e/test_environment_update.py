"""End-to-end coverage for environment-config update + fanout (009 + 011).

Drives the user-facing path for ``updateEnvironment``: the env-config row
is persisted, every active deployment receives a redeploy Task, and the
new env-config slice lands on the rendered pod spec on the vcluster.

Marker landscape (audited under 011/US4):

* US1 fanout + US4 form scenarios use the dual-entrypoint
  ``scenario_driver.update_environment_via_form`` and run under both
  ``[api-chromium]`` and ``[ui-chromium]`` — the parametrisation IS the
  parity check between the SDK round-trip path and the form's
  ``buildFullReplacementInput`` path.
* The remaining ``api_only`` markers below tag scenarios that have no
  dual-entrypoint analogue: failure-isolation needs a typed
  ``SchedulingInput`` the v1 form cannot drive, and the rejection test
  asserts on a typed SDK exception that the UI form would only surface
  as an inline error string.

Scenarios:

* ``test_us1_environment_update_fans_out_to_all_deployments`` — Quickstart
  Steps 1-3: an ``updateEnvironment`` call setting a single env var on
  three peer deployments propagates to each deployment's container[0]
  ``env`` block within ``RECONCILE_TIMEOUT_SECONDS``, and each
  deployment's timeline gains a fresh entry whose ``contextDiff``
  records the env-config change (FR-006 / FR-010 / FR-023).
* ``test_us1_environment_update_failure_isolation`` — Quickstart Step 7:
  one deployment's chart fails to render under a specific scheduling
  override; the env-config row still persists, the healthy peer
  converges, and the failing deployment's timeline records a failed
  Task. Currently skipped pending a multi-driver fixture (see body for
  unskip path).
"""

from __future__ import annotations

import uuid
from typing import Any, AsyncGenerator

import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk.graphql._generated.input_types import (
    EnvVarInput,
    SchedulingInput,
    UpdateEnvironmentInput,
)

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.helpers.workloads import _wait_for_pod_template

pytestmark = [
    pytest.mark.shard_mutation_large,
]

RECONCILE_TIMEOUT_SECONDS = 480.0


def _container_zero_envs(dep: Any) -> list[dict[str, str]]:
    """Return the ``env`` entries on ``container[0]`` only (per the
    post-008 narrowing — env var injection lands on the first container).
    """
    containers = dep.spec.template.spec.containers or []
    if not containers:
        return []
    container = containers[0]
    return [
        {
            "name": entry.name,
            "value": entry.value if entry.value is not None else "",
        }
        for entry in container.env or []
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def env_update_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    """Empty environment that the US1 fanout test owns end-to-end."""
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"env-update-e2e-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {
        "environment_id": str(env.id),
        "client": client,
    }


@pytest.fixture(scope="module")
async def env_update_three_deployments(
    env_update_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> list[dict]:
    """Three peer ``simple-app`` deployments parked in RUNNING — the
    fanout target set for the US1 headline scenario.
    """
    driver, _ = session_scenario_driver
    deployments: list[dict] = []
    # All three deployments share `env_update_environment` and use the
    # `simple-app` driver, which declares a service named `simple-app`. The
    # platform enforces service-name uniqueness within an environment, so each
    # deployment must rename its service (see `test_pod_scheduling.py` for the
    # same pattern).
    for suffix in ("a", "b", "c"):
        deployment = await driver.create_deployment(
            driver="simple-app",
            version="0.1.0",
            environment_id=env_update_environment["environment_id"],
            name=f"env-update-{suffix}",
            service_name_overrides=[
                {
                    "driverServiceName": "simple-app",
                    "overrideName": f"simple-app-{suffix}",
                }
            ],
        )
        deployment = await driver.wait_for_deployment_running(
            deployment_id=deployment.id
        )
        deployments.append(
            {
                "deployment_id": str(deployment.id),
                "namespace": f"styrmin-{deployment.id}",
                "kubeconfig_path": vcluster["kubeconfig_path"],
            }
        )
    return deployments


@pytest.fixture
def _env_update_driver_bound(
    env_update_environment: dict,
    env_update_three_deployments: list[dict],  # noqa: ARG001 — force ordering
    scenario_driver: ScenarioDriver,
) -> None:
    scenario_driver.attach_to_deployment(
        environment_id=env_update_environment["environment_id"]
    )


# ---------------------------------------------------------------------------
# T025 — US1 headline (Quickstart Steps 1-3)
# ---------------------------------------------------------------------------


@pytest.mark.ci
async def test_us1_environment_update_fans_out_to_all_deployments(
    env_update_environment: dict,
    env_update_three_deployments: list[dict],
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _env_update_driver_bound: None,
) -> None:
    """Quickstart Steps 1-3: ``updateEnvironment`` with a single env var
    propagates to every active deployment in the environment.

    * Set ``OTEL_EXPORTER_OTLP_ENDPOINT`` at the environment scope.
    * Wait for each deployment to reconcile within
      ``RECONCILE_TIMEOUT_SECONDS``.
    * Assert every deployment's ``container[0]`` carries the new env entry.
    * Assert each deployment's timeline received a fresh entry whose
      ``contextDiff`` records the env-config change (FR-023).
    """
    client: StyrminClient = env_update_environment["client"]
    environment_id = env_update_environment["environment_id"]
    target_value = "https://otel.staging"

    # Snapshot timeline length per deployment BEFORE the fanout — so we
    # can assert "exactly one new entry" instead of just "non-empty".
    pre_timeline_lengths: dict[str, int] = {}
    for dep in env_update_three_deployments:
        timeline = await client.deployments.get_timeline(
            deployment_id=dep["deployment_id"]
        )
        pre_timeline_lengths[dep["deployment_id"]] = len(timeline)

    # Use the dual-entrypoint scenario_driver method so the test runs
    # under both ``[api-chromium]`` (typed SDK round-trip) and
    # ``[ui-chromium]`` (Configuration tab + EnvVarsForm) variants
    # automatically — the parametrisation IS the parity check per
    # 011-env-config-input-hardening / US4.
    await scenario_driver.update_environment_via_form(
        environment_id=environment_id,
        env_vars={"OTEL_EXPORTER_OTLP_ENDPOINT": target_value},
    )

    # Each deployment must reconcile to RUNNING with the new env entry on
    # container[0] of its rendered pod template.
    for dep in env_update_three_deployments:
        await scenario_driver.wait_for_deployment_running(
            deployment_id=dep["deployment_id"], timeout=RECONCILE_TIMEOUT_SECONDS
        )
        rendered = await _wait_for_pod_template(
            vcluster,
            namespace=dep["namespace"],
            label_selector="app.kubernetes.io/name=simple-app",
            predicate=lambda d: any(
                entry.name == "OTEL_EXPORTER_OTLP_ENDPOINT"
                and entry.value == target_value
                for container in (d.spec.template.spec.containers or [])[:1]
                for entry in container.env or []
            ),
            description=(
                f"OTEL_EXPORTER_OTLP_ENDPOINT to land on container[0] of "
                f"deployment {dep['deployment_id']}"
            ),
        )
        envs = _container_zero_envs(rendered)
        assert {
            "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
            "value": target_value,
        } in envs, (
            f"deployment {dep['deployment_id']} did not pick up the env "
            f"var on container[0] — saw {envs}"
        )

    # Each deployment's timeline gained at least one new entry whose
    # ``contextDiff`` mentions the env-config change. We don't lock the
    # exact count to "+1" because the reconciliation loop may produce
    # follow-up entries (status-only) — what we DO lock is that a fresh
    # entry exists with the new env var in its diff.
    for dep in env_update_three_deployments:
        timeline_after = await client.deployments.get_timeline(
            deployment_id=dep["deployment_id"]
        )
        assert len(timeline_after) > pre_timeline_lengths[dep["deployment_id"]], (
            f"deployment {dep['deployment_id']} timeline did not grow after "
            "the env-config fanout"
        )
        # At least one new entry must record the env-config change in
        # its context diff — the additions must reference the env var
        # name we set.
        # Timeline is ordered newest-first (see
        # ``TaskRepository.find_by_deployment``), so the entries added by
        # the fanout sit at the front of the list — not at the end.
        new_count = len(timeline_after) - pre_timeline_lengths[dep["deployment_id"]]
        new_entries = timeline_after[:new_count]
        env_var_in_diff = False
        for entry in new_entries:
            ctx_diff = getattr(entry, "context_diff", None)
            if ctx_diff is None:
                continue
            changes = getattr(ctx_diff, "changes", None) or []
            for change in changes:
                path = getattr(change, "path", "") or ""
                new_value = getattr(change, "new_value", None)
                # The diff path contains the env var name when ``env_vars``
                # already existed pre-update (the recursive dict diff
                # extends the path with the new key). When ``env_vars`` was
                # absent pre-update it is recorded as a single
                # ``added`` change at ``instance.config.env_vars`` whose
                # ``new_value`` is the whole env-vars dict — match either
                # shape, plus the legacy "value-substring" form.
                if "OTEL_EXPORTER_OTLP_ENDPOINT" in path:
                    env_var_in_diff = True
                    break
                if isinstance(new_value, dict) and (
                    "OTEL_EXPORTER_OTLP_ENDPOINT" in new_value
                    or target_value in new_value.values()
                ):
                    env_var_in_diff = True
                    break
                if isinstance(new_value, str) and target_value in new_value:
                    env_var_in_diff = True
                    break
            if env_var_in_diff:
                break
        assert env_var_in_diff, (
            f"deployment {dep['deployment_id']} timeline grew but no new "
            "entry carries the env-config change in its contextDiff"
        )


# ---------------------------------------------------------------------------
# T026 — US1 failure isolation (Quickstart Step 7)
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Needs a multi-driver fixture or a chart-render-failure path: the "
        "test asserts that an env-config update with a scheduling override "
        "fails on deployment B (chart can't render) while deployment A "
        "converges, and that A/B/the env-config row are properly isolated. "
        "Body fully written so unskipping is a one-line change once the "
        "fixture lands. Tracking issue: see tasks T026 in "
        "specs/009-environment-update/tasks.md."
    )
)
@pytest.mark.api_only(
    reason=(
        # 011/US4 audit (FR-015): kept api_only because this scenario submits a
        # ``SchedulingInput`` override that the v1 ``EnvVarsForm`` cannot drive
        # (the form blocks submission outright when persisted ``scheduling``
        # is non-empty — see ``detectNestedOverridesBlock`` in
        # EnvironmentConfigurationTab). A ``[ui-chromium]`` variant would
        # have to bypass the form block to reproduce this scenario, which
        # would defeat the purpose of the dual-entrypoint test.
        "Submits a SchedulingInput override that the v1 EnvVarsForm "
        "cannot edit (the form's nested-overrides block trips on "
        "non-empty scheduling). No UI surface drives this flow today; "
        "the [ui-chromium] variant would have to bypass the form block."
    )
)
@pytest.mark.ci
async def test_us1_environment_update_failure_isolation(
    env_update_environment: dict,
    env_update_three_deployments: list[dict],
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _env_update_driver_bound: None,
) -> None:
    """Quickstart Step 7: env-config fanout failure isolation.

    Setup: an environment with two deployments A and B. Submit
    ``updateEnvironment`` with a scheduling override that B's chart
    cannot render plus an env var that A's chart can.

    Assertions:
    * The env-config row on the environment persists with the submitted
      values (FR-009a — committed before fanout).
    * Deployment A reconciles to RUNNING with the new env var on its
      ``container[0]`` (peer-isolation invariant).
    * Deployment B's timeline records a failed Task — the failure must
      not propagate to peer A or roll back the env-config row.
    """
    client: StyrminClient = env_update_environment["client"]
    environment_id = env_update_environment["environment_id"]
    deployment_a = env_update_three_deployments[0]
    deployment_b = env_update_three_deployments[1]

    # A scheduling override that A accepts and B's chart rejects on
    # render — the exact value depends on the multi-driver fixture; the
    # placeholder below is the shape the test will use once the fixture
    # exists.
    bad_override = SchedulingInput(runtime_class="nonexistent")
    typed_input = UpdateEnvironmentInput(
        env_vars=[
            EnvVarInput(
                name="OTEL_EXPORTER_OTLP_ENDPOINT",
                value="https://otel.staging",
            )
        ],
        scheduling=bad_override,
    )

    await client.environments.update(
        environment_id=environment_id,
        input=typed_input,
    )

    # The env-config row persists despite the per-deployment failure.
    fresh_env = await client.environments.get(environment_id=environment_id)
    assert fresh_env.config == {
        "env_vars": {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.staging"},
        "scheduling": {"runtime_class": "nonexistent"},
    }

    # A converges with the new env var.
    await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment_a["deployment_id"],
        timeout=RECONCILE_TIMEOUT_SECONDS,
    )
    rendered_a = await _wait_for_pod_template(
        vcluster,
        namespace=deployment_a["namespace"],
        label_selector="app.kubernetes.io/name=simple-app",
        predicate=lambda d: any(
            entry.name == "OTEL_EXPORTER_OTLP_ENDPOINT"
            for container in (d.spec.template.spec.containers or [])[:1]
            for entry in container.env or []
        ),
        description="deployment A to converge with new env var (peer isolation)",
    )
    envs_a = _container_zero_envs(rendered_a)
    assert {
        "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
        "value": "https://otel.staging",
    } in envs_a

    # B's timeline records a failed Task.
    timeline_b = await client.deployments.get_timeline(
        deployment_id=deployment_b["deployment_id"]
    )
    failed_tasks = [
        entry
        for entry in timeline_b
        if getattr(entry.task, "status", "").upper() == "FAILED"
    ]
    assert failed_tasks, (
        "deployment B should have logged a failed Task in its timeline; "
        "found no FAILED entries"
    )


# ---------------------------------------------------------------------------
# T047 — typed-input rejection scenario (Quickstart Step 6)
# ---------------------------------------------------------------------------


@pytest.mark.api_only(
    reason=(
        # 011/US4 audit (FR-015): kept api_only because the assertion
        # binds to ``OperationFailedError.typename`` — a typed SDK
        # exception. The UI form's client-side validator catches
        # ``"1invalid"`` before any GraphQL call, so the
        # ``[ui-chromium]`` variant cannot exercise the server-side
        # ``INVALID_ENV_VAR_NAME`` extension code that is the test's
        # contract.
        "Asserts on the OperationFailedError.typename surfaced by the "
        "GraphQL extensions code; the UI form's client-side regex "
        "rejects '1invalid' before any mutation reaches the server."
    )
)
@pytest.mark.ci
async def test_us2_environment_update_invalid_env_var_name_rejected(
    env_update_environment: dict,
) -> None:
    """Quickstart Step 6: an ``updateEnvironment`` with an invalid env var
    name (regex violation) is rejected with
    ``extensions.code = "INVALID_ENV_VAR_NAME"`` (FR-006 / SC-003).

    The regenerated SDK surfaces the error as
    :class:`styrmin_sdk.exceptions.OperationFailedError` whose
    ``typename`` carries the GraphQL extensions code; we assert directly
    on that to keep the contract pinned.
    """
    from styrmin_sdk.exceptions import OperationFailedError

    client: StyrminClient = env_update_environment["client"]
    environment_id = env_update_environment["environment_id"]

    with pytest.raises(OperationFailedError) as exc_info:
        await client.environments.update(
            environment_id=environment_id,
            input=UpdateEnvironmentInput(
                env_vars=[EnvVarInput(name="1invalid", value="y")],
            ),
        )
    assert exc_info.value.typename == "INVALID_ENV_VAR_NAME"


# ---------------------------------------------------------------------------
# T061 — US4 form E2E (Quickstart Step 9)
# ---------------------------------------------------------------------------


@pytest.mark.ci
async def test_us4_env_vars_form_redeploys_environment(
    env_update_environment: dict,
    env_update_three_deployments: list[dict],
    vcluster: dict,
    scenario_driver: ScenarioDriver,
    _env_update_driver_bound: None,
) -> None:
    """Quickstart Step 9: an operator edits env vars from the environment
    detail page, confirms the redeploy, and each affected deployment's
    pod template eventually carries the new env entry on container[0].

    Drives the dual-entrypoint
    ``scenario_driver.update_environment_via_form`` (011 / US4): under
    ``[ui-chromium]`` the driver navigates the Configuration tab, fills
    the env-vars form, and confirms the redeploy dialog; under
    ``[api-chromium]`` the driver round-trips the existing config
    through ``EnvironmentConfig.model_validate`` and submits a typed
    ``UpdateEnvironmentInput``. Both sides must reach the same persisted
    state and trigger the same per-deployment fanout — the
    parametrisation IS the parity check (critique E1+E2).
    """
    environment_id = env_update_environment["environment_id"]

    await scenario_driver.update_environment_via_form(
        environment_id=environment_id,
        env_vars={"LOG_LEVEL": "debug"},
    )

    # Each deployment converges to RUNNING with the new env entry on
    # container[0]. This reuses the same ``_wait_for_pod_template``
    # helper the API/SDK fanout test uses so the assertion shape stays
    # uniform across both variants.
    for dep in env_update_three_deployments:
        await scenario_driver.wait_for_deployment_running(
            deployment_id=dep["deployment_id"], timeout=RECONCILE_TIMEOUT_SECONDS
        )
        rendered = await _wait_for_pod_template(
            vcluster,
            namespace=dep["namespace"],
            label_selector="app.kubernetes.io/name=simple-app",
            predicate=lambda d: any(
                entry.name == "LOG_LEVEL" and entry.value == "debug"
                for container in (d.spec.template.spec.containers or [])[:1]
                for entry in container.env or []
            ),
            description=(
                f"LOG_LEVEL=debug to land on container[0] of "
                f"deployment {dep['deployment_id']}"
            ),
        )
        envs = _container_zero_envs(rendered)
        assert {"name": "LOG_LEVEL", "value": "debug"} in envs
