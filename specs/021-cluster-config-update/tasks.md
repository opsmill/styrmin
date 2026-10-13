---
description: "Task list for the cluster config update (021-cluster-config-update)"
---

# Tasks: Update a Cluster's Config in Place

**Input**: Design documents from `specs/021-cluster-config-update/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required. The constitution (§V) requires tests for new functionality, a GraphQL propagation test for the new mutation, and E2E tests with local pass evidence. The spec's FR "Verified by" lines name the tests.

**Organization**: Tasks are grouped by user story. US1 and US2 are both P1; the shipped feature needs both. US3 is P2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1, US2 or US3 from spec.md
- Paths are relative to the repository root

## Working notes for every task

- Run `uv run invoke format lint` before each commit. In this emdash worktree, frontend `pnpm` commands need `--ignore-workspace`.
- `CONTEXT.md` has an uncommitted **Config fan-out** entry in the working tree from before this feature. Keep it and extend it in T046; do not discard it.
- Keep code comments to 1–3 lines; rationale goes in commit messages.
- Research decision references (D1–D12) point to [research.md](research.md).

---

## Phase 1: Setup

**Purpose**: Tooling ready for codegen and tests.

- [X] T001 Install dependencies with `uv sync` and `cd frontend && pnpm install --ignore-workspace`, then run `uv run invoke generate` once to confirm codegen works before any schema change (no file changes expected)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared helpers that US1 and US2 build on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 [P] Add public `resolve_instance_config(cluster: ClusterConfig, environment: EnvironmentConfig, deployment: DeploymentConfig) -> ResolvedConfig` in `backend/styrmin_backend/context/resolvers.py` that delegates to `_resolve_instance_config` (D1), and unit tests for it (override wins, `env_vars` per-key merge, cluster `scheduling` ignored) in `backend/tests/unit/context/test_resolve_instance_config.py`
- [X] T003 [P] Extract `_apply_cluster_defaults(config: dict) -> dict` (`ingress_class: traefik`, `runtime_class: default`) in `backend/styrmin_backend/services/clusters.py` and use it from `create_cluster`; existing cluster tests must still pass (`uv run pytest backend/tests -k cluster -q`)
- [X] T004 [P] Extract `_create_ingress_controller(environment_id, uow, created_by_user_id) -> Deployment` from `_ensure_ingress_controller` in `backend/styrmin_backend/services/deployment.py`, keeping `_ensure_ingress_controller`'s behaviour unchanged; run the existing ingress controller unit tests
- [X] T005 [P] Add `StandardStorageInput` and `FastStorageInput` (`storage_class: str`) to `backend/styrmin_backend/api/definitions/config/inputs.py`, one Strawberry input per Pydantic class (D2). Already present before this feature (added in `0271271d`, used by `UpdateDeploymentInput`); no code change, schema export unchanged

**Checkpoint**: Foundation ready.

---

## Phase 3: User Story 1 - Change a cluster config value without recreating the cluster (Priority: P1) 🎯 MVP

**Goal**: An administrator submits a full cluster config through GraphQL, the SDK or `styrminctl clusters update`; Styrmin saves it, recomputes capabilities, and redeploys every deployment whose resolved config changed.

**Independent Test**: Spec US1 Independent Test, through the unit, functional and CLI suites below (the E2E that also covers it is in Phase 4, T031).

### Tests for User Story 1 (write first, expect them to fail)

- [X] T006 [P] [US1] Unit tests for `update_cluster` in `backend/tests/unit/services/test_cluster_update.py`: cluster row committed before the first task is created (FR-001); value left out is cleared and `ingress_class`/`runtime_class` defaults apply (FR-005); `fqdn_suffix` added → ingress capability present in the returned cluster (FR-007); invalid config → `InvalidContextError` (`VALIDATION_ERROR`) and stored config unchanged (FR-008); clone in progress on any environment → `EnvironmentOperationInProgressError` and nothing saved, while an environment backup or restore in progress does not block (FR-006); unknown cluster → `ClusterNotFoundError`
- [X] T007 [P] [US1] Unit tests for the application fan-out in `backend/tests/unit/services/test_cluster_config_fanout.py`: environment A takes `ingress_class`, environment B overrides it → only A's deployment gets an `UPDATE_INSTANCE` task (FR-002, US1 scenario 1); resubmission → zero tasks (SC-003); forced dispatch failure on one deployment then resubmission → only that deployment gets a task; tombstoned, internal and `RESTORING` deployments skipped and counted; `standard_storage` change redeploys the deployments that take it (FR-003); a cluster `scheduling` change starts no redeploy; an instance generated by `generate_context_from_deployment` is found at config when the cluster config is unchanged (critique E7); one `cluster_config_fanout` log line with every count (FR-010, data-model §6)
- [X] T008 [P] [US1] GraphQL propagation test in `backend/tests/functional/graphql/test_cluster_update_propagation.py` per `dev/guides/graphql-propagation-tests.md` and `contracts/graphql.md`: every `UpdateClusterInput` field reaches `cluster.config` with snake_case keys; omitted field absent and defaults applied; recomputed `capabilities` returned and read back; lookup by `clusterId` and by `clusterName`; non-admin refused with the row unchanged (FR-009)
- [X] T009 [P] [US1] SDK test for `clusters.update` in `python_sdk/tests/test_clusters.py`: variables sent (`input` camelCased, `clusterId`/`clusterName`), result parsed, GraphQL error mapped to the typed SDK exception
- [X] T010 [P] [US1] CLI tests in `cli/tests/test_clusters.py` per `contracts/sdk-cli.md`: snake_case and camelCase files reach `sdk.clusters.update` as `UpdateClusterInput`; unknown top-level key and unknown nested key (`dedicated_ingress.servce`) refused before any SDK call, naming the key path; name and `--id` mutually exclusive and one required; success output includes the JSON config and the redeploy line; `clusters get` prints a config that `json.loads` accepts

### Implementation for User Story 1

- [X] T011 [US1] Create `backend/styrmin_backend/services/cluster_config_fanout.py` with a `FanOutCounts` dataclass (data-model §6), `_deployment_at_resolved_config(deployment, cluster_config, environment_config) -> bool` (D1: canonical `ResolvedConfig` dump comparison; no active instance or invalid stored config → `False`), and `fan_out_cluster_config(cluster, uow, acting_user_id) -> FanOutCounts` that, for each environment of the cluster, redeploys every live non-internal deployment not at config via `redeploy_for_environment_update` with a per-deployment `try/except` (`dispatch_failed`), counts `RESTORING` (`None` return) as `skipped_restoring`, commits, and logs `cluster_config_fanout` (D7). Leave a clearly named seam for the controller rules added in T025
- [X] T012 [US1] Add `update_cluster(uow, cluster_id, config, acting_user_id) -> Cluster` to `backend/styrmin_backend/services/clusters.py`: load cluster (`ClusterNotFoundError`), `guard_no_clone_occupying_environment` for each environment (D6), `_apply_cluster_defaults`, `validate_cluster_config` → `InvalidContextError`, set `config` and `capabilities = compute_cluster_capabilities(cluster)`, commit, then `fan_out_cluster_config` (D7); return the refreshed cluster
- [X] T013 [US1] Create `backend/styrmin_backend/api/definitions/cluster/inputs.py` with `UpdateClusterInput` (fields and description per `contracts/graphql.md`, reusing `DedicatedIngressInput`, `SchedulingInput`, `ExternalUrlScheme`, `ExternalDnsEndpointsType`, and T005's storage inputs) and `update_cluster_input_to_dict` built on `_convert_value` (top-level `None` omitted)
- [X] T014 [US1] Add the `update_cluster` mutation to `backend/styrmin_backend/api/schema/mutation.py` with `extensions=[_requires(Role.ADMIN)]`, arguments `input: UpdateClusterInput`, `cluster_id: UUID | None`, `cluster_name: str | None`; resolve via `resolve_cluster`, pass `info.context["current_user"].id` as `acting_user_id`, return `Cluster.from_instance`; confirm `backend/tests/unit/api/test_mutation_authz_coverage.py` passes
- [X] T015 [US1] Regenerate the schema with `uv run styrmin export graphql-schema schema.graphql` and check `schema.graphql` shows `UpdateClusterInput`, `StandardStorageInput`, `FastStorageInput` and `updateCluster`
- [X] T016 [US1] Add `python_sdk/src/styrmin_sdk/graphql/update_cluster.graphql` (operation in `contracts/graphql.md`), run `uv run invoke validate-graphql` and `uv run invoke generate`, add `ClusterResource.update(input, cluster_id=None, cluster_name=None)` in `python_sdk/src/styrmin_sdk/resources/clusters.py`, and export `UpdateClusterInput` from `python_sdk/src/styrmin_sdk/__init__.py`
- [X] T017 [US1] Add `validate_input_strict(model: type[BaseModel], data: Any) -> None` to `cli/src/styrminctl/output.py` (walk model fields recursively; accept field names and aliases; raise `ValueError` listing unknown key paths) (D3)
- [X] T018 [US1] Add `update` to `cli/src/styrminctl/commands/clusters.py` (`NAME` or `--id`, required `--config`; `parse_json_argument` → `validate_input_strict` → `UpdateClusterInput.model_validate` → `sdk.clusters.update`; print name, id, JSON config and the redeploy line pointing to `styrminctl deployments list`), and change `get` and `list` to print `config` with `json.dumps(..., sort_keys=True)` (critique P2, P3)
- [X] T019 [US1] Run T006–T010 to green: `uv run pytest backend/tests/unit/services/test_cluster_update.py backend/tests/unit/services/test_cluster_config_fanout.py backend/tests/functional/graphql/test_cluster_update_propagation.py python_sdk/tests/test_clusters.py cli/tests/test_clusters.py -v`

**Checkpoint**: The cluster config can be changed through all three surfaces; applications are redeployed by the resolved-config rule. Dedicated ingress changes are not yet ordered (US2), so do not ship without Phase 4.

---

## Phase 4: User Story 2 - Turn the cluster's dedicated ingress on or off and keep the applications reachable (Priority: P1)

**Goal**: Controller creation, redeploy and removal ordered around the applications, driven by the update call and the status reporter (D4, D5).

**Independent Test**: Spec US2 Independent Test; automated by T031.

### Tests for User Story 2 (write first, expect them to fail)

- [X] T020 [P] [US2] Unit tests for the controller actions and the per-application rule in `backend/tests/unit/services/test_ingress_controller_ordering.py`, one test per row of the D4 controller table and per application case: turn on with applications → controller created (attributed to the acting user), applications wait (`skipped_waiting_for_ingress`); controller values changed → controller redeployed, applications wait; controller `RUNNING` with the new values → applications redeployed now; controller `FAILED`, values unchanged, applications already on it → applications redeployed now, controller untouched; resubmission after a failed turn-on → controller redeployed again, applications on the shared class not moved; controller `DELETING` → no second controller, applications wait; turn off → applications redeployed now; environment with its own `dedicated_ingress` → nothing changes (US2 scenario 4); environment with no applications → no controller (US2 scenario 5); file without `dedicated_ingress` → turned off (US2 scenario 6)
- [X] T021 [P] [US2] Unit tests for the extended removal rule in `backend/tests/unit/services/test_ingress_controller_ordering.py` (separate test class): not removed while an application is `PENDING`/`DEPLOYING` or still has `dedicated_ingress` in its active instance; not removed while the controller is `PENDING`/`DEPLOYING` (critique E3); removed once all applications are off it and settled; existing "last application deleted" rule unchanged; an environment update that turns the environment's own `dedicated_ingress` off leads to removal after the applications move (critique E2)
- [X] T022 [P] [US2] Unit tests for the status reporter hooks in `backend/tests/unit/services/test_deployment_status_fanout_hooks.py`: internal deployment → `RUNNING` runs `continue_environment_fan_out` for its environment and redeploys the waiting applications; internal → `FAILED` and application → `RUNNING`/`FAILED` run the removal check; no hook runs when the state does not change; an exception in the continuation is logged, rolled back to the savepoint, and the status snapshot and state still commit; `cluster_config_fanout_continued` log line emitted with counts

### Implementation for User Story 2

- [X] T023 [US2] Extend `tear_down_unused_ingress_controller` in `backend/styrmin_backend/services/deployment.py` with the second removal condition (data-model §4 removal rule: effective `dedicated_ingress` off, every live application's active instance without `dedicated_ingress`, no application `PENDING`/`DEPLOYING`, controller not `PENDING`/`DEPLOYING`), keeping the existing deletion path (DELETING, born-complete delete task, delete steps)
- [X] T024 [US2] Add `_effective_dedicated_ingress(environment, cluster_config)` and the controller action function in `backend/styrmin_backend/services/cluster_config_fanout.py` (D4 controller table: create via `_create_ingress_controller`, redeploy via `redeploy_for_environment_update` when values differ or when `FAILED` with waiting applications, nothing when `DELETING`); count `ingress_controllers_created`/`ingress_controllers_redeployed`
- [X] T025 [US2] Apply the per-application rule in the fan-out loop of `backend/styrmin_backend/services/cluster_config_fanout.py`: an application whose resolved `dedicated_ingress` changes to a set value is redeployed only when the controller is `RUNNING` with that value, otherwise counted `skipped_waiting_for_ingress`; all other differing applications redeployed now; run the removal check (T023) at the end of each environment and count `ingress_controllers_removed`
- [X] T026 [US2] Add `continue_environment_fan_out(environment_id, uow, trigger_deployment_id) -> FanOutCounts` in `backend/styrmin_backend/services/cluster_config_fanout.py` (same per-environment evaluation, no controller creation since no acting user; logs `cluster_config_fanout_continued`)
- [X] T027 [US2] Call the hooks from `report_deployment_statuses` in `backend/styrmin_backend/services/deployment_status.py` only on a state change: internal → `RUNNING` runs `continue_environment_fan_out`; internal → `FAILED` and non-internal → `RUNNING`/`FAILED` run `tear_down_unused_ingress_controller`; wrap each call in `uow.session.begin_nested()` with a logged broad `except`, like `_record_operator_steps` (D7)
- [X] T028 [US2] Run T020–T022 and the full backend unit suite to green: `uv run invoke test`

### E2E for User Stories 1 and 2

- [X] T029 [P] [US2] Move `_ingress_controller_ids`, `_wait_for_deployment_status`, `_wait_for_traefik_pod` and `_wait_for_namespace_gone` from `backend/tests/e2e/test_ingress_controller.py` to `backend/tests/e2e/helpers/ingress.py` (public names) and update the imports in `test_ingress_controller.py`
- [X] T030 [US2] Add a helper in `backend/tests/e2e/helpers/ingress.py` that waits until no deployment of a cluster (all environments, internal included) is `PENDING` or `DEPLOYING`, and a helper that returns a deployment's tasks with their creation and end timestamps for ordering assertions
- [X] T031 [US2] Create `backend/tests/e2e/test_cluster_update.py` with module markers `shard_compute`, and `test_cluster_update_redeploys_and_moves_dedicated_ingress` marked `e2e`, `ci`, `api_only(reason=...)` implementing the four phases of D10 on environments A (`config={}`) and B (`ingress_class: traefik`) with one `simple-app` each created through `client.deployments.create`: (1) `dedicated_ingress` off → applications moved, A's controller removed only after A's application redeploy finished, A's Ingress has `ingressClassName: traefik` and no dedicated annotation; (2) `ingress_class: nginx` → A's application gets a task and its Ingress has `ingressClassName: nginx`, B's application gets none; (3) original session config → A's controller created, A's application redeploy created after the controller task finished, application answers through A's controller via port-forward and HTTP; (4) same config again → no new task on A's or B's application. `finally`: resubmit the original session config, wait for the cluster to settle (T030), delete A and B. Docstring states that the vCluster has no shared ingress controller, so the shared-class check is on the Ingress resource
- [X] T032 [US2] Build the server image (`docker compose build server`), then run `sleep infinity | uv run pytest "backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress" -k api-chromium -v -s --pdb 2>&1 | tee /tmp/cluster-update-api.log` until it passes; debug with `kubectl` against the paused vCluster
- [X] T033 [US2] Run the whole shard once for the API variant to check the restore and settle wait: `uv run pytest backend/tests/e2e -m shard_compute -k api-chromium -v`
- [X] T034 [US2] Record local pass evidence (node id, command, ISO 8601 timestamp, vCluster id and kubeconfig path, verbatim `PASSED` line) for T032 and T033 in `specs/021-cluster-config-update/e2e-evidence.md`

**Checkpoint**: P1 complete — US1 and US2 work together and the P1 E2E passes locally.

---

## Phase 5: User Story 3 - Edit the cluster config from the cluster detail page (Priority: P2)

**Goal**: An administrator edits the cluster config in a dialog on the cluster detail page; values the form does not show are kept (D11).

**Independent Test**: Spec US3 Independent Test; automated by T035 and T042.

### Tests for User Story 3 (write first, expect them to fail)

- [X] T035 [P] [US3] Vitest tests in `frontend/src/__tests__/EditClusterDialog.test.tsx`: prefilled from `cluster.config`; changing only the FQDN suffix submits an `UpdateClusterInput` that keeps `dedicatedIngress`, `scheduling`, `nodeSelector`, `dbSize`, `backupTtl` and both storage classes unchanged; validation errors block submission; the mutation error is shown; the Edit button is absent for a user whose `effectiveRole` is not `ADMIN`

### Implementation for User Story 3

- [X] T036 [P] [US3] Add `frontend/src/graphql/update_cluster.graphql` (same operation as the SDK) and regenerate `frontend/src/generated/graphql.ts` with `uv run invoke generate` (or `pnpm --ignore-workspace codegen` in `frontend/`)
- [X] T037 [US3] Extract the config fields and the Zod schema of `frontend/src/pages/settings/CreateClusterDialog.tsx` into `frontend/src/components/cluster/ClusterConfigFields.tsx` (fields component, schema, `configToFormValues` and `formValuesToConfig` helpers) and make `CreateClusterDialog` use it; existing create-dialog tests must still pass
- [X] T038 [US3] Create `frontend/src/pages/clusters/EditClusterDialog.tsx`: prefill from `cluster.config` via `configToFormValues`, on submit merge the form values over the stored config (so unseen keys and unseen `dedicated_ingress.service` fields are carried through), map to `UpdateClusterInput` (camelCase keys, enum values), call `useUpdateClusterMutation`, invalidate the cluster query, close on success, show the error otherwise
- [X] T039 [US3] Add an Edit button that opens `EditClusterDialog` to `frontend/src/pages/clusters/ClusterDetailPage.tsx`, shown only when `useAuth().effectiveRole === "ADMIN"`
- [X] T040 [US3] Run `cd frontend && pnpm --ignore-workspace test` and `pnpm --ignore-workspace lint` to green
- [X] T041 [P] [US3] Add `open_edit_dialog()`, `set_fqdn_suffix(value)` and `save()` to `backend/tests/e2e/pages/cluster_detail.py`
- [X] T042 [US3] Add `test_edit_cluster_config_from_detail_page` to `backend/tests/e2e/test_cluster_update.py`, marked `e2e`, `ci`, `ui_only(reason=...)`: sign in as admin, change only the FQDN suffix in the dialog, read the stored config through the SDK (new suffix; `dedicated_ingress`, `standard_storage`, `fast_storage`, `external_dns_endpoints_type` unchanged); `finally` resubmit the original session config through the SDK and wait for the cluster to settle (T030)
- [X] T043 [US3] Run `sleep infinity | uv run pytest "backend/tests/e2e/test_cluster_update.py::test_edit_cluster_config_from_detail_page" -k ui-chromium -v -s --pdb 2>&1 | tee /tmp/cluster-update-ui.log` until it passes (in its own session, separate from the API variant)
- [X] T044 [US3] Append the local pass evidence for T043 to `specs/021-cluster-config-update/e2e-evidence.md`

**Checkpoint**: All three stories work and both E2E tests have local pass evidence.

---

## Phase 6: Documentation and Polish

**Purpose**: Constitution §VII — documentation in the same change.

- [X] T045 [P] Write `dev/adr/0066-cluster-config-fanout.md` (MADR, `Status: Accepted`): resolved-config comparison (D1) and why ADR-012's slice comparison does not apply; readiness ordering through the status reporter and the per-application rule (D4); removal rule and its effect on the environment update (D5); typed input and the `createCluster` JSON asymmetry (D2); CLI strict-key guard (D3); consequences including the upgrade-triggered redeploys and the dispatch-before-commit window (D7)
- [X] T046 [P] Extend the **Config fan-out** entry in `CONTEXT.md` (keep the existing uncommitted environment text) to cover the cluster case: compared on the resolved config, ordered around the dedicated ingress controller, link ADR-0066
- [X] T047 [P] Update `dev/knowledge/architecture.md` §3.5 so it describes how a cluster config change now reaches the deployments (the cluster config fan-out and its status reporter continuation)
- [X] T048 [P] Update the Cluster section of `dev/knowledge/backend/data-models.md`: config replaced by `updateCluster`, capabilities recomputed, no migration
- [X] T049 [P] Add a `clusters update` section to `docs/docs/reference/styrminctl.md`: synopsis, the file is the whole current config (last update wins), unknown keys refused, which deployments are redeployed, how to revert (resubmit the previous file), `clusters get` prints JSON, the StatefulSet storage class limit and its recovery
- [X] T050 [P] Update `docs/docs/concepts-and-architecture/ingress-and-networking.md`: what happens when `dedicated_ingress` changes at the cluster (controller ready before applications move; removed after they move; failed or removed controller cases) and the new removal after an environment update turns its own `dedicated_ingress` off
- [X] T051 [P] Update `docs/docs/concepts-and-architecture/reconciliation.md` to name the cluster config fan-out next to the environment one
- [X] T052 [P] Add towncrier fragments: `uv run towncrier create -c "..." 423.added.md` (update a cluster's config with `styrminctl clusters update`, the SDK, GraphQL and the cluster detail page) and `uv run towncrier create -c "..." +env-update-removes-ingress-controller.changed.md` (environment update now removes the dedicated ingress controller after its applications move off it); check wording against `dev/guidelines/changelog.md`
- [X] T053 Run the full local gate: `uv run invoke format lint`, `uv run invoke validate-graphql`, `uv run invoke test`, `cd frontend && pnpm --ignore-workspace lint && pnpm --ignore-workspace test`; confirm `uv run invoke generate` leaves no diff
- [X] T054 Walk through `specs/021-cluster-config-update/quickstart.md` sections 1, 2 and 4 against the dev stack (`uv run invoke dev`) and fix any step that does not match

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** → **Foundational (Phase 2)** → user stories.
- **US1 (Phase 3)** depends on Phase 2.
- **US2 (Phase 4)** depends on US1's fan-out module (T011) and service (T012); the E2E (T031) depends on all of US1 and US2.
- **US3 (Phase 5)** depends on US1's mutation and schema (T014, T015) only; its E2E (T042) reuses T030 and the module from T031.
- **Documentation (Phase 6)** can start once D-decisions are implemented; T053–T054 run last.

### Within Each User Story

- Tests first (they fail), then services, then API, then SDK and CLI.
- T015 (schema export) before T016 (SDK codegen) and T036 (frontend codegen).
- T023 before T025 (the fan-out calls the removal check); T026 before T027.

### Parallel Opportunities

- Phase 2: T002, T003, T004, T005 touch different files.
- US1 tests: T006, T007, T008, T009, T010 in parallel.
- US2 tests: T020, T021, T022 in parallel; T029 in parallel with the US2 implementation.
- US3: T035, T036 and T041 in parallel; US3 front-end work can run in parallel with US2 once T015 is done.
- Phase 6: T045–T052 in parallel.

## Parallel Example: User Story 1

```text
Task: "T006 Unit tests for update_cluster in backend/tests/unit/services/test_cluster_update.py"
Task: "T007 Unit tests for the application fan-out in backend/tests/unit/services/test_cluster_config_fanout.py"
Task: "T008 GraphQL propagation test in backend/tests/functional/graphql/test_cluster_update_propagation.py"
Task: "T009 SDK test in python_sdk/tests/test_clusters.py"
Task: "T010 CLI tests in cli/tests/test_clusters.py"
```

## Parallel Example: User Story 2

```text
Task: "T020 Controller action and per-application tests in backend/tests/unit/services/test_ingress_controller_ordering.py"
Task: "T022 Status reporter hook tests in backend/tests/unit/services/test_deployment_status_fanout_hooks.py"
Task: "T029 Move the E2E ingress helpers to backend/tests/e2e/helpers/ingress.py"
```

## Implementation Strategy

### MVP

The smallest shippable increment is **US1 + US2** (both P1): US1 alone would move applications onto a dedicated ingress controller that is not ready when `dedicated_ingress` changes. Stop after Phase 4 and validate with T032–T034.

### Incremental Delivery

1. Phases 1–2: foundation.
2. Phase 3 (US1): change any value; verify with unit, propagation, SDK and CLI tests.
3. Phase 4 (US2): ordered dedicated ingress; P1 E2E with local evidence → shippable.
4. Phase 5 (US3): edit dialog and UI E2E.
5. Phase 6: documentation and the full gate (documentation is required before the change is done, not optional polish).

## Notes

- Commit after each task or logical group, with Conventional Commit messages.
- Do not edit generated files by hand: `schema.graphql`, `python_sdk/src/styrmin_sdk/graphql/_generated/`, `frontend/src/generated/graphql.ts`, `CHANGELOG.md`.
- E2E: one variant per pytest session; build the server image before the first run.
