"""E2E test for ``client.deployments.apply()`` create-then-update flow (US1).

Covers `specs/009-deployments-apply` User Story 1: a single resolved manifest
flowing through the SDK's `apply` method must create a fresh deployment on the
first call and switch to the update branch on the second call (returning
``action="updated"`` and a config that reflects the new manifest, replaced —
not merged).

Marked ``api_only`` because ``apply`` exposes no UI flow today; the
``[ui-chromium]`` variant would re-run the same SDK call. Re-evaluate once a
declarative-manifest UI lands (US-future).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import yaml
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminError
from styrmin_sdk.models.deployment_manifest import ResolvedManifest

from tests.e2e.drivers import ScenarioDriver

# Own shard: every test here is api_only and deploys fresh simple-apps, which
# made it the bulk of `general` (see `dev/guides/e2e-parallelism.md`).
pytestmark = [pytest.mark.ci, pytest.mark.shard_apply]


async def _create_apply_env(
    driver: ScenarioDriver,
    styrmin_resources: dict,
) -> str:
    env = await driver.create_environment(
        name=f"apply-e2e-{uuid.uuid4().hex[:8]}",
        cluster_id=styrmin_resources["cluster_id"],
        config={},
    )
    env_id = str(env.id)
    await driver.assign_bsl_to_environment(
        environment_id=env_id, bsl_id=styrmin_resources["bsl_id"]
    )
    return env_id


async def _drop_apply_env(client: StyrminClient, env_id: str) -> None:
    try:
        await client.environments.delete(environment_id=env_id)
    except StyrminError:
        pass


@pytest.fixture
async def apply_environment_id(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[str, None]:
    """Function-scoped fresh environment for apply E2E tests.

    Each test deploys ``simple-app``, which registers a per-env service named
    ``simple-app``. The shared ``scenario_environment_id`` already has that
    service registered (via ``deployed_simple_app`` and other session
    fixtures), and ``ResolvedManifest`` has no ``service_name_overrides``
    surface, so reusing the session env collides on
    ``ResourceAlreadyExistsError``. A fresh env per test is the simplest
    isolation that doesn't require expanding the manifest schema.
    """
    driver, client = session_scenario_driver
    env_id = await _create_apply_env(driver, styrmin_resources)
    try:
        yield env_id
    finally:
        await _drop_apply_env(client, env_id)


@pytest.fixture
async def apply_environment_id_secondary(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[str, None]:
    """Second fresh environment for tests that need two simple-app deployments.

    The batch test exercises ``apply_files`` on a directory containing two
    ``simple-app`` manifests. Both manifests would register the same
    per-env service name, so they must target distinct environments.
    """
    driver, client = session_scenario_driver
    env_id = await _create_apply_env(driver, styrmin_resources)
    try:
        yield env_id
    finally:
        await _drop_apply_env(client, env_id)


def _resolve_manifest_from_doc(doc: dict, path: Path) -> ResolvedManifest:
    """Round-trip a manifest doc through YAML and into a ``ResolvedManifest``.

    Mirrors what the SDK's ``apply_files`` does internally, so each test still
    exercises the "edit a YAML, apply it" loop while feeding the parsed result
    straight into ``apply()``.
    """
    path.write_text(yaml.safe_dump(doc))
    parsed = yaml.safe_load(path.read_text())
    return ResolvedManifest(
        name=parsed["metadata"]["name"],
        driver=parsed["spec"]["driver"],
        version=parsed["spec"]["version"],
        environment=parsed["spec"]["environment"],
        config=parsed["spec"].get("config", {}),
        parameters=parsed["spec"].get("parameters", {}),
        source_path=path,
    )


async def _wait_for_task_success(
    client: StyrminClient, deployment_id: str, task_id: str, timeout: float
) -> None:
    """Poll the timeline until ``task_id`` succeeds.

    ``Deployment.status`` is still ``running`` from before an update, so it
    cannot tell whether the update's reconcile has finished.
    """
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        timeline = await client.deployments.get_timeline(deployment_id)
        status = next(
            (e.task.status for e in timeline if str(e.task.id) == task_id), None
        )
        if status == "success":
            return
        assert status != "failed", f"task {task_id} failed"
        await asyncio.sleep(1)
    raise AssertionError(f"task {task_id} did not succeed in {timeout}s: {status!r}")


@pytest.mark.api_only(
    reason="apply has no UI flow; api/sdk and ui variants would re-run identical SDK calls",
)
async def test_apply_creates_updates_then_noops(
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    apply_environment_id: str,
    styrmin_resources: dict,  # noqa: ARG001 — transitive: cluster/BSL/driver loaded
    simple_app_image: str,  # noqa: ARG001 — ensures the image is built
    tmp_path: Path,
) -> None:
    """One deployment through the apply lifecycle: create, update, no-op.

    - Create from a manifest whose ``config.env_vars`` is a ``[{name, value}]``
      list: ``created``, persisted flattened to ``{name: value}`` (the create
      path used to reject the list shape).
    - Re-apply with a different config: ``updated`` on the same deployment,
      and the config is replaced, not merged (US1, ``contracts/sdk-apply.md``).
    - Re-apply the byte-identical manifest: ``unchanged``, no new task, and
      the active instance and status untouched (SC-001/002).
    """
    driver, client = session_scenario_driver

    # Target the environment by name, the way a user's manifest would.
    environment = await client.environments.get(environment_id=apply_environment_id)
    deployment_name = f"apply-e2e-{tmp_path.name[-8:]}"
    manifest_path = tmp_path / "deployment.yaml"
    manifest_doc = {
        "apiVersion": "styrmin/v1",
        "kind": "Deployment",
        "metadata": {"name": deployment_name},
        "spec": {
            "driver": "simple-app",
            "version": "0.1.0",
            "environment": environment.name,
            "config": {"env_vars": [{"name": "MY_ENV", "value": "value01"}]},
            "parameters": {},
        },
    }

    # --- Create ------------------------------------------------------------
    create_outcome = await client.deployments.apply(
        _resolve_manifest_from_doc(manifest_doc, manifest_path)
    )
    assert create_outcome.action == "created", (
        f"first apply should create the deployment, got action="
        f"{create_outcome.action!r} (reason={create_outcome.failure_reason!r})"
    )
    assert create_outcome.deployment_id is not None
    deployment_id = str(create_outcome.deployment_id)
    await driver.wait_for_deployment_running(deployment_id=deployment_id, timeout=300.0)

    created = await client.deployments.get_by_name(
        deployment_name, environment_id=apply_environment_id
    )
    assert created is not None
    assert created.config == {"env_vars": {"MY_ENV": "value01"}}, (
        f"env_vars list did not flatten/persist on create; got {created.config!r}"
    )

    # --- Update: the new config replaces the old one -----------------------
    new_config = {"ip_whitelist": ["10.0.0.0/8"]}
    manifest_doc["spec"]["config"] = new_config
    update_outcome = await client.deployments.apply(
        _resolve_manifest_from_doc(manifest_doc, manifest_path)
    )
    assert update_outcome.action == "updated", (
        f"second apply should update the existing deployment, got action="
        f"{update_outcome.action!r} (reason={update_outcome.failure_reason!r})"
    )
    assert str(update_outcome.deployment_id) == deployment_id, (
        "update should target the same deployment_id, not create a new one"
    )
    assert update_outcome.task_id is not None, "a real change must dispatch a task"
    await _wait_for_task_success(
        client, deployment_id, str(update_outcome.task_id), timeout=300.0
    )
    await driver.wait_for_deployment_running(deployment_id=deployment_id, timeout=300.0)

    refreshed = await client.deployments.get_by_name(
        deployment_name, environment_id=apply_environment_id
    )
    assert refreshed is not None
    assert refreshed.config == new_config, (
        f"deployment config was not replaced by the second apply; "
        f"expected {new_config!r}, got {refreshed.config!r}"
    )

    # --- No-op: the byte-identical manifest changes nothing ----------------
    before = await client.deployments.get(deployment_id)
    before_task_count = len(await client.deployments.get_timeline(deployment_id))
    assert before.application_instance is not None, (
        "a running deployment must have an active instance to compare against"
    )

    noop_outcome = await client.deployments.apply(
        _resolve_manifest_from_doc(manifest_doc, manifest_path)
    )
    assert noop_outcome.action == "unchanged", (
        f"re-applying an identical manifest must be a no-op, got action="
        f"{noop_outcome.action!r} (reason={noop_outcome.failure_reason!r})"
    )
    assert noop_outcome.task_id is None, (
        f"a no-op must not dispatch a reconcile task, got task_id="
        f"{noop_outcome.task_id!r}"
    )

    after = await client.deployments.get(deployment_id)
    after_task_count = len(await client.deployments.get_timeline(deployment_id))
    assert after.application_instance is not None
    assert after_task_count == before_task_count, (
        f"no-op re-apply must not create a reconcile task; task count went "
        f"{before_task_count} -> {after_task_count}"
    )
    assert str(after.application_instance.id) == str(before.application_instance.id), (
        "no-op re-apply must not move the active-instance pointer"
    )
    assert after.status == before.status, (
        f"no-op re-apply must not change deployment status; "
        f"{before.status!r} -> {after.status!r}"
    )


@pytest.mark.api_only(
    reason="apply has no UI flow; api/sdk and ui variants would re-run identical SDK calls",
)
async def test_apply_partial_change_dispatches_exactly_one_reconcile(
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    apply_environment_id: str,
    styrmin_resources: dict,  # noqa: ARG001 — transitive: cluster/BSL/driver loaded
    simple_app_image: str,  # noqa: ARG001 — ensures the 0.1.0 image is built
    simple_app_image_v2: str,  # noqa: ARG001 — ensures the 0.2.0 image is built
    tmp_path: Path,
) -> None:
    """A real partial change drives exactly one reconcile, not over/under-dispatch (SC-003).

    Baseline apply, then:
      - a config-only change → ``updated`` + exactly one new reconcile task;
      - a version-only change → ``updated`` + exactly one upgrade task, plus
        the tasks simple-app's ``upgrade`` action creates itself.

    Task count is read via the deployment timeline (one entry per ``Task``)
    once the dispatched task has succeeded. ``Deployment.status`` cannot be
    the wait point: it can read ``running`` mid-upgrade (#405).
    """
    driver, client = session_scenario_driver

    environment = await client.environments.get(environment_id=apply_environment_id)
    env_name = environment.name

    deployment_name = f"apply-partial-e2e-{tmp_path.name[-8:]}"
    manifest_doc = {
        "apiVersion": "styrmin/v1",
        "kind": "Deployment",
        "metadata": {"name": deployment_name},
        "spec": {
            "driver": "simple-app",
            "version": "0.1.0",
            "environment": env_name,
            "config": {},
            "parameters": {},
        },
    }
    manifest_path = tmp_path / "deployment.yaml"

    create_outcome = await client.deployments.apply(
        _resolve_manifest_from_doc(manifest_doc, manifest_path)
    )
    assert create_outcome.action == "created", (
        f"baseline apply should create the deployment, got "
        f"action={create_outcome.action!r} (reason={create_outcome.failure_reason!r})"
    )
    assert create_outcome.deployment_id is not None
    deployment_id = str(create_outcome.deployment_id)
    await driver.wait_for_deployment_running(deployment_id=deployment_id, timeout=300.0)

    baseline_task_count = len(await client.deployments.get_timeline(deployment_id))

    # --- Config-only change → exactly 1 new reconcile ----------------------
    manifest_doc["spec"]["config"] = {"ip_whitelist": ["10.0.0.0/8"]}
    config_outcome = await client.deployments.apply(
        _resolve_manifest_from_doc(manifest_doc, manifest_path)
    )
    assert config_outcome.action == "updated", (
        f"a config-only change must be an update, got "
        f"action={config_outcome.action!r} (reason={config_outcome.failure_reason!r})"
    )
    assert config_outcome.task_id is not None, "a real change must dispatch a task"
    await _wait_for_task_success(
        client, deployment_id, str(config_outcome.task_id), timeout=300.0
    )

    after_config_task_ids = {
        str(e.task.id) for e in await client.deployments.get_timeline(deployment_id)
    }
    assert len(after_config_task_ids) == baseline_task_count + 1, (
        f"a config-only change must dispatch exactly one reconcile; task count "
        f"went {baseline_task_count} -> {len(after_config_task_ids)}"
    )

    # --- Version-only change → exactly 1 upgrade ---------------------------
    manifest_doc["spec"]["version"] = "0.2.0"
    version_outcome = await client.deployments.apply(
        _resolve_manifest_from_doc(manifest_doc, manifest_path)
    )
    assert version_outcome.action == "updated", (
        f"a version-only change must be an update, got "
        f"action={version_outcome.action!r} (reason={version_outcome.failure_reason!r})"
    )
    assert version_outcome.task_id is not None, "a version upgrade must dispatch a task"
    # The upgrade task succeeds only after the driver's upgrade action returns,
    # so every task the action creates exists by then.
    await _wait_for_task_success(
        client, deployment_id, str(version_outcome.task_id), timeout=300.0
    )

    # simple-app's upgrade action adds a stop_components and a start_components
    # task; upgrade_deployment_version is a no-op and execute_commands writes none.
    action_task_count = 2
    new_tasks = [
        e
        for e in await client.deployments.get_timeline(deployment_id)
        if str(e.task.id) not in after_config_task_ids
    ]
    assert len(new_tasks) == 1 + action_task_count, (
        f"a version-only change must dispatch exactly one upgrade; expected "
        f"{1 + action_task_count} new tasks (upgrade + {action_task_count} from "
        f"the driver action), got {[(str(e.task.id), e.task.type_) for e in new_tasks]}"
    )
    assert str(version_outcome.task_id) in {str(e.task.id) for e in new_tasks}, (
        "the upgrade task apply dispatched must be on the timeline"
    )


@pytest.mark.api_only(
    reason="apply_files has no UI flow; api/sdk and ui variants would re-run identical SDK calls",
)
async def test_apply_files_batch_continues_past_failure(
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    apply_environment_id: str,
    apply_environment_id_secondary: str,
    styrmin_resources: dict,  # noqa: ARG001 — transitive: cluster/BSL/driver loaded
    simple_app_image: str,  # noqa: ARG001 — ensures the image is built
    tmp_path: Path,
) -> None:
    """A batch with one bad manifest still applies the other two and reports `failed`.

    User Story 2 acceptance scenario 4: a batch where one manifest fails
    (driver mismatch against an existing deployment) must continue to
    process the remaining manifests, surface a per-manifest ``failed``
    outcome, and roll up a count summary that reflects the mix.

    Setup:
      1. Apply manifest ``alpha`` once via ``apply_files`` so it exists at
         driver ``simple-app``. The second pass will *update* it.
      2. Build a directory with three manifests and call
         ``apply_files([dir])``:
           - ``alpha.yaml``: same name + driver → expected ``updated``.
           - ``beta.yaml``: a fresh name + valid driver → expected ``created``.
           - ``gamma.yaml``: re-uses ``alpha``'s name but a different driver
             → ``DriverMismatchError`` from inside ``apply()``, captured by
             ``apply_files`` as a ``failed`` outcome.

    Asserts on per-outcome shape and on cluster-side state for the two
    successful deployments.

    Two envs are needed because the manifest schema has no
    ``service_name_overrides`` surface and ``simple-app`` registers a
    fixed per-env service name. ``alpha`` and ``gamma`` (which reuses
    ``alpha``'s deployment name to trigger the driver-mismatch failure)
    target the primary env; ``beta`` lives in a secondary env so its own
    ``simple-app`` deployment doesn't collide with ``alpha``'s service.
    """
    driver, client = session_scenario_driver

    environment = await client.environments.get(environment_id=apply_environment_id)
    env_name = environment.name
    secondary_environment = await client.environments.get(
        environment_id=apply_environment_id_secondary
    )
    secondary_env_name = secondary_environment.name

    # --- Step 1: prime alpha so the batch hits both create + update branches.
    alpha_name = f"apply-batch-alpha-{tmp_path.name[-8:]}"
    beta_name = f"apply-batch-beta-{tmp_path.name[-8:]}"

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    (seed_dir / "alpha.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "styrmin/v1",
                "kind": "Deployment",
                "metadata": {"name": alpha_name},
                "spec": {
                    "driver": "simple-app",
                    "version": "0.1.0",
                    "environment": env_name,
                    "config": {},
                    "parameters": {},
                },
            }
        )
    )
    seed_outcomes = await client.deployments.apply_files([seed_dir])
    assert len(seed_outcomes) == 1
    assert seed_outcomes[0].action == "created", (
        f"seeding alpha should create the deployment, got {seed_outcomes[0]!r}"
    )
    assert seed_outcomes[0].deployment_id is not None
    alpha_deployment_id = str(seed_outcomes[0].deployment_id)
    await driver.wait_for_deployment_running(
        deployment_id=alpha_deployment_id, timeout=300.0
    )

    # --- Step 2: build a directory of three manifests and apply it.
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()

    # alpha.yaml — same (name, driver) as the seeded deployment → update path.
    (batch_dir / "alpha.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "styrmin/v1",
                "kind": "Deployment",
                "metadata": {"name": alpha_name},
                "spec": {
                    "driver": "simple-app",
                    "version": "0.1.0",
                    "environment": env_name,
                    "config": {"ip_whitelist": ["10.0.0.0/8"]},
                    "parameters": {},
                },
            }
        )
    )
    # beta.yaml — new name, valid driver, separate env → create path.
    # Targets the secondary env so its simple-app service registration
    # doesn't collide with alpha's in the primary env.
    (batch_dir / "beta.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "styrmin/v1",
                "kind": "Deployment",
                "metadata": {"name": beta_name},
                "spec": {
                    "driver": "simple-app",
                    "version": "0.1.0",
                    "environment": secondary_env_name,
                    "config": {},
                    "parameters": {},
                },
            }
        )
    )
    # gamma.yaml — re-uses alpha's name with a *different* driver → mismatch.
    (batch_dir / "gamma.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "styrmin/v1",
                "kind": "Deployment",
                "metadata": {"name": alpha_name},
                "spec": {
                    "driver": "not-simple-app",
                    "version": "0.1.0",
                    "environment": env_name,
                    "config": {},
                    "parameters": {},
                },
            }
        )
    )

    outcomes = await client.deployments.apply_files([batch_dir])

    # apply_files returns outcomes in expansion order (sorted filename:
    # alpha, beta, gamma). One updated, one created, one failed.
    assert len(outcomes) == 3, f"expected 3 outcomes, got {outcomes!r}"
    by_action = {o.action for o in outcomes}
    assert by_action == {"created", "updated", "failed"}, (
        f"expected one of each action, got {by_action!r} from {outcomes!r}"
    )

    alpha_outcome = next(
        o for o in outcomes if o.name == alpha_name and o.action == "updated"
    )
    beta_outcome = next(
        o for o in outcomes if o.name == beta_name and o.action == "created"
    )
    gamma_outcome = next(o for o in outcomes if o.action == "failed")

    assert alpha_outcome.deployment_id is not None
    assert str(alpha_outcome.deployment_id) == alpha_deployment_id, (
        "alpha update should target the seeded deployment, not create a new one"
    )
    assert beta_outcome.deployment_id is not None
    assert gamma_outcome.failure_reason is not None
    assert "driver" in gamma_outcome.failure_reason.lower(), (
        f"gamma failure reason should mention the driver mismatch; got "
        f"{gamma_outcome.failure_reason!r}"
    )

    # Count summary the CLI would print: "1 created, 1 updated, 1 failed".
    created_count = sum(1 for o in outcomes if o.action == "created")
    updated_count = sum(1 for o in outcomes if o.action == "updated")
    failed_count = sum(1 for o in outcomes if o.action == "failed")
    assert (created_count, updated_count, failed_count) == (1, 1, 1), (
        f"expected (1, 1, 1) for (created, updated, failed); got "
        f"({created_count}, {updated_count}, {failed_count}) from {outcomes!r}"
    )

    # --- Step 3: verify cluster-side state for the two successes.
    beta_deployment_id = str(beta_outcome.deployment_id)
    await driver.wait_for_deployment_running(
        deployment_id=alpha_deployment_id, timeout=300.0
    )
    await driver.wait_for_deployment_running(
        deployment_id=beta_deployment_id, timeout=300.0
    )

    refreshed_alpha = await client.deployments.get_by_name(
        alpha_name, environment_id=apply_environment_id
    )
    assert refreshed_alpha is not None, "alpha should still exist after the batch"
    assert refreshed_alpha.config == {"ip_whitelist": ["10.0.0.0/8"]}, (
        f"alpha config should reflect the batch update; got {refreshed_alpha.config!r}"
    )

    refreshed_beta = await client.deployments.get_by_name(
        beta_name, environment_id=apply_environment_id_secondary
    )
    assert refreshed_beta is not None, "beta should have been created by the batch"


@pytest.mark.api_only(
    reason="apply_files(wait=True) has no UI flow; api/sdk and ui variants would re-run identical SDK calls",
)
async def test_apply_files_wait_blocks_until_running(
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    apply_environment_id: str,
    styrmin_resources: dict,  # noqa: ARG001 — transitive: cluster/BSL/driver loaded
    simple_app_image: str,  # noqa: ARG001 — ensures the image is built
    tmp_path: Path,
) -> None:
    """``apply_files([path], wait=True)`` blocks until ``Deployment.status`` is RUNNING.

    User Story 4: ``--wait`` (and its SDK equivalent) must not return until each
    successfully-submitted deployment is observably RUNNING. The SDK polls
    ``Deployment.status`` (matching ``CONTEXT.md`` → "Deployment state" and the
    API E2E driver's ``wait_for_deployment_running``); see
    ``python_sdk/src/styrmin_sdk/_wait.py`` for the rationale that
    rules out polling ``Task.status`` (settles too early — the task's
    ``SUCCESS`` transition deliberately doesn't flip ``Deployment.status``)
    and ``ApplicationInstance.status`` (touched by other reconciliation
    paths, so racy).

    The negative scenario (manifest engineered to fail reconciliation) is left
    out for now — every available driver in the e2e suite is a known-good
    reconciliation. The SDK's failure-flip path is covered by
    ``test_apply_wait_marks_outcome_failed_on_terminal_failure`` in
    ``python_sdk/tests/test_deployments.py``.
    """
    driver, client = session_scenario_driver

    environment = await client.environments.get(environment_id=apply_environment_id)
    env_name = environment.name

    deployment_name = f"apply-wait-e2e-{tmp_path.name[-8:]}"

    # Seed the deployment so the wait scenario exercises the *update* branch
    # (the more interesting path: it must wait for the post-update reconcile
    # to settle, not just the initial deploy). Seed without ``wait=True`` so
    # that the test's wait-feature assertion is exercised only on the update
    # path; we then block on RUNNING via the driver helper, which gives the
    # seed a longer (and isolated) settle budget.
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    (seed_dir / "app.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "styrmin/v1",
                "kind": "Deployment",
                "metadata": {"name": deployment_name},
                "spec": {
                    "driver": "simple-app",
                    "version": "0.1.0",
                    "environment": env_name,
                    "config": {},
                    "parameters": {},
                },
            }
        )
    )
    seed_outcomes = await client.deployments.apply_files([seed_dir])
    assert len(seed_outcomes) == 1
    assert seed_outcomes[0].action == "created", (
        f"seeding should create the deployment, got {seed_outcomes[0]!r}"
    )
    assert seed_outcomes[0].deployment_id is not None
    await driver.wait_for_deployment_running(
        deployment_id=str(seed_outcomes[0].deployment_id), timeout=600.0
    )

    # Re-author with a config change and apply with ``wait=True``.
    update_dir = tmp_path / "update"
    update_dir.mkdir()
    (update_dir / "app.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "styrmin/v1",
                "kind": "Deployment",
                "metadata": {"name": deployment_name},
                "spec": {
                    "driver": "simple-app",
                    "version": "0.1.0",
                    "environment": env_name,
                    "config": {"ip_whitelist": ["10.0.0.0/8"]},
                    "parameters": {},
                },
            }
        )
    )

    outcomes = await client.deployments.apply_files([update_dir], wait=True)

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.action == "updated", (
        f"second apply should update the existing deployment, got "
        f"action={outcome.action!r} (reason={outcome.failure_reason!r})"
    )
    assert outcome.deployment_id is not None

    # ``wait=True`` must not return before the deployment reaches a terminal
    # state. We observe this via the live SDK rather than trusting only the
    # polling loop, so a regression in the wait helper would surface as a
    # status mismatch here rather than as a green test.
    #
    # Important: we assert on ``Deployment.status`` (the canonical
    # user-visible enum the SDK wait polls), NOT on
    # ``applicationInstance.status``. The latter is racy here because the
    # post-update reconciliation pipeline continues firing sub-flows
    # (service registration, ingress patching, …) after the outer
    # apply_state completes — each sub-flow's ``on_running`` callback
    # transiently writes ``instance.status = PENDING`` via
    # ``services/tasks.py:update_task_state``. ``Deployment.status``,
    # owned by the CRD status reporter, settles to ``"running"`` once the
    # cluster-side CR is Ready and stays there.
    refreshed = await client.deployments.get(outcome.deployment_id)
    assert refreshed.status.lower() == "running", (
        f"apply_files(wait=True) returned but Deployment.status is "
        f"{refreshed.status!r}; wait did not block until RUNNING"
    )
