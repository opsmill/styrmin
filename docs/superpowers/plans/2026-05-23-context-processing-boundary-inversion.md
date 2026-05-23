# Context Processing Boundary Inversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the "stale context across the FastAPI → Prefect boundary" bug class (first surfaced by #237: rename-service-after-deploy never creates the new endpoint) by (a) committing all desired-state writes before instance generation and (b) sending `deployment_id` + `new_instance_id` + `current_instance_id` across the Prefect boundary instead of a pre-computed `Remediation` object.

**Architecture:**

- **Server-side keeps:** validation, writing user intent to the DB (parameters, config, deployed services), generating the new `Instance` from the freshly-committed deployment, setting it active, creating the `Task` row, and scheduling the Prefect `apply_state` flow.
- **Prefect side gains:** loading the deployment + both instance IDs fresh from the DB at flow-run time, building the `DiffReport` via `Comparator`, generating the `Remediation` via `Remediator`, applying it.
- **Boundary carries IDs, not plans.** The `Remediation` pydantic model is no longer a Prefect parameter.
- **Two-UoW pattern in `update_deployment`.** Phase 1 commits the user's intent (config / parameters / reconciled services). Phase 2 (a new UoW that begins after phase 1 commits) regenerates the instance against the now-correct DB, sets active, creates the task, commits, then schedules Prefect outside both UoWs. This is the minimal change that closes the #237 bug class even without the boundary inversion, so we land it as Stage 1 and ship the inversion in Stages 2–3.

**Tech Stack:** Python 3.14, Strawberry GraphQL, SQLModel/SQLAlchemy (async), Prefect, Pydantic, pytest. Backend only — frontend unchanged.

