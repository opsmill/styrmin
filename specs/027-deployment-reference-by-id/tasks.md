---

description: "Task list for storing the id of the deployment that an affinity term names"
---

# Tasks: Deployment References Stored by Id

**Input**: Design documents from `specs/027-deployment-reference-by-id/` ([plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md), [critique](critiques/critique-20261016.md))

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: required. Constitution §V asks for tests of new behaviour, a GraphQL propagation test for the changed input, and E2E coverage of the user-visible flows run to a local PASS.

**Organization**: tasks are grouped by user story. The binding (Phase 3, US2) is the mechanism that US1, US3, US4 and US8 rely on, so it comes first even though all four are P1 or P2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US8 (spec user stories)
- Paths are relative to the repository root

## Rules that apply to every task

- Keep code comments to one to three lines; put the reasoning in the commit message.
- After each task group, run `uv run invoke format lint` (with `export npm_config_ignore_workspace=true` in this worktree) and commit with a Conventional Commit message that ends with the `Co-Authored-By` line.
- Use the terms of [`CONTEXT.md`](../../CONTEXT.md): affinity term, deployment reference, counterpart deployment, tombstoned deployment.

## E2E run rules (apply to every E2E task)

- Build the server image once before the first session: `docker compose build server`.
- One CI shard per pytest session, and `api-chromium` and `ui-chromium` in separate sessions.
- Run with `--pdb`. From a non-interactive shell, prefix the command with `sleep infinity |` and stop the run by PID, never with `pkill -f`.
- Record each passing run in `specs/027-deployment-reference-by-id/e2e-evidence.md`: the pytest node id, the exact command, the ISO 8601 time of the passing run, the vcluster id and kubeconfig path under `/tmp/pytest-of-*/pytest-*/`, and the verbatim `PASSED` line (Constitution §V).

---

## Phase 1: Setup

**Purpose**: a green baseline before any change.

- [X] T001 Run `uv sync`, then `uv run pytest backend/tests/unit/services/test_scheduling_validator.py backend/tests/unit/services/backup/test_environment_clone_service.py backend/tests/unit/services/backup/test_environment_backup.py backend/tests/functional/test_api_scheduling_config.py backend/tests/functional/graphql/test_environment_clone.py backend/tests/functional/graphql/test_deployment_noop_propagation.py -q` and note the results as the baseline in the commit message of T002 (no file change)

---

## Phase 2: Foundational (blocks every story)

**Purpose**: the reference helpers, the error types and the reconcile-time resolver that every story uses.