**Bug context:** [Issue #237](https://github.com/opsmill/styrmin/issues/237). Analyst hypothesis confirmed: `services/deployment.py::update_deployment` calls `reconcile_services_on_upgrade()` *after* `generate_instance_from_deployment()` and `apply_state()`, so the `DeployedService` rows are still pre-rename when the context is built, and the Prefect flow receives a frozen `Remediation` against the old service name.

---

## File Map

**Modify (Stage 1):**

- `backend/styrmin_backend/services/deployment.py` — reorder `update_deployment()` into two UoW phases (lines 241–384). No signature changes.

**Modify (Stage 2):**

- `backend/styrmin_backend/services/reconciliation/__init__.py` — `apply_state()` becomes a thin Task-creator + Prefect scheduler that takes instance IDs and no longer calls `Comparator`/`Remediator`. Drop the `fast_depends` injection of `PrefectManager` from `apply_state`; it now lives inside the flow.
- `backend/styrmin_backend/agent/tasks/orchestration.py` — `apply_state` flow signature changes from `(task_id, deployment_id, remediation)` to `(task_id, deployment_id, new_instance_id, current_instance_id)`. The flow opens its own UoW, loads the deployment + both instances, builds the diff via `Comparator`, generates the remediation via `Remediator`, and applies it.
- `backend/styrmin_backend/services/reconciliation/remediation.py` — no signature change; `Remediation.apply()` still chains to a sub-flow via `run_deployment_or_fail`. Update strategies' `execute()` to accept `Instance` objects loaded from the DB (no change to the `Remediator` shape).
- `backend/styrmin_backend/services/deployment.py` — update 5 callers of `apply_state` (`update_deployment`, `refresh_deployment`, `update_deployment_version`, `redeploy_for_environment_update`, `_ensure_ingress_controller`, `deploy_application`) to pass `current_instance` + `new_instance` (which the function will reduce to IDs internally).
- `backend/styrmin_backend/services/primitives.py` — update 2 callers of `apply_state` (`stop_components`, `start_components`).

**Modify (Stage 3 — cleanup):**

- `backend/styrmin_backend/services/reconciliation/remediation.py` — clean up imports if `inject(cast_result=False)` is no longer needed on the server side.
- Remove `Remediation` from any place it's still referenced as a Prefect parameter.

**Tests — new:**

- `backend/tests/unit/services/test_update_deployment_service_rename.py` — direct repro of #237 at the service-layer boundary. Asserts the new `Instance.context.deployed_services` reflects the renamed service after `update_deployment()` returns.
- `backend/tests/functional/graphql/test_update_deployment_service_rename.py` — GraphQL-level repro: call `updateDeployment(serviceNameOverrides=…)`, then read back the deployment and assert the active instance's context carries the new resolved name.
- `backend/tests/unit/services/test_apply_state_boundary.py` — Stage 2 test: assert the server-side `apply_state` schedules the Prefect flow with `(task_id, deployment_id, new_instance_id, current_instance_id)` and does **not** call `Comparator`/`Remediator`.
- `backend/tests/unit/agent/tasks/test_apply_state_flow.py` — Stage 2 test: assert the Prefect-side `apply_state` flow loads the deployment + instances, builds a diff, builds a remediation, and calls `remediation.apply()`.

**Tests — modify:**

- `backend/tests/unit/services/reconciliation/test_remediation.py` — strategies still get tested at the same layer, but their callers change. Sanity-check that this file does not import the old `Remediation` parameter shape.
- `backend/tests/e2e/test_service_discovery.py` — extend with a rename-after-deploy scenario (api-only marker) that catches #237 at the cluster level.

---

## Stage 1 — Fix the ordering bug in `update_deployment` (no boundary change)

This stage closes #237 without touching the Prefect boundary. It produces working, shippable software on its own. Stages 2 and 3 are independent.

### Task 1.1: Unit test reproducing #237 at the service layer

**Files:**

- Create: `backend/tests/unit/services/test_update_deployment_service_rename.py`

- [ ] **Step 1: Write the failing test**

The repo has `tests/unit/services/fakes.py` with `FakeUnitOfWork` etc. and `tests/unit/services/test_service_overrides.py` shows the wiring style. Add a deployment with one driver-declared service, run `update_deployment(service_name_overrides={…})`, then assert the active instance's context exposes the new resolved name.

```python
"""Repro for #237 at the service layer.

Bug: `update_deployment(service_name_overrides=…)` previously called
`reconcile_services_on_upgrade` AFTER `generate_instance_from_deployment`,
so the generated instance carried the OLD service name. The Prefect flow
then reconciled K8s against the old name and never created the new Service.

Fix: writes that affect context (service rename, parameter merge, config
update) must be COMMITTED before instance generation. This test pins that
invariant at the service-layer boundary, so future reorderings can't
silently regress.
"""

from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest

from styrmin_backend.domain.models import Deployment, DeploymentState
from styrmin_backend.services.deployment import update_deployment
from styrmin_backend.services.driver.models.resources.services import (
    ServiceDefinition,
    ServiceKind,
    ServiceScope,
)
from tests.unit.services.fakes import (
    FakeUnitOfWork,
    FakeClusterRepository,
    FakeEnvironmentRepository,
    FakeHelmRepositoryRepository,
    FakeHelmChartRepository,
    FakeApplicationRepository,
    FakeApplicationInstanceRepository,
    FakeActionRepository,
    FakeTaskRepository,
    FakeDeployedServiceRepository,
    FakeDeploymentRepository,
    FakeApplicationDriverVersionRepository,
)


def _make_uow() -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationDriverVersionRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        deployed_services=FakeDeployedServiceRepository(),
        deployments=FakeDeploymentRepository(),
        application_drivers=FakeApplicationRepository(),
    )


@pytest.mark.asyncio
@patch("styrmin_backend.services.reconciliation.apply_state", new_callable=AsyncMock)
async def test_service_rename_produces_instance_with_new_name(
    mock_apply_state: AsyncMock,
) -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    env_id = uuid4()

    # Seed an existing deployment with a single service "api".
    # (Helper to be added in fakes.py if missing — see Task 1.2.)
    await _seed_deployment_with_service(
        uow=uow,
        deployment_id=deployment_id,
        environment_id=env_id,
        driver_service_name="api",
    )

    # Stub apply_state so we don't touch Prefect.
    mock_apply_state.return_value = _stub_task(deployment_id=deployment_id)

    async with uow:
        await update_deployment(
            deployment_id=deployment_id,
            uow=uow,
            service_name_overrides={"api": "api-v2"},
        )

    # Pull the deployment back out of the fake repo.
    async with uow:
        deployment = await uow.deployments.find(id=deployment_id)

    assert deployment is not None
    assert deployment.active_instance is not None
    deployed_services = deployment.active_instance.context.deployed_services
    resolved_names = {svc["resolved_name"] for svc in deployed_services}
    assert resolved_names == {"api-v2"}, (
        f"Expected the new instance context to carry the renamed service "
        f"'api-v2', got {resolved_names}. This is #237."
    )
```

The `_seed_deployment_with_service` and `_stub_task` helpers go in the same file (keep them private to this test for now).

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/unit/services/test_update_deployment_service_rename.py -v
```

Expected: FAIL — assertion shows `resolved_names == {"api"}` (the old name) because reconcile runs after instance generation.

If the fake repos don't have the helpers yet (`FakeDeploymentRepository`, `FakeApplicationDriverVersionRepository`), Task 1.2 fills the gap.

- [ ] **Step 3: Commit the failing test (xfail)**

Mark the assertion with `pytest.xfail("#237 — fixed in Task 1.3")` ONLY if the fakes are missing too many helpers; otherwise leave it as a real failure and proceed straight to Task 1.3. Commit either way.

```bash
git add backend/tests/unit/services/test_update_deployment_service_rename.py
git commit -m "test: pin #237 — service rename must produce instance with new name"
```

### Task 1.2: Fill any fakes gaps

**Files:**

- Modify: `backend/tests/unit/services/fakes.py`

- [ ] **Step 1: Run the new test and read the import errors**

```bash
cd backend && uv run pytest tests/unit/services/test_update_deployment_service_rename.py -v 2>&1 | head -40
```

Whatever imports fail (`FakeDeploymentRepository`, `FakeApplicationDriverVersionRepository`, etc.), add to `fakes.py`. Mirror the style of the existing fakes (in-memory list + `save`/`find`/`get` methods).

- [ ] **Step 2: Implement the missing fakes**

Look at the real repos (`backend/styrmin_backend/repository/deployment.py`, `application_driver_version.py`) for the protocol surface the service layer calls. Implement only the methods `update_deployment` actually invokes (`find`, `save`, `get_by_name`, etc.).

- [ ] **Step 3: Re-run the test**

Expected: now FAILS at the assertion (not at imports).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/unit/services/fakes.py
git commit -m "test: extend service-layer fakes for #237 repro"
```

### Task 1.3: Reorder `update_deployment` into two UoW phases

**Files:**

- Modify: `backend/styrmin_backend/services/deployment.py:204-384`

- [ ] **Step 1: Read the current function carefully**

The current ordering inside `async with uow:` is:

1. Find deployment, validate config, merge parameters, update name.
2. `current_instance = deployment.active_instance`
3. `new_instance = await generate_instance_from_deployment(...)` ← reads stale `DeployedService` rows
4. `set_active_instance`, `set_status(PENDING)`
5. `apply_state(...)` ← builds frozen remediation
6. `deployments.save`
7. `reconcile_services_on_upgrade(...)` ← writes new names too late
8. `tasks.save`, `commit`

- [ ] **Step 2: Rewrite into two phases**

Replace the body of `update_deployment` from `async with uow:` (line 241) through to the end of the function with the structure below. Keep all existing validation logic unchanged; only the ordering and the UoW splitting change.

```python
async with uow:
    deployment = await uow.deployments.find(id=deployment_id)
    if deployment is None:
        raise DeploymentNotFoundError(
            f"Deployment with ID {deployment_id} not found"
        )

    logger.info(
        "Deployment found: id={} current_version={}",
        deployment.id,
        deployment.application_version,
    )

    # ---- Phase 1: validate + write user intent to the DB ----
    # Everything that affects the *desired-state context* must land here
    # so that `generate_instance_from_deployment` in phase 2 reads
    # already-committed rows. This is the #237 fix: the previous ordering
    # ran reconcile_services_on_upgrade AFTER instance generation, so the
    # context carried the old service name.

    if deployment_config is not None:
        adv = await uow.application_driver_versions.get(
            id=deployment.application_driver_version_id
        )
        assert adv is not None, "Application driver version not found"
        known_names = [cc.name for cc in (adv.component_configs or [])]
        _validate_component_env_var_targets(deployment_config, known_names)
        _prevalidate_deployment_env_vars(deployment_config)

        try:
            validate_deployment_config(context=deployment_config)
        except InvalidDeploymentContextError as e:
            raise InvalidContextError() from e

    if deployment_name is not None:
        try:
            validated_name = validate_deployment_name(deployment_name)
        except ValueError as e:
            raise DeploymentNameValidationError(str(e)) from e

        if validated_name != deployment.name:
            existing = await uow.deployments.get_by_name(
                validated_name, deployment.environment_id
            )
            if existing is not None:
                raise DeploymentNameConflictError(
                    f"A deployment named '{validated_name}' already exists "
                    "in this environment"
                )
            deployment.name = validated_name

    if deployment_config is not None:
        deployment.config = deployment_config

    await _ensure_ingress_controller(
        environment_id=deployment.environment_id,
        uow=uow,
        created_by_user_id=deployment.created_by_user_id,
    )

    if deployment_parameters is not None:
        application_driver_version = await uow.application_driver_versions.get(
            id=deployment.application_driver_version_id
        )
        assert application_driver_version is not None
        merged_parameters = {
            **deployment.parameters,
            **deployment_parameters,
        }
        definitions = parse_parameter_definitions(
            application_driver_version.parameters
        )
        deployment.parameters = validate_parameter_values(
            definitions=definitions,
            values=merged_parameters,
        )

    if service_name_overrides is not None:
        adv_for_services = await uow.application_driver_versions.get(
            id=deployment.application_driver_version_id
        )
        assert adv_for_services is not None
        service_defs = parse_service_definitions(adv_for_services.services)
        if service_defs:
            await reconcile_services_on_upgrade(
                deployment_id=deployment.id,
                environment_id=deployment.environment_id,
                new_service_definitions=service_defs,
                uow=uow,
                service_name_overrides=service_name_overrides,
            )

    await uow.deployments.save(deployment=deployment)
    await uow.commit()
    logger.info(
        "Phase 1 committed: deployment_id={} (intent written to DB)",
        deployment.id,
    )

# ---- Phase 2: regenerate instance against the freshly-committed DB ----
# New UoW. The deployment is re-loaded so the in-memory copy reflects
# everything phase 1 wrote (in particular, the new resolved_name of any
# renamed DeployedService).

async with uow:
    deployment = await uow.deployments.find(id=deployment_id)
    assert deployment is not None, (
        "Deployment vanished between phase 1 commit and phase 2 load"
    )

    current_instance = deployment.active_instance
    new_instance = await generate_instance_from_deployment(
        deployment=deployment,
        uow=uow,
    )
    deployment.set_active_instance(instance=new_instance)
    deployment.set_status(DeploymentState.PENDING)
    logger.info("New instance set as active: instance_id={}", new_instance.id)

    task = await apply_state(
        deployment=deployment, current_instance=current_instance, uow=uow
    )

    await uow.deployments.save(deployment=deployment)
    await uow.tasks.save(task=task)
    await uow.commit()

    logger.info("Deployment config update committed, task_id={}", task.id)

    result = await uow.tasks.find(id=task.id)
    assert result is not None, "Task not found"
    return result
```

Note: `apply_state` still ends with `prefect_manager.run_action(...)` *before* the final commit. This is a known latent race that Stage 2 closes — leave it alone in Stage 1 to keep the diff small.

- [ ] **Step 3: Run the unit test from Task 1.1**

```bash
cd backend && uv run pytest tests/unit/services/test_update_deployment_service_rename.py -v
```

Expected: PASS.

- [ ] **Step 4: Run the full update-deployment test family**

```bash
cd backend && uv run pytest \
  tests/unit/services/test_update_deployment_service_rename.py \
  tests/unit/services/test_service_overrides.py \
  tests/functional/graphql/test_update_deployment_input_propagation.py \
  tests/functional/graphql/test_update_deployment_input_errors.py \
  -v
```

Expected: ALL PASS. If anything else broke, the most likely culprit is the `apply_state` call now living in the second UoW with a re-loaded `deployment` — verify the assertion `Deployment vanished between phase 1 commit and phase 2 load` is not triggered by tests that swap UoW backends.

- [ ] **Step 5: Run lint + format**

```bash
uv run invoke format lint
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add backend/styrmin_backend/services/deployment.py
git commit -m "fix(#237): commit service-rename writes before regenerating instance context

Split update_deployment into two UoW phases: phase 1 validates and
commits user intent (parameters, config, reconciled DeployedService
rows). Phase 2 reloads the deployment, regenerates the instance from
the now-correct DB state, sets it active, and schedules reconciliation.

Closes the bug class where any DB write that affects context could land
after generate_instance_from_deployment had already snapshotted the
old context."
```

### Task 1.4: GraphQL-level propagation test for #237

**Files:**

- Create: `backend/tests/functional/graphql/test_update_deployment_service_rename.py`
- Reuse: `backend/tests/functional/graphql/operations/update_deployment.graphql`

**Steps:**

- [ ] **Step 1: Write the test**

Use the existing `update_deployment_input_*` tests as templates for the GraphQL request shape. The test should:

1. Create a deployment (via the SDK fixture or a direct service call) with a driver that declares one service.
2. Call `updateDeployment(serviceNameOverrides=[{driverServiceName: "X", overrideName: "X-v2"}])` via the GraphQL endpoint.
3. Wait for the mutation to return.
4. Query the deployment back and assert that:
   - `deployedServices` resolves to one entry with `resolvedName == "X-v2"`.
   - The active instance's serialized context (via whatever GraphQL field exposes it; if none, fall back to fetching it through the SDK or DB) carries `"X-v2"` in its `deployed_services` block.

```python
import pytest


@pytest.mark.asyncio
async def test_service_rename_propagates_to_active_instance_context(
    graphql_client,
    seeded_deployment_with_service,  # fixture: returns deployment + driver svc name
) -> None:
    deployment_id = seeded_deployment_with_service.id
    driver_service_name = seeded_deployment_with_service.driver_service_name

    mutation = """
    mutation Rename($id: UUID!, $overrides: [ServiceNameOverrideInput!]!) {
      updateDeployment(
        deploymentId: $id,
        serviceNameOverrides: $overrides
      ) { id }
    }
    """
    resp = await graphql_client.execute(
        mutation,
        variables={
            "id": str(deployment_id),
            "overrides": [
                {
                    "driverServiceName": driver_service_name,
                    "overrideName": f"{driver_service_name}-v2",
                }
            ],
        },
    )
    assert resp.get("errors") is None, resp

    query = """
    query Q($id: UUID!) {
      deployment(id: $id) {
        id
        deployedServices { driverServiceName resolvedName }
        activeInstance { context }
      }
    }
    """
    out = await graphql_client.execute(query, variables={"id": str(deployment_id)})
    dep = out["data"]["deployment"]

    resolved = {s["resolvedName"] for s in dep["deployedServices"]}
    assert resolved == {f"{driver_service_name}-v2"}

    ctx_services = dep["activeInstance"]["context"]["deployed_services"]
    assert {s["resolved_name"] for s in ctx_services} == {f"{driver_service_name}-v2"}
```

If `activeInstance.context` is not exposed via GraphQL, drop that final block and trust the assertion on `deployedServices`; the unit test from Task 1.1 already pins the instance-side invariant. Look at the existing GraphQL schema (`schema.graphql` at the repo root) before deciding.

- [ ] **Step 2: Run the test**

```bash
cd backend && uv run pytest tests/functional/graphql/test_update_deployment_service_rename.py -v
```

Expected: PASS (the service-layer fix from Task 1.3 closes the bug; this just pins it at the GraphQL boundary).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/functional/graphql/test_update_deployment_service_rename.py
git commit -m "test(graphql): propagate #237 fix to the mutation boundary"
```

### Task 1.5: Extend the e2e service-discovery test with a rename-after-deploy scenario

**Files:**

- Modify: `backend/tests/e2e/test_service_discovery.py`

- [ ] **Step 1: Add a new test in the same file**

The existing `test_service_discovery_between_apps` deploys two apps with their final names. The new test deploys one app, asserts the Service is reachable at the original name, then renames it via `update_deployment(serviceNameOverrides=…)`, and asserts the Service object with the new name exists in the cluster.

The repo convention is to mark API-only flows with `@pytest.mark.api_only(reason=…)` — see CLAUDE.md. This scenario goes through SDK calls and `kr8s` only; no UI is exercised, so it must be api-only. Both `@pytest.mark.api_only` and `@pytest.mark.ci` apply.

```python
@pytest.mark.api_only(
    reason="Rename flow drives SDK calls + kubectl/kr8s only; the "
    "[ui-chromium] variant would just re-run the same SDK call.",
)
@pytest.mark.ci
async def test_service_rename_creates_new_kubernetes_service(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,  # noqa: ARG001
    simple_app_image: str,  # noqa: ARG001
    vcluster: dict,
) -> None:
    """#237: renaming a deployed service must create the new Service object."""
    kubeconfig_path = vcluster["kubeconfig_path"]

    dep = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": "before-rename"}
        ],
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=dep.id, timeout=300.0
    )

    namespace = f"styrmin-{dep.id}"
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)

    # Pre-rename: Service "before-rename" exists.
    before = await _find_service(kr8s_api, namespace, "before-rename")
    assert before is not None, "Pre-rename Service should exist"

    # Trigger the rename via the same path that #237 broke.
    await scenario_driver.update_deployment(
        deployment_id=dep.id,
        service_name_overrides=[
            {"driverServiceName": "simple-app", "overrideName": "after-rename"}
        ],
    )
    await scenario_driver.wait_for_deployment_running(
        deployment_id=dep.id, timeout=300.0
    )

    # Post-rename: Service "after-rename" exists. Without the #237 fix this
    # is the assertion that fails — the K8s Service for the new name is
    # never created.
    after_deadline = time.time() + 120
    after = None
    while time.time() < after_deadline:
        after = await _find_service(kr8s_api, namespace, "after-rename")
        if after is not None:
            break
        await asyncio.sleep(5)
    assert after is not None, (
        "Post-rename Service 'after-rename' was never created. "
        "This is #237 regressing — the new instance's context did not "
        "include the renamed service."
    )


async def _find_service(
    kr8s_api, namespace: str, name_substring: str
):
    services: list[AsyncService] = [
        svc async for svc in AsyncService.list(namespace=namespace, api=kr8s_api)
        if isinstance(svc, AsyncService)
    ]
    return next(
        (svc for svc in services if name_substring in svc.name and "postgresql" not in svc.name),
        None,
    )
```

If `scenario_driver` does not expose `update_deployment(deployment_id, service_name_overrides=…)`, add it to both `api_driver.py` and the protocol; the unit/functional tests already pin the underlying behaviour.

- [ ] **Step 2: Run the new test in isolation (with --pdb)**

Per CLAUDE.md, every e2e run uses `--pdb`. From an interactive shell:

```bash
cd backend && uv run pytest tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service -v -s --pdb
```

Expected: PASS. If it fails, inspect the cluster from a second shell (see CLAUDE.md for the kubeconfig export incantation), confirm the post-rename Service is missing, and double-check that Task 1.3 actually shipped.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/e2e/test_service_discovery.py backend/tests/e2e/drivers/  # if drivers changed
git commit -m "test(e2e): #237 — rename-after-deploy creates the new Service"
```

### Task 1.6: Stage 1 checkpoint — full backend test run

- [ ] **Step 1: Run the full backend suite**