- [X] T002 [P] Add `deleted: bool = False` to `UnresolvableAffinityReferenceError` in `backend/styrmin_backend/services/exceptions.py` (message "Affinity term at <path> names deployment <name> (<id>), which was deleted" when set; `error_metadata` adds `deleted: True` only when set) and add `UnclonedReference` (dataclass: `deployment_id: UUID`, `deployment_name: str | None`, `paths: list[str]`) and `UnclonedDeploymentReferenceError(ServiceError)` with `error_code = "VALIDATION_ERROR"`, `default_message = "An affinity term names a deployment that the clone does not copy"`, a message that lists the names, and `error_metadata = {"deployments": [{"deployment_id": str, "deployment_name": ..., "paths": [...]}]}`; re-export the new error in `backend/styrmin_backend/context/exceptions.py` next to the existing one (contracts/graphql-and-errors.md)
- [X] T003 [P] Unit tests for T002 in `backend/tests/unit/services/test_scheduling_reference_errors.py`: message and metadata with and without `deleted`; metadata of `UnclonedDeploymentReferenceError` for two deployments with two paths each
- [X] T004 Create `backend/styrmin_backend/services/scheduling/references.py` (plan D-001): `ReferenceSite`, `iter_reference_sites(config, path_prefix)` over `scheduling.{pod_affinity,pod_anti_affinity}.{required[i],preferred[i].term}.deployment_ref`, `referenced_deployment_ids(config, path_prefix) -> dict[UUID, list[str]]`, `remap_deployment_references(config, mapping) -> tuple[dict | None, dict[UUID, list[str]]]` (deep copy, never mutates the input), and `async bind_deployment_references(uow, environment_id, config, *, path_prefix, upcoming_deployments=None)` with the rules of research R-001 and R-002: a name matches an upcoming deployment first, then `uow.deployments.get_by_name(name, environment_id)` unless the row found is an upcoming deployment under its old name; an id is accepted when upcoming, else `uow.deployments.find(id)` must be in `environment_id` and not tombstoned (tombstoned raises with `deleted=True` and the row's name); `environment_id=None` matches upcoming deployments only; output reference is `{"deployment_id": str(UUID(...)), "components": [...]}` with `components` only when given; the first failing term raises `UnresolvableAffinityReferenceError` with its full path
- [X] T005 Create `backend/tests/unit/services/scheduling/__init__.py` and unit tests in `backend/tests/unit/services/scheduling/test_references.py` for T004, with an in-memory unit of work as in `backend/tests/unit/services/test_scheduling_validator.py`: name to id at `required` and `preferred`; uppercase id canonicalised; `components` kept; missing name, other environment, tombstoned id (with last name and `deleted`); upcoming name and upcoming id; renamed upcoming deployment's old name refused; `environment_id=None`; node affinity untouched; input not mutated; remap with mutual references and an unmapped id reported with its path; a bound config unchanged by `EnvironmentConfig.model_validate(c).model_dump(exclude_none=True, mode="json")` (critique E8)
- [X] T006 Change the resolver in `backend/styrmin_backend/services/scheduling/validator.py` (plan D-004): `resolve_deployment_reference(..., upcoming_deployments=None)` reads ids only (a reference with `deployment_name` raises `UnresolvableAffinityReferenceError` with the name), accepts an upcoming id without a lookup, and refuses a tombstoned row with `deleted=True` and its name; `expand_deployment_references(..., *, path_prefix="scheduling", upcoming_deployments=None)` uses the prefix in every path
- [X] T007 Expand each level before the merge in `_populate_component_scheduling` in `backend/styrmin_backend/services/context.py`: expand the environment level once with prefix `environment.config.scheduling`, the deployment level once with `deployment.config.scheduling`, and each component with `component[<name>].config.scheduling`, then call `_resolve_scheduling_config`; add `upcoming_deployments` to `generate_context_from_deployment` and pass it down; do the same per-level expansion in the `resolvedScheduling` resolver in `backend/styrmin_backend/api/definitions/deployment/model.py` (L455-523)
- [X] T008 Add `upcoming_deployments: Mapping[UUID, str] | None = None` to `generate_instance_from_deployment` in `backend/styrmin_backend/services/reconciliation/__init__.py` and pass it to `generate_context_from_deployment`; add an optional `id: UUID | None = None` to `Deployment.create` in `backend/styrmin_backend/domain/models.py`
- [X] T009 Update `backend/tests/unit/services/test_scheduling_validator.py` for T006 and T007: `test_resolves_by_name` expects a refusal; new tests for a tombstoned id (last name, `deleted`), an upcoming id, and per-level paths (an environment-level term in error gives `environment.config.scheduling.pod_anti_affinity.preferred[0].term`); update every other test that writes the name of a deployment that does not exist, found with `grep -rn "deployment_name" backend/tests/unit backend/tests/functional | grep -iv "snapshot\|backup\|clone"`, including `backend/tests/functional/test_api_scheduling_config.py::test_accepts_anti_affinity_with_deployment_ref` (L49-63): create the named deployment first or expect the refusal (critique E7)

**Checkpoint**: references can be found, bound and remapped; reconcile reads ids only.

---

## Phase 3: User Story 2 - Give a name when writing a term (Priority: P1) 🎯 MVP

**Goal**: every write stores the id of the deployment a term names.

**Independent Test**: write `deployment_name: A` in the environment's and a deployment's config, and deploy a driver version whose component definition names A; read each config back and get `deployment_id: <A's id>`.

- [X] T010 [US2] In `deploy_application` in `backend/styrmin_backend/services/deployment.py` (plan D-002): add `deployment_id: UUID | None = None` and `upcoming_deployments: Mapping[UUID, str] | None = None`; compute `new_id = deployment_id or uuid4()` and pass it to `Deployment.create(id=new_id, ...)`; after the name is resolved (L1648-1668) bind `deployment_config` with prefix `deployment.config` and `{**(upcoming_deployments or {}), new_id: resolved_name}`; bind each component config copied from the driver version (L1687-1692) with prefix `component[<name>].config`; pass `upcoming_deployments` with the new deployment added to `generate_instance_from_deployment` (L1714)
- [X] T011 [US2] In `update_deployment` in `backend/styrmin_backend/services/deployment.py`: after the rename and config assignment (L609-613) and before the save at L655, set `deployment.config = await bind_deployment_references(uow, deployment.environment_id, deployment.config, path_prefix="deployment.config", upcoming_deployments={deployment.id: deployment.name})`
- [X] T012 [US2] In `update_deployment_version` in `backend/styrmin_backend/services/deployment.py`: after the name is validated (L970-974), bind `effective_config` with `{deployment.id: new_name}`, and bind each component config re-copied in `set_components` (L1028-1037) with prefix `component[<name>].config`; both before `deployment.config = effective_config` (L1066) and the no-op comparison (L1106-1110)
- [X] T013 [US2] In `backend/styrmin_backend/services/environments.py` (plan D-003): `create_environment` gains `upcoming_deployments: Mapping[UUID, str] | None = None` and binds `config` with `environment_id=None` and prefix `environment.config` after the shape check (L203-208); `update_environment` binds `config` against `environment_id` after L352 and before `environment.config = config` (L357)
- [X] T014 [US2] Add descriptions to `DeploymentReferenceInput` and its `deployment_id` and `deployment_name` fields in `backend/styrmin_backend/api/definitions/config/inputs.py` (L100-106), with the text of contracts/graphql-and-errors.md; then run `uv run styrmin export graphql-schema schema.graphql` and `uv run invoke generate` (with `npm_config_ignore_workspace=true`); stage `schema.graphql`, `python_sdk/src/styrmin_sdk/graphql/_generated/` and `frontend/src/generated/` before `uv run invoke lint`
- [X] T015 [P] [US2] Unit tests in `backend/tests/unit/services/test_deployment_reference_binding.py` (plan D-002): `deploy` with a name stores the id; `deploy` of A with a term that names A stores A's new id (FR-007); `updateDeployment` that renames B to B2 with a term that names B2 stores B's id, and a term that names the old name B is refused; `updateDeploymentVersion` with a name stores the id; component configs copied from the driver version store the id
- [X] T016 [P] [US2] GraphQL propagation rows (dev/guides/graphql-propagation-tests.md): `deploymentRef.deploymentName` sent through `deploy` in `backend/tests/functional/graphql/test_deploy_input_propagation.py`, through `updateDeployment` in `backend/tests/functional/graphql/test_update_deployment_input_propagation.py`, through `updateDeploymentVersion` in `backend/tests/functional/graphql/test_update_deployment_version_input_propagation.py`, and through `updateEnvironment` in `backend/tests/functional/graphql/test_environment_update_propagation.py`; each asserts the database row's config holds `deployment_id` with the named deployment's id and no `deployment_name`, and that the GraphQL `config` read returns the same

**Checkpoint**: names given on write are stored as ids at every write.

---

## Phase 4: User Story 3 - A term that names a missing deployment is refused when written (Priority: P1)

**Goal**: a write that names a deployment the environment does not have is refused with the term's path and saves nothing.

**Independent Test**: `updateEnvironment` with a term that names a missing deployment returns `VALIDATION_ERROR` with the path, and the environment's config is unchanged.

- [X] T017 [P] [US3] Functional tests in `backend/tests/functional/graphql/test_environment_update_propagation.py`: `updateEnvironment` with a term that names a missing deployment is refused with `extensions.code == "VALIDATION_ERROR"` and `extensions.path == "environment.config.scheduling.pod_anti_affinity.preferred[0].term"`, and the stored config is unchanged; `createEnvironment` with any term that names a deployment is refused and no environment is created
- [X] T018 [P] [US3] Functional tests in `backend/tests/functional/graphql/test_update_deployment_input_propagation.py`: `updateDeployment` with a term that names a missing deployment, and one that gives the id of a deployment of another environment, are refused with the path, and the deployment's stored config and name are unchanged (FR-002, research R-006)

**Checkpoint**: refusals happen at write time with the term's path.

---

## Phase 5: User Story 1 - Rename a deployment that affinity terms name (Priority: P1)

**Goal**: a rename leaves the terms that name the deployment working, and restarts no pod.

**Independent Test**: B's config and E's config name A by name; rename A; update B and E; every write succeeds and B's `resolvedScheduling` still selects A's id.

- [ ] T019 [US1] Functional scenario tests in new `backend/tests/functional/graphql/test_deployment_reference_scenarios.py` (spec US1 scenarios 1 to 4): set up E with A and B, a pod affinity term in B's config and a pod anti-affinity term in E's config written with `deploymentName: A`; rename A to A2 with `updateDeployment` (succeeds; before the change it failed because the rename built a new instance with E's term); `updateDeployment` on B succeeds; `updateEnvironment` on E with a changed env var reports no failed redeploy (`fan_out_environment_config` result `dispatch_failed == 0`, or the log counter the existing fan-out tests read); B's `resolvedScheduling` gives `styrmin/deployment_id=<A's id>`; B's stored config is unchanged by the rename (FR-010)
- [ ] T020 [US1] Extend `test_pod_anti_affinity_cross_deployment_via_graphql` in `backend/tests/e2e/test_pod_scheduling.py` (research R-013): write A's term with `DeploymentReferenceInput(deploymentName=<B's name>)` and assert A's stored config gives B's id; record A's pod uids, rename B with `updateDeployment(deploymentName=...)`, wait for B to run, and assert A's pod uids are unchanged; write A's config back as read and assert the `Task` is null; update A with a changed env var, wait for `running`, and assert the rendered pod template still selects `styrmin/deployment_id=<B's id>` with `_wait_for_pod_template`; in the cleanup, rename B back to `scheduling-b` in a `finally` block; keep the `api_only` marker and update its `reason=` and the docstring
- [ ] T021 [US1] Run T020 per the E2E run rules: `sleep infinity | uv run pytest "backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql" -m "ci and shard_compute" -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-scheduling.log`; record the PASS evidence in `specs/027-deployment-reference-by-id/e2e-evidence.md`

**Checkpoint**: #492 is fixed and observed in a real cluster.

---

## Phase 6: User Story 5 - An environment clone points the copied terms at the counterparts (Priority: P1)

**Goal**: every term in a clone names the counterparts, in any snapshot order and with mutual terms.

**Independent Test**: clone E with A and B selected, where B's config and E's config name A; the terms in E2 give the id of A's counterpart.

- [ ] T022 [US5] Add `order_counterparts(snapshots, environment_config)` to `backend/styrmin_backend/services/backup/clone.py` (plan D-007, critique E1): each counterpart after the ones its terms name; among those that can come next, the ones named by the environment config first, then source-name order; a cycle is broken in source-name order. Pure function
- [ ] T023 [US5] In `backend/styrmin_backend/workflows/templates/clone.py` (plan D-007): build `counterpart_ids = {snapshot.deployment_id: uuid4()}` for the usable snapshots and `upcoming = {counterpart_ids[s.deployment_id]: s.deployment_name}`; in `_create_cloned_environment`, remap the merged config with `remap_deployment_references` and call `create_environment(..., config=remapped, upcoming_deployments=upcoming)`; in `_create_counterpart`, remap `snapshot.config` and call `deploy_application(..., deployment_id=counterpart_ids[...], deployment_config=remapped, upcoming_deployments=<upcoming without failed counterparts>)` and return the given id instead of reading back by name; run the counterpart loop in `order_counterparts` order; an unmapped id returned by the remap fails the counterpart (or, for the environment config, writes the fatal error of T027)
- [ ] T024 [P] [US5] Unit tests for `order_counterparts` in `backend/tests/unit/services/backup/test_environment_clone_service.py`: chain, environment-named first, the conflict case of critique E1 (environment names A and A names B gives B then A), cycle in name order
- [ ] T025 [US5] Functional tests with the real flow in `backend/tests/functional/graphql/test_environment_clone.py` (via `_run_clone_flow`, L906-960): A names B, run with A's snapshot first and with B's first (patch the snapshot order); A and B name each other; E's config names A; in each case both entries are `CLONED`, the terms in the new environment's config and in the counterparts' configs give counterpart ids, and `referenced_deployment_ids` of every config in the new environment contains no source id (FR-008, SC-003); the counterpart's id equals the id in `counterpart_deployment_id`

**Checkpoint**: clones of environments whose terms name their deployments complete.

---

## Phase 7: User Story 6 - A clone request that leaves out a named deployment is refused (Priority: P2)

**Goal**: the request is refused before anything is created; failures during the clone cascade to the counterparts that name the failed deployment.

**Independent Test**: clone E with only B selected, where B's config names A, and get the refusal that lists A and the term's path.

- [ ] T026 [US6] Add `find_uncloned_references(...)` (pure) to `backend/styrmin_backend/services/backup/clone.py` and call it in `clone_environment` before the clone row is created (L1336), per plan D-006 and research R-007: bind `canonical_override` against the source environment with prefix `config_override` and store the bound override; merge with `merge_environment_config`; take the copied deployments as the `PENDING` entries of `_plan_deployment_results`; collect ids from the merged environment config and each copied deployment's config; for components, check each copied deployment's driver version component definitions by name against the copied deployments' names and by id against their ids (critique X1); raise `UnclonedDeploymentReferenceError` with names from the roster (last name for a tombstoned deployment)
- [ ] T027 [US6] In `backend/styrmin_backend/workflows/templates/clone.py` and `backend/styrmin_backend/services/backup/clone.py` (plan D-007): add `CLONE_STEP_REFERENCED_DEPLOYMENT_NOT_CLONED = "referenced_deployment_not_cloned"` to `CLONE_STEPS` and `CLONE_REASON_REFERENCED_DEPLOYMENT_NOT_CLONED = "an affinity term names deployment {name}, which was not cloned"`; add `cascade_reference_failures(snapshots, failed_ids)`; after `_classify_captured_constituents`, cascade the capture failures and attribute them; when the merged environment config names a failed deployment, write the fatal error, `_fail_pending`, and create no environment; in the counterpart loop, fail a counterpart whose config names a failed counterpart without creating it and log `env_clone_reference_not_cloned environment_clone_id=… deployment_id=… named_deployment_id=…` (critique E4); when a counterpart named by the environment config fails, write the fatal error and fail the remaining pending entries
- [ ] T028 [P] [US6] Unit tests in `backend/tests/unit/services/backup/test_environment_clone_service.py`: request refused when the named deployment is not selected, when it is selected but not eligible, when the environment config names it, when the override names it (by name), and when a driver component definition names a deployment that no copied deployment has by name; accepted when `cleared_config_fields` clears `scheduling` or `config_override` replaces it; no clone row, backup or dispatch on refusal; `cascade_reference_failures` with a chain; flow harness: A's capture fails, B (names A) is attributed `FAILED` with the new reason and C is `CLONED`, so the status is `PARTIAL`; E's config names A and A's capture fails, so the clone has the fatal step, no environment, and status `FAILED`
- [ ] T029 [P] [US6] Functional test in `backend/tests/functional/graphql/test_environment_clone.py`: `cloneEnvironment` with a selection that leaves out a named deployment returns `extensions.code == "VALIDATION_ERROR"` with `extensions.deployments[0].deployment_name` and `paths`; the mutation stays `ADMIN`-only (existing `test_clone_environment_requires_admin` unchanged)
- [ ] T030 [US6] Extend `test_environment_clone_lifecycle` in `backend/tests/e2e/test_backup_restore.py` (research R-013; covers US5 and US6): after the peer runs, give it a preferred pod affinity term (weight 1, `kubernetes.io/hostname`) that names the primary by name through `client.deployments.update`, wait for it to run, and assert its stored config gives the primary's id; assert that `client` clone request selecting only the peer raises the SDK error for `UnclonedDeploymentReferenceError` listing the primary and the peer's term path, and that `environmentClones` gained no record; select both deployments in the clone; change the attribution, capture and counterpart assertions to two `CLONED` entries (the not-selected `SKIPPED` reason stays asserted by the re-clone with `deployment_ids=[]`); assert the peer's counterpart's term gives the primary's counterpart id and no term in the new environment gives a source id; update the docstring
- [ ] T031 [US6] Run T030 per the E2E run rules, once per variant in separate sessions: `sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" -m "ci and shard_env_backup" -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-clone-api.log`, then the same with `-k ui-chromium` and `/tmp/e2e-clone-ui.log`; record both PASS entries in `specs/027-deployment-reference-by-id/e2e-evidence.md`

**Checkpoint**: clone requests that would break terms are refused before a backup is taken.

---

## Phase 8: User Story 4 - Delete and re-create a named deployment (Priority: P2)

**Goal**: a term that names a deleted deployment is refused with its last name; writing the term again with the name points it at the new deployment.

**Independent Test**: delete A, update B, and get an error with the term's path, A's last name and `deleted: true`.

- [ ] T032 [P] [US4] Functional tests in `backend/tests/functional/graphql/test_deployment_reference_scenarios.py` (spec US4): B's config names A; tombstone A (the repository or service path the existing deletion tests use to reach `DELETED`); `updateDeployment` on B is refused with `extensions.deleted == True`, `deployment_name` A's last name and the path; E's config names A, A tombstoned, and the environment fan-out redeploy of B fails (counted as failed); create a new A and re-send B's config with `deploymentName: A`: accepted, and the stored id is the new A's id

**Checkpoint**: deletions are reported with the deployment's last name.

---

## Phase 9: User Story 8 - Re-apply an unchanged manifest without a reconcile (Priority: P2)

**Goal**: write-backs and re-applies with names start no reconcile.

**Independent Test**: read B's config, write it back with `updateDeployment`, and get a null `Task`.

- [ ] T033 [P] [US8] No-op tests in `backend/tests/functional/graphql/test_deployment_noop_propagation.py`: write back a config read from `Deployment.config` with `updateDeployment` gives a null `Task`; `updateDeploymentVersion` with the same version and a config whose term gives `deploymentName` of the already-named deployment gives a null `Task` (the path `deployments apply` takes); `updateEnvironment` re-sending a config whose term gives the name skips every deployment as already at config
- [ ] T034 [P] [US8] SDK apply test in the existing SDK apply test module (find it with `grep -rln "def apply_files\|action=\"unchanged\"" T python_sdk`): a manifest whose `spec.config` term gives `deploymentName`, applied twice, reports `unchanged` the second time

**Checkpoint**: ADR-054 no-op detection holds for references.

---

## Phase 10: User Story 7 - Restore an environment backup with a term that names a deleted deployment (Priority: P3)

**Goal**: the restore succeeds and saves the other deployments' redeploys.

**Independent Test**: back up E, delete A, and restore E; the restore succeeds, and B's next update fails with A's last name.

- [ ] T035 [US7] In `restore_environment_backup` in `backend/styrmin_backend/services/backup/environment.py` (L1071-1089, plan D-008), wrap `redeploy_for_environment_update(deployment, uow)` in `async with uow.session.begin_nested():` inside the existing `try`, as `_redeploy_application` does in `backend/styrmin_backend/services/cluster_config_fanout.py` (L375-400)
- [ ] T036 [P] [US7] Unit test in `backend/tests/unit/services/backup/test_environment_backup.py`: in the restore fan-out, the first deployment's redeploy raises `UnresolvableAffinityReferenceError` and the second's succeeds; the second's redeploy is committed and the restore returns normally
- [ ] T037 [P] [US7] Functional test in `backend/tests/functional/graphql/test_deployment_reference_scenarios.py` (FR-006): E's captured config names A; tombstone A; restore the environment backup: the restore succeeds and E's config equals the captured config; `updateDeployment` on B is refused with A's last name and `deleted: true`

**Checkpoint**: one term does not block a recovery.

---

## Phase 11: Documentation, Polish and Verification

- [ ] T038 [P] Rewrite "Affinity by deployment reference" in `dev/guides/pod-scheduling.md` (research R-014): a name is replaced with the id on write; the id is resolved at each reconcile; a rename changes nothing; a delete gives no warning and makes every later update of the deployments that name it fail until the terms are written again; re-create and re-apply; the driver-term limit (research R-005); clones point terms at the counterparts and refuse a request that leaves out a named deployment
- [ ] T039 [P] Add **Affinity term** and **Deployment reference** entries to `CONTEXT.md` (Infrastructure or Context section, with the avoid list: "affinity rule" for term), and extend the **Environment clone** entry with the copied terms and the refusal; keep the format of the neighbouring entries
- [ ] T040 [P] Write `dev/adr/0075-deployment-references-stored-by-id.md` (Status Accepted, Date 2026-10-16, Source #508 and #492, Related ADR-034, ADR-054, ADR-056, ADR-073): context (#492), drivers, options (rewrite names on rename as in PR #504; store the id; resolve at reconcile as today), decision, consequences (delete and re-create, driver-term limit, clone ids given in advance, rollback leaves stored configs valid, critique E9), and that it amends ADR-034's "re-expanded on every reconcile" for names; check again before writing that 0075 is still free on local and remote branches
- [ ] T041 [P] Update `dev/knowledge/backend/backup-restore.md` (clone flow: counterpart ids given in advance, remap, order, cascade, request check, the new step and reason; restore redeploys in savepoints), `dev/knowledge/backend/data-models.md` (L797, `DeploymentReference` stored form) and `dev/knowledge/backend/services.md` (L272, `deploy_application` arguments `deployment_id` and `upcoming_deployments`)
- [ ] T042 [P] In `docs/docs/concepts-and-architecture/backups-and-restores.md`, "Choosing which deployments come along": add a row to the table for a request rejected up front because an affinity term names a deployment the clone does not copy, and one sentence that copied terms name the counterparts
- [ ] T043 [P] Create `changelog/492.fixed.md` and `changelog/508.changed.md` with `uv run towncrier create -c "..." <issue>.<type>.md`, with the content of research R-014 (dev/guidelines/changelog.md)
- [ ] T044 Run `uv run invoke format lint`, `uv run invoke validate-graphql`, `uv run invoke test` and `uv run pytest backend/tests/functional -q`; fix failures
- [ ] T045 Walk through `specs/027-deployment-reference-by-id/quickstart.md` §1, §2 and §5 and confirm each expected result; note any difference in `specs/027-deployment-reference-by-id/e2e-evidence.md`
- [ ] T046 Write the handoff notes in `specs/027-deployment-reference-by-id/pr-notes.md`: link `e2e-evidence.md`; call out the GraphQL description change and the changes to the clone flow and the environment restore as high-risk areas; list the known limits (research R-005 driver terms, R-008 cycle with a creation failure); and state that the user files the follow-up issue for showing which deployment a term names, next to the id (spec Out of Scope, critique P2) — do not file it during implementation

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: T002 and T004 in parallel; T003 after T002; T005 after T004; T006 after T002; T007 after T006; T008 any time; T009 after T006 and T007. Blocks every story.
- **US2 (Phase 3)**: after Phase 2. T010 needs T008; T011, T012, T013 after T010 (same file for T011 and T012); T014 any time; T015 after T010 to T012; T016 after T010 to T014.
- **US3 (Phase 4)**: after T011 and T013.
- **US1 (Phase 5)**: after Phase 3. T020 → T021.
- **US5 (Phase 6)**: after Phase 3 (needs `deploy_application(deployment_id, upcoming_deployments)` and `create_environment(upcoming_deployments)`). T022 → T023 → T025; T024 after T022.
- **US6 (Phase 7)**: after Phase 6 (same flow file). T026 and T027 in sequence; T028 and T029 after them; T030 after T023, T026, T027; T031 after T030.
- **US4 (Phase 8)**: after Phase 3.
- **US8 (Phase 9)**: after Phase 3.
- **US7 (Phase 10)**: after Phase 2 for T035 and T036; T037 after Phase 3.
- **Phase 11**: T038 to T043 any time after the behaviour they describe is final; T044 to T046 last.

### User Story Dependencies

- US2 is the mechanism; US1, US3, US4 and US8 test it from other angles and need Phase 3.
- US5 needs Phase 3; US6 needs US5.
- US7 needs only Phase 2 for its code change.

### Parallel Opportunities

- Phase 2: T002 and T004; then T003, T005 and T008.
- After Phase 3: Phases 4, 5, 8, 9 and the T035/T036 part of Phase 10 can run in parallel (different test files; T019, T032 and T037 share `test_deployment_reference_scenarios.py`, so write them in sequence).
- E2E sessions T021 and T031 each need a full vcluster; run them in sequence on one host unless it has the memory for two.
- Phase 11: T038 to T043 in parallel.

## Parallel Example: Phase 2

```text
T002 error types in backend/styrmin_backend/services/exceptions.py
T004 backend/styrmin_backend/services/scheduling/references.py
T008 upcoming_deployments in backend/styrmin_backend/services/reconciliation/__init__.py and Deployment.create(id=...)
```

## Implementation Strategy

1. Phases 1 and 2: helpers, errors and the resolver, with unit tests.
2. Phase 3 (US2): every write binds. This is the smallest change that fixes #492 for operators' terms; with Phases 4, 5, 8 and 9 it is the first state worth reviewing.
3. Phase 5 E2E (T020, T021): #492 observed fixed in a cluster.
4. Phases 6 and 7 (US5, US6): the clone must ship in the same change as Phase 3, because after Phase 3 every stored term gives an id and an unchanged clone would fail for every counterpart whose terms name a deployment (spec US5). Do not merge Phase 3 without them.
5. Phase 10 (US7) and Phase 11: restore isolation, documentation, ADR, changelog, full verification.