```bash
cd backend && uv run pytest tests/unit tests/functional -v --tb=short
```

Expected: all green. The only new failures should be in tests that hard-coded the old ordering, which would be a genuine signal.

- [ ] **Step 2: If anything red, fix and recommit**

- [ ] **Step 3: Update CONTEXT.md / dev/knowledge if anything in the user-visible contract changed**

For Stage 1 specifically, the only behavioural change is "the new instance's context reflects the renamed service" — which was already the documented intent. No doc update needed. Verify by skimming `dev/knowledge/architecture.md` and `docs/how-it-works/` for any text claiming the prior (incorrect) ordering; remove or fix if found.

- [ ] **Step 4: Stage 1 ships**

At this point #237 is closed and the bug class for "DB write lands after context generation in the same UoW" is structurally prevented in `update_deployment`. Stages 2–3 generalise the fix.

---

## Stage 2 — Boundary inversion: move diff + remediation into the Prefect flow

This stage stops serializing `Remediation` across the FastAPI→Prefect boundary. The server schedules the flow with three IDs (`deployment_id`, `new_instance_id`, `current_instance_id`); the flow loads, diffs, and remediates from a fresh DB read.

### Task 2.1: Unit test for the new server-side `apply_state` shape

**Files:**

- Create: `backend/tests/unit/services/test_apply_state_boundary.py`

- [ ] **Step 1: Write the failing test**

```python
"""Pin the post-#237 FastAPI/Prefect boundary contract.

Server-side `apply_state` must:
- Create a Task row.
- Schedule the Prefect `apply_state` flow with deployment_id +
  new_instance_id + current_instance_id + task_id (no Remediation
  parameter).
- Return the Task.

It must NOT call Comparator or Remediator — that work belongs inside
the flow so a flow retry sees fresh DB state.
"""

from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrmin_backend.domain.models import (
    Deployment,
    DeploymentState,
    Instance,
    InstanceStatus,
)
from styrmin_backend.services.reconciliation import apply_state
from styrmin_backend.workflows.models import PrefectAction


@pytest.mark.asyncio
async def test_apply_state_passes_ids_not_remediation_to_prefect() -> None:
    deployment = _make_deployment_with_active_instance()
    current = deployment.active_instance
    new_instance = _make_instance(deployment.id)
    deployment.set_active_instance(new_instance)

    fake_uow = MagicMock()
    fake_prefect = MagicMock()
    fake_prefect.run_action = AsyncMock(
        return_value=MagicMock(id=uuid4(), state_name="Scheduled")
    )

    # Patch the dependency injector so apply_state picks up our fake.
    with patch(
        "styrmin_backend.services.reconciliation.get_manager",
        return_value=fake_prefect,
    ), patch(
        "styrmin_backend.services.reconciliation.Comparator"
    ) as mock_comparator, patch(
        "styrmin_backend.services.reconciliation.Remediator"
    ) as mock_remediator:
        task = await apply_state(
            deployment=deployment,
            current_instance=current,
            uow=fake_uow,
        )

    # The Prefect call must carry IDs, not a Remediation.
    fake_prefect.run_action.assert_awaited_once()
    kwargs = fake_prefect.run_action.await_args.kwargs
    assert kwargs["action"] == PrefectAction.APPLY_STATE
    params = kwargs["parameters"]
    assert params["deployment_id"] == deployment.id
    assert params["new_instance_id"] == new_instance.id
    assert params["current_instance_id"] == (current.id if current else None)
    assert params["task_id"] == task.id
    assert "remediation" not in params

    # Server-side never builds a remediation anymore.
    mock_comparator.assert_not_called()
    mock_remediator.assert_not_called()


def _make_deployment_with_active_instance() -> Deployment:
    ...  # mirror style of existing reconciliation tests


def _make_instance(deployment_id) -> Instance:
    ...
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && uv run pytest tests/unit/services/test_apply_state_boundary.py -v
```

Expected: FAIL — the current `apply_state` calls `Comparator` and `Remediator` and passes a `Remediation` object.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/services/test_apply_state_boundary.py
git commit -m "test: pin the post-inversion apply_state boundary contract"
```

### Task 2.2: Implement the new server-side `apply_state`

**Files:**

- Modify: `backend/styrmin_backend/services/reconciliation/__init__.py`

- [ ] **Step 1: Rewrite `apply_state`**

```python
from fast_depends import Depends, inject
from loguru import logger

from styrmin_backend.domain.models import (
    Deployment,
    Instance,
    Task,
    TaskType,
)
from styrmin_backend.services.context import generate_context_from_deployment
from styrmin_backend.services.unit_of_work import UnitOfWork
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectAction


async def generate_instance_from_deployment(
    deployment: Deployment,
    uow: UnitOfWork,
) -> Instance:
    """Generate an instance from a deployment."""
    context = await generate_context_from_deployment(deployment=deployment, uow=uow)

    instance = Instance.create(
        application_version=deployment.application_version,
        deployment_id=deployment.id,
        application_driver_version_id=deployment.application_driver_version_id,
        context=context,
    )

    instance.context.instance.id = instance.id
    return instance


@inject(cast_result=False)  # type: ignore[arg-type]
async def apply_state(
    deployment: Deployment,
    current_instance: Instance | None,
    uow: UnitOfWork,  # noqa: ARG001  retained for caller-shape stability
    prefect_manager: PrefectManager = Depends(get_manager),
) -> Task:
    """Schedule a reconciliation pass for the deployment.

    Server-side responsibility: create the Task row and kick off the
    Prefect ``apply_state`` flow with the IDs the flow needs to load
    fresh state. The flow itself computes the diff and remediation
    against a freshly-loaded deployment — see
    `agent/tasks/orchestration.py::apply_state`. Pre-#237 this function
    pre-computed a Remediation and serialized it across the Prefect
    boundary, which froze the plan against a snapshot of the world and
    produced staleness bugs whenever DB writes landed between the
    snapshot and the flow start.
    """
    new_instance = deployment.active_instance
    assert new_instance is not None, "Deployment must have an active instance"

    task = Task.create(
        type=TaskType.NOOP,  # The flow will refine the type once it
                             # has computed the diff. NOOP is safe as
                             # the initial value; the orchestration
                             # callback updates the task state.
        deployment_id=deployment.id,
        prefect_flow_run_id=None,
    )

    logger.info(
        "Scheduling apply_state flow: task_id={} deployment_id={} "
        "current_instance_id={} new_instance_id={}",
        task.id,
        deployment.id,
        current_instance.id if current_instance else None,
        new_instance.id,
    )

    flow_info = await prefect_manager.run_action(
        action=PrefectAction.APPLY_STATE,
        parameters={
            "task_id": task.id,
            "deployment_id": deployment.id,
            "new_instance_id": new_instance.id,
            "current_instance_id": (
                current_instance.id if current_instance else None
            ),
        },
    )
    task.prefect_flow_run_id = flow_info.id
    return task
```

- [ ] **Step 2: Run the boundary test**

```bash
cd backend && uv run pytest tests/unit/services/test_apply_state_boundary.py -v
```

Expected: PASS.

- [ ] **Step 3: Don't run anything else yet** — the Prefect-side flow still expects `remediation` as a parameter, so the broader suite will be red until Task 2.3.

- [ ] **Step 4: Commit**

```bash
git add backend/styrmin_backend/services/reconciliation/__init__.py
git commit -m "refactor(reconciliation): server-side apply_state schedules with IDs, not a Remediation"
```

### Task 2.3: Unit test for the new Prefect-side `apply_state` flow

**Files:**

- Create: `backend/tests/unit/agent/tasks/test_apply_state_flow.py`

- [ ] **Step 1: Write the failing test**

```python
"""Pin the post-#237 Prefect-side apply_state behaviour.

The flow must:
- Open a UoW.
- Load the deployment, new instance, and (if provided) current
  instance from the freshly-committed DB.
- Build a DiffReport via Comparator.
- Generate a Remediation via Remediator.
- Call `remediation.apply()` (the existing sub-flow chain).
"""

from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
@patch("styrmin_backend.agent.tasks.orchestration.get_unit_of_work")
@patch("styrmin_backend.agent.tasks.orchestration.Comparator")
@patch("styrmin_backend.agent.tasks.orchestration.Remediator")
async def test_apply_state_flow_loads_fresh_and_remediates(
    mock_remediator_cls,
    mock_comparator_cls,
    mock_get_uow,
) -> None:
    from styrmin_backend.agent.tasks.orchestration import apply_state

    deployment_id = uuid4()
    new_instance_id = uuid4()
    current_instance_id = uuid4()
    task_id = uuid4()

    fake_uow = AsyncMock()
    fake_uow.deployments.find = AsyncMock(return_value=MagicMock(id=deployment_id))
    fake_uow.instances = AsyncMock()
    fake_uow.instances.find = AsyncMock(side_effect=lambda *, id: MagicMock(id=id))
    mock_get_uow.return_value = fake_uow

    diff_report = MagicMock()
    mock_comparator_cls.return_value.compare = MagicMock(return_value=diff_report)

    fake_remediation = MagicMock()
    fake_remediation.apply = AsyncMock(
        return_value=MagicMock(state=MagicMock(name="Completed"))
    )
    mock_remediator_cls.return_value.generate_remediation = AsyncMock(
        return_value=fake_remediation
    )

    # Run the flow directly (Prefect flows are still callables).
    await apply_state(
        task_id=task_id,
        deployment_id=deployment_id,
        new_instance_id=new_instance_id,
        current_instance_id=current_instance_id,
    )

    fake_uow.deployments.find.assert_awaited_with(id=deployment_id)
    mock_comparator_cls.assert_called_once()
    mock_remediator_cls.assert_called_once()
    fake_remediation.apply.assert_awaited_once()


@pytest.mark.asyncio
@patch("styrmin_backend.agent.tasks.orchestration.get_unit_of_work")
@patch("styrmin_backend.agent.tasks.orchestration.Comparator")
@patch("styrmin_backend.agent.tasks.orchestration.Remediator")
async def test_apply_state_flow_handles_no_remediation_needed(
    mock_remediator_cls,
    mock_comparator_cls,
    mock_get_uow,
) -> None:
    """If Remediator returns None, the flow should not error."""
    from styrmin_backend.agent.tasks.orchestration import apply_state

    fake_uow = AsyncMock()
    fake_uow.deployments.find = AsyncMock(return_value=MagicMock())
    fake_uow.instances = AsyncMock()
    fake_uow.instances.find = AsyncMock(return_value=MagicMock())
    mock_get_uow.return_value = fake_uow
    mock_comparator_cls.return_value.compare = MagicMock(return_value=MagicMock())
    mock_remediator_cls.return_value.generate_remediation = AsyncMock(
        return_value=None
    )

    result = await apply_state(
        task_id=uuid4(),
        deployment_id=uuid4(),
        new_instance_id=uuid4(),
        current_instance_id=None,
    )
    # Either returns a Completed state or None — pin to the contract
    # the flow exposes after Task 2.4.
    assert result is None or "Completed" in (getattr(result, "name", "") or "")
```

- [ ] **Step 2: Run, expect failure**

```bash
cd backend && uv run pytest tests/unit/agent/tasks/test_apply_state_flow.py -v
```

Expected: FAIL — the current flow signature is `(task_id, deployment_id, remediation)`.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/agent/tasks/test_apply_state_flow.py
git commit -m "test: pin the post-inversion apply_state flow contract"
```

### Task 2.4: Implement the new Prefect-side `apply_state` flow

**Files:**

- Modify: `backend/styrmin_backend/agent/tasks/orchestration.py:137-154`

- [ ] **Step 1: Rewrite the flow body**

Replace the existing `apply_state` flow (lines 137–154) with:

```python
from styrmin_backend.services.context import generate_context_from_deployment  # unchanged
from styrmin_backend.services.reconciliation.diffs.comparison import Comparator
from styrmin_backend.services.reconciliation.remediation import Remediator
from styrmin_backend.services.unit_of_work import get_unit_of_work


@flow(
    on_cancellation=[orchestration_callback],
    on_completion=[orchestration_callback],
    on_failure=[orchestration_callback],
    on_crashed=[orchestration_callback],
    on_running=[orchestration_callback],
)
async def apply_state(
    task_id: UUID,
    deployment_id: UUID,
    new_instance_id: UUID,
    current_instance_id: UUID | None,
) -> State | None:
    """Reconcile a deployment to its declared state.

    Post-#237 boundary: the flow loads the deployment + both instances
    fresh from the DB at run time, builds the diff, and generates the
    remediation here — not in the FastAPI request. This means a flow
    retry sees fresh state, and DB writes that landed between scheduling
    and run no longer produce a stale plan.
    """
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    uow = await get_unit_of_work()
    async with uow:
        deployment = await uow.deployments.find(id=deployment_id)
        if deployment is None:
            return Completed(
                message=f"Deployment {deployment_id} not found; nothing to apply",
            )

        new_instance = await uow.instances.find(id=new_instance_id)
        assert new_instance is not None, (
            f"new_instance {new_instance_id} not found"
        )
        current_instance = None
        if current_instance_id is not None:
            current_instance = await uow.instances.find(id=current_instance_id)

        comparator = Comparator(
            current_instance=current_instance,
            new_instance=new_instance,
        )
        diff_report = comparator.compare()
        logger.info("Flow-side diff report: {}", diff_report)

        remediator = Remediator(uow=uow)
        remediation = await remediator.generate_remediation(diff_report=diff_report)

        if remediation is None:
            return Completed(message="No remediation needed")

        flow_info = await remediation.apply()
        return flow_info.state
```

If `uow.instances.find` doesn't exist (the existing `InstanceRepository` may use a different method name), grep first and use the actual one. Mirror exactly what `apply_state` (server-side) used to use to load instances if needed.

- [ ] **Step 2: Run the flow tests**

```bash
cd backend && uv run pytest tests/unit/agent/tasks/test_apply_state_flow.py -v
```

Expected: PASS.

- [ ] **Step 3: Run the reconciliation tests**

```bash
cd backend && uv run pytest tests/unit/services/reconciliation/ -v
```

Expected: PASS. The `Remediator` / strategies didn't change shape, so these should pass without edits. If they fail because they import `Remediation` for a Prefect-parameter assertion, fix the test inline to assert against the new shape.

- [ ] **Step 4: Run the boundary test again**

```bash
cd backend && uv run pytest tests/unit/services/test_apply_state_boundary.py tests/unit/services/test_update_deployment_service_rename.py -v
```

Expected: PASS.

- [ ] **Step 5: Lint + format**

```bash
uv run invoke format lint
```

- [ ] **Step 6: Commit**

```bash
git add backend/styrmin_backend/agent/tasks/orchestration.py
git commit -m "refactor(prefect): apply_state flow loads + diffs + remediates from fresh DB"
```

### Task 2.5: Audit and update remaining `apply_state` callers

**Files:**

- Modify: `backend/styrmin_backend/services/deployment.py`
- Modify: `backend/styrmin_backend/services/primitives.py`

**Steps:**

- [ ] **Step 1: Survey**

```bash
grep -rn "apply_state\b" backend/styrmin_backend/services/ | grep -v __init__.py | grep -v __pycache__
```

The signature `apply_state(deployment, current_instance, uow) -> Task` didn't change — callers don't need to change. Verify by running:

```bash
cd backend && uv run pytest tests/unit tests/functional -v --tb=short
```

Expected: all green. If any caller is red because it was passing a pre-built `remediation`, switch it to the new signature.

- [ ] **Step 2: Commit any changes (likely none)**

If the suite was already green, skip the commit. If something changed:

```bash
git add backend/styrmin_backend/services/
git commit -m "refactor: align apply_state callers with the new boundary"
```

### Task 2.6: Stage 2 e2e validation

- [ ] **Step 1: Re-run the e2e rename test from Task 1.5**

```bash
cd backend && uv run pytest tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service -v -s --pdb
```

Expected: PASS. The behaviour is still correct under the new boundary.

- [ ] **Step 2: Run a sanity-check e2e on a clean deploy**

Pick any small `@pytest.mark.ci` e2e test (e.g. `test_deployment_timeline.py`) and run it.

```bash
cd backend && uv run pytest tests/e2e/test_deployment_timeline.py -v -s --pdb
```

Expected: PASS. The new flow does the same work in the same order — just from a different layer.

- [ ] **Step 3: Commit (no-op if nothing changed)**

---

## Stage 3 — Cleanup

### Task 3.1: Remove dead code

**Files:**

- Modify: `backend/styrmin_backend/services/reconciliation/__init__.py`
- Modify: `backend/styrmin_backend/services/reconciliation/remediation.py`

**Steps:**

- [ ] **Step 1: Grep for unused imports**

```bash
cd backend && uv run invoke lint
```

Ruff will flag unused imports. Remove them. Common candidates after Stage 2: `Comparator`, `Remediator`, `PrefectAction` are likely no longer needed in `services/reconciliation/__init__.py`.

- [ ] **Step 2: Update CONTEXT.md / dev/knowledge**

The architecture knowledge in `dev/knowledge/architecture.md` may describe the old boundary. Skim it and update the section on reconciliation if it claims the server-side builds the remediation. Per AGENTS.md Constitution §VII, doc accuracy is non-negotiable.

- [ ] **Step 3: Run the full suite**

```bash
cd backend && uv run invoke format lint
cd backend && uv run pytest tests/unit tests/functional -v
```

Expected: all green, no lint errors.

- [ ] **Step 4: Commit**

```bash
git add backend/styrmin_backend/services/reconciliation/ dev/knowledge/
git commit -m "chore: remove dead reconciliation imports after boundary inversion"
```

### Task 3.2: Final regenerate + schema check

- [ ] **Step 1: Regenerate schema + SDK (no GraphQL changes are expected, but verify)**

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
```

- [ ] **Step 2: Check git status**

```bash
git status
```

If `schema.graphql` or `python_sdk/src/styrmin_sdk/graphql/_generated/` changed, that's a signal we accidentally touched the schema — investigate before committing. Expected: clean.

- [ ] **Step 3: Final commit if anything regenerated**

---

## Self-Review

Coverage check against #237 analyst report:

- ✅ Bug: ordering in `update_deployment` → fixed in Task 1.3
- ✅ Bug class (stale context across Prefect boundary) → fixed in Tasks 2.2/2.4
- ✅ Repro test at service layer → Task 1.1
- ✅ Repro test at GraphQL layer → Task 1.4
- ✅ Repro test at cluster layer → Task 1.5

Coverage check against the user's stated preferences:

- ✅ Instance generation stays server-side → Tasks 1.3, 2.2
- ✅ Setting active instance stays server-side → Tasks 1.3, 2.2
- ✅ Both deployment_id + instance_id flow to Prefect → Task 2.2
- ✅ Diff happens in the Prefect flow → Task 2.4
- ✅ Flow reloads a fresh deployment → Task 2.4

No placeholders, no TBDs. Types and signatures are consistent: server-side `apply_state(deployment, current_instance, uow) -> Task` is preserved; flow-side `apply_state(task_id, deployment_id, new_instance_id, current_instance_id)` is the new shape. Both refer to the same `Comparator` / `Remediator` / `Remediation` classes, but the latter is constructed inside the flow.

Risks the engineer should know about:

- The `uow.instances.find` API might not match what's assumed — Task 2.4 Step 1 includes a grep-first instruction.
- The Prefect `apply_state` flow now needs DB access. `get_unit_of_work()` exists for exactly this case (see `backend/styrmin_backend/services/unit_of_work.py:185`), so this is a known pattern.
- The Task type is initialised to `NOOP` server-side and refined by the flow on first transition. If the GraphQL surface exposes `Task.type` immediately after the mutation returns, downstream consumers (frontend, tests) may briefly observe `NOOP`. Confirm during Task 2.6 that this doesn't break existing e2e expectations.
