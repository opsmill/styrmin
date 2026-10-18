---

description: "Tasks for 030: a clone writes its own service aliases and restores none of the source's"
---

# Tasks: A Clone Writes Its Own Service Aliases and Restores None of the Source's

**Input**: Design documents from `specs/030-clone-service-aliases/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/internal-interfaces.md](contracts/internal-interfaces.md), [quickstart.md](quickstart.md)

**Tests**: Required. The spec's Testing Decisions list the unit tests, the functional GraphQL test (FR-007) and the E2E checks in two existing nodes; Constitution §V requires local PASS evidence for both nodes in both variants.

**Organization**: One phase per user story. Phase 2 moves the alias step so that the restore can call it. User Stories 1 and 2 share the restore changes; User Story 2 adds the partial-clone check. User Story 3 adds the failure path and the clone entry fold. User Story 4 checks that in-place restores keep their aliases.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US4 (spec user stories)
- Paths are relative to the repository root; backend paths without a prefix are under `backend/styrmin_backend/`

## E2E run rules (apply to every E2E task)

- Build the server image once before the first session: `docker compose build server`. The fixture's parallel builds race on one tag.
- Run one CI shard per pytest session (both nodes are `shard_env_backup`), and `api-chromium` and `ui-chromium` in separate sessions.
- Run with `--pdb`. From a non-interactive shell, prefix the command with `sleep infinity |`, and stop the run by PID, never with `pkill -f`. To run the two variants one after the other from one script, open a private sleep with `exec 3< <(sleep infinity); spid=$!` and kill only `$spid`.
- Record each passing run in `specs/030-clone-service-aliases/e2e-evidence.md`: the pytest node IDs, the exact command, ISO 8601 start and end times, the vcluster name and kubeconfig path under `/tmp/pytest-of-*/pytest-*/`, and the verbatim `PASSED` lines (Constitution §V). Check the log before recording totals.

---

## Phase 1: Setup

**Purpose**: a green baseline before any change.

- [X] T001 Run `uv sync`, then `uv run pytest backend/tests/unit/agent/test_service_aliases.py backend/tests/unit/agent/test_backup_builders.py backend/tests/unit/workflows/test_restore_steps.py backend/tests/unit/agent/tasks/test_remediation_flow_steps.py backend/tests/unit/services/backup/test_environment_clone_status.py backend/tests/unit/test_restore_recovery_cross_target.py backend/tests/functional/graphql/test_environment_clone.py -q`, and note the result as the baseline (no file change)

---

## Phase 2: Foundational (blocks US1 and US3)

**Purpose**: one alias step that the CRD flows and the restore both call (research R-003, [contract](contracts/internal-interfaces.md#alias-step-agenttasksservice_aliasespy)).

- [X] T002 Move `_apply_service_aliases_step` from `agent/tasks/orchestration.py` to `agent/tasks/service_aliases.py` as `apply_service_aliases_step(reporter: StepReporter, context: GlobalContext) -> None`, with the same body and docstring; import `StepReporter` from `styrmin_backend.agent.steps.reporter` and `steps` from `styrmin_backend.domain`. In `orchestration.py`, import it and call it from `create_instance_crd`, `update_instance_crd` and `upgrade_instance_crd`; keep the imports of `compute_service_aliases`, `find_stale_service_aliases` and `apply_service_aliases` that the non-CRD flows still use, and drop `with_current_peer_services` if nothing else in the module uses it
- [X] T003 In `backend/tests/unit/agent/tasks/test_remediation_flow_steps.py`, patch `apply_service_aliases`, `find_stale_service_aliases`, `with_current_peer_services` (fixture `cluster`) and `compute_service_aliases` (fixtures `with_aliases`, `without_aliases`) on the `styrmin_backend.agent.tasks.service_aliases` module, where the moved step now looks them up; keep the other patches on `orchestration`
- [X] T004 Run `uv run pytest backend/tests/unit/agent/tasks/test_remediation_flow_steps.py backend/tests/unit/agent/test_service_aliases.py -q`; fix failures; then `uv run invoke format lint`

**Checkpoint**: the CRD flows behave as before, through the moved step.

---

## Phase 3: User Story 1 - Clone every deployment, and each counterpart reaches the other counterparts (Priority: P1) 🎯 MVP

**Goal**: a cross-target restore restores no alias and writes the counterpart's aliases from the new environment's services (FR-001, FR-002, FR-003).

**Independent Test**: after the first clone of `test_environment_clone_lifecycle` reports `COMPLETED`, each counterpart's namespace holds exactly the expected aliases (T015, SC-001); the unit tests of T007, T011 and T012 pass.

### Implementation for User Story 1

- [X] T005 [P] [US1] In `agent/service/kubernetes/velero/resources.py`, add `label_selector: dict[str, Any] | None = None` to `VeleroRestore`, and in `render()` write `spec["labelSelector"] = self.label_selector` only when it is not `None`
- [X] T006 [US1] In `agent/service/kubernetes/resources/builders/backup.py`, add the module constant `CROSS_TARGET_LABEL_SELECTOR = {"matchExpressions": [{"key": SERVICE_ALIAS_LABEL, "operator": "NotIn", "values": ["true"]}]}` next to `CROSS_TARGET_EXCLUDED_RESOURCES`, with a comment of one or two lines: the aliases point to the source's namespaces, and the restore writes the new environment's aliases after its recovery (#530). Import `SERVICE_ALIAS_LABEL` from `styrmin_backend.agent.service.kubernetes.service_alias_rules`. In `build_velero_restore`, pass `label_selector=copy.deepcopy(CROSS_TARGET_LABEL_SELECTOR)` in the branch where `source_namespace != target_namespace`, and `None` otherwise; add one sentence to the docstring
- [X] T007 [P] [US1] In `backend/tests/unit/agent/test_backup_builders.py`, add: a cross-target restore renders `spec.labelSelector` with one `NotIn` expression on `styrmin.io/service-alias` for `["true"]`; an in-place restore renders no `labelSelector` key; two cross-target restores do not share the selector object (same pattern as `test_restores_do_not_share_the_excluded_list`)
- [X] T008 [US1] In `workflows/templates/backup.py`, make `_build_counterpart_crd_body` return a `NamedTuple` `_Counterpart(crd_body: dict[str, Any], context: GlobalContext)`, reading the active instance once, and update its docstring. Update `backend/tests/unit/counterpart_crd_fixtures.py` to read `.crd_body` where it uses the result
- [X] T009 [US1] In `execute_restore_workflow` (`workflows/templates/backup.py`), for a cross-target restore, take `counterpart_crd_body` and `counterpart_context` from the `_Counterpart`, and pass `"counterpart_context": counterpart_context` in the `arun_deployment` parameters next to `counterpart_crd_body`; both stay `None` for an in-place restore
- [X] T010 [US1] In `execute_velero_restore_flow` (`workflows/templates/backup.py`), add the parameter `counterpart_context: GlobalContext | None = None` with an `Args:` entry. After `await reporter.succeed_step(steps.RESTORE_RECOVERY.key)`, when `counterpart_context` is not `None`, call `await apply_service_aliases_step(reporter, counterpart_context)` (import it from `styrmin_backend.agent.tasks.service_aliases`). Leave the failure handling to T016
- [X] T011 [US1] In `backend/tests/unit/workflows/test_restore_steps.py`, add, with the existing `api`/`events` fixtures and a patched `apply_service_aliases_step` that records an event: (a) a cross-target run of `execute_velero_restore_flow` with a `counterpart_context` calls the step once with that context after `("SUCCEEDED", "restore:recovery")`; (b) an in-place run (no `counterpart_context`) does not call it and records `ALL_STEPS_SUCCEEDED`; (c) a run whose recovery fails does not call it; (d) `execute_restore_workflow` with `source_deployment_id` set passes `counterpart_context` equal to the counterpart instance's context to `arun_deployment`, and without it passes `None`
- [X] T012 [P] [US1] In `backend/tests/unit/agent/test_service_aliases.py`, add `TestCounterpartAliases`: build a counterpart context `C` (environment `E`, own service `a`), patch `read_environment_services` to return the services of `C`, of a cloned peer `P` and of a counterpart `F` whose restore failed; call `compute_service_aliases(await with_current_peer_services(context))` and assert: aliases in `styrmin-<C>` for the services of `P` and `F`, pointing to `styrmin-<P>` and `styrmin-<F>`; aliases of `a` in `styrmin-<P>` and `styrmin-<F>`; no alias whose `externalName` or holder names the namespace of a source deployment `S` that the context's own list held before the read (put `S` in the stored context's `deployed_services`, and not in the server's list)
- [X] T013 [US1] Run `uv run pytest backend/tests/unit/agent/test_backup_builders.py backend/tests/unit/workflows/test_restore_steps.py backend/tests/unit/agent/test_service_aliases.py backend/tests/unit/test_restore_recovery_cross_target.py -q`; fix failures; then `uv run invoke format lint`

### E2E for User Story 1

- [X] T014 [US1] In `backend/tests/e2e/test_backup_restore.py`, add the helper of commit `472fe403` (its first hunk applies as is, after `workload_object_names`), extended to return, for each alias Service labelled `styrmin.io/service-alias=true` in a namespace, its name, its `styrmin.io/deployment-id` label and the namespace part of `spec.externalName`. Add `wait_for_service_aliases(kubeconfig_path, namespace, expected, timeout)` that polls every 5 seconds until the aliases equal `expected` and returns the last set read, as `_wait_for_alias_names` in `backend/tests/e2e/test_service_discovery.py` does
- [X] T015 [US1] In `test_environment_clone_lifecycle`, right after the first clone's `wait_for_environment_clone` and the `CLONED` assertions (where the counterpart ids are read), check SC-001 for each counterpart: read the deployments of the created environment with `client.deployments.list(created_environment_id, include_internal=True)` and their services (`deployed_services[].resolved_name`, as `source_deployment_state` reads them); the expected aliases of counterpart `c` are, for every other deployment `d` with services, one alias per resolved name, labelled with `d.id` and pointing to `styrmin-<d.id>`; call `wait_for_service_aliases` with a 60-second timeout and assert equality, with a message that lists the unexpected and the missing aliases. Name the check after SC-001 of spec 030 and FR-016 of #518 in a one-line comment

**Checkpoint**: a full clone writes the new environment's aliases and restores none of the source's.

---

## Phase 4: User Story 2 - Clone some deployments, and a peer that was not cloned cannot be reached (Priority: P2)

**Goal**: in a partial clone, no alias names a source namespace and a peer that was not cloned gets no alias (FR-001, FR-003, SC-002).

**Independent Test**: the re-clone of the primary only in `test_environment_clone_lifecycle` passes the SC-002 check (T016); T007 and T012 cover the selector and the server's list.

- [X] T016 [US2] In `test_environment_clone_lifecycle`, step 11: re-clone with `deployment_ids=[primary_deployment_id]` instead of `[]`, wait with `ENVIRONMENT_CLONE_TIMEOUT_SECONDS`, and assert `COMPLETED`. Keep the peer's `SKIPPED` and `CLONE_REASON_NOT_SELECTED` assertions and the "no counterpart" assertion for the peer; assert that the primary is `CLONED`. Then check SC-002: list the aliases in every namespace of the re-clone's environment (`client.deployments.list(<re-clone environment id>, include_internal=True)`) and assert that none names a namespace outside that environment, and that the primary's counterpart has no alias named after the peer's resolved service name (`envclone{suffix}`). Rewrite the comment above the re-clone (it cites research D12 of spec 010 for the empty selection) to say why the re-clone now selects the primary, and update the test's docstring where it describes the re-clone's empty selection. Check that the `finally` block deletes the re-clone's environment, which now holds a counterpart

**Checkpoint**: a partial clone reaches no source deployment.

---

## Phase 5: User Story 3 - The aliases cannot be written, and the clone reports it (Priority: P3)

**Goal**: a failed alias write fails the restore with the error and the clone entry reads `failed` with that error (FR-004, FR-007, SC-004).

**Independent Test**: the unit tests of T018, T021 and the functional test of T022 pass.

### Failure path of the restore

- [ ] T017 [US3] In `execute_velero_restore_flow` (`workflows/templates/backup.py`), wrap the call of T010 in `try`/`except Exception as exc`: log `error_msg = f"Service alias step failed: {exc}"` and set `recovery_status = {"recovered": False, "error": error_msg}`. Do not call `mark_failed` (research R-004); add a comment of one line that says why (the operator's rollout of the recovered spec would replace the failed status). The step is already recorded as failed by `StepReporter.step`
- [ ] T018 [US3] In `backend/tests/unit/workflows/test_restore_steps.py`, add: (a) a cross-target run whose alias write raises `ApiException(status=500)` (patch `apply_service_aliases` in `styrmin_backend.agent.tasks.service_aliases` and make `compute_service_aliases` return one alias) records `("STARTED", "resource:service-aliases")` and `("FAILED", "resource:service-aliases", <error>)`, stores `recovery == {"recovered": False, "error": "Service alias step failed: ..."}` in the result variable, and does not call `mark_failed`; (b) `execute_restore_workflow`, given a USER result with that recovery, sets the restore to `FAILED` with `error_message` equal to the alias error and sets the counterpart deployment to `FAILED` (critique E4)

### Clone entry of a failed restore

- [ ] T019 [P] [US3] In `services/backup/clone.py`, add `CLONE_REASON_RESTORE_FAILED = "the restore failed"`, `failed_restore(restore_id: UUID | None, restores: Mapping[UUID, Restore]) -> Restore | None` and `resolve_deployment_result(result: CloneDeploymentResult, restores: Mapping[UUID, Restore]) -> CloneDeploymentResult` as the [contract](contracts/internal-interfaces.md#clone-entry-fold-servicesbackupclonepy) states; in `derive_environment_clone_status`, replace the inline `restore is not None and restore.status is RestoreStatus.FAILED` test with `failed_restore(result.restore_id, rows) is not None`, with no other change
- [ ] T020 [US3] In `api/definitions/backup/environment_clone.py`, make `EnvironmentClone.deployment_results` project each readable entry through `resolve_deployment_result(..., self.referenced_restores)`: split `EnvironmentCloneDeploymentResult.from_stored` so that the validated `CloneDeploymentResult` passes through the fold before `from_model`, and an unreadable entry keeps its current projection. Add one sentence to the descriptions of `EnvironmentCloneDeploymentResult` (type), `outcome` and `reason`: an entry whose restore failed reads `FAILED`, with the restore's error as the reason
- [ ] T021 [P] [US3] In `backend/tests/unit/services/backup/test_environment_clone_status.py`, add tests of `resolve_deployment_result`: a `cloned` entry with a `FAILED` restore with an error message becomes `failed` with `the restore failed: <message>` and keeps its counterpart and restore ids; without an error message the reason is `the restore failed`; a `cloned` entry with an `IN_PROGRESS`, `COMPLETED` or missing restore, and `skipped` and `failed` entries, are returned unchanged. Add one test that, for entries with one failed and one completed restore, the number of `failed` entries read equals the failures that `derive_environment_clone_status` counts (it returns `PARTIAL`) (critique E2)
- [ ] T022 [US3] In `backend/tests/functional/graphql/test_environment_clone.py`, extend the case `a-cloned-entry-whose-restore-failed` (around line 1732) or add a test next to `test_environment_clone_projects_links_attribution_and_errors` that queries `environmentClone { deploymentResults { outcome reason counterpartDeploymentId restoreId } }` for a clone whose `cloned` entry references a `FAILED` restore with an error message, and asserts `outcome == "FAILED"`, the reason, and the unchanged ids; and that `environmentClones` returns the same entry (propagation through the real repository and resolver, Constitution §V)
- [ ] T023 [US3] Regenerate the schema with `uv run styrmin export graphql-schema schema.graphql` and the generated types with `uv run invoke generate` (frontend codegen needs `pnpm install --ignore-workspace` in `frontend/` in this worktree, in a `node:22-slim` container when the host Node is older); check that the diff holds only the changed descriptions
- [ ] T024 [US3] Run `uv run pytest backend/tests/unit/workflows/test_restore_steps.py backend/tests/unit/services/backup/ backend/tests/functional/graphql/test_environment_clone.py -q`; fix failures; then `uv run invoke format lint`

**Checkpoint**: a failed alias write is visible on the restore and on the clone entry.

---

## Phase 6: User Story 4 - Restores of a deployment or of an environment keep their aliases (Priority: P3)

**Goal**: in-place and environment restores write back the same aliases as before (FR-006, SC-003).

**Independent Test**: the SC-003 check of T025 passes; T007(b) and T011(b) cover the in-place request and steps.

- [ ] T025 [US4] In `test_environment_backup_and_restore_lifecycle` (`backend/tests/e2e/test_backup_restore.py`), after the environment restore's deployment-count check and before step 10 (the cascade delete), check SC-003 of spec 030: the primary's namespace holds the alias named after the second deployment's resolved service name (`envsnap{suffix}`), labelled with the second deployment's id and pointing to its namespace. Use `wait_for_service_aliases` from T014 with a 60-second timeout, filtered to that alias, because other deployments of the shared environment can add aliases

**Checkpoint**: in-place restores are unchanged.

---

## Phase 7: Documentation (Constitution §VII)

**Purpose**: the pages that research R-010 lists, in the same change.

- [ ] T026 [P] In `docs/docs/concepts-and-architecture/backups-and-restores.md`: (a) in "Choosing which deployments come along", add the paragraph: an application in the clone reaches the clone's other deployments by short service name, and a deployment that was not cloned cannot be reached by short service name from the clone; (b) in "What happens when you restore", after the paragraph on aliases added for #503, say that a clone's restore does not restore the source's aliases and writes the aliases of the new environment at its end; (c) in "Watching a clone, and what its status means", say that a deployment whose restore failed is reported failed with the restore's error, that a counterpart whose alias step failed can read `Running` because its workloads run, and that the admin repairs it with a change to its configuration or parameters, or an upgrade, because saving the same values can run no flow
- [ ] T027 [P] In `docs/docs/concepts-and-architecture/ingress-and-networking.md`, "Service aliases": add that a clone restores none of the source's aliases and that each counterpart's restore writes the aliases between it and the other deployments of the new environment; check that the bullet "Self-contained cloned environments" and the paragraph near line 308 stay true
- [ ] T028 [P] In `dev/knowledge/backend/orchestration-flows.md`: add the alias step to the steps of a cross-target restore; restrict "After a restore, the namespace holds the aliases that Velero restored from the backup" to in-place restores; record that the clone relies on Velero 1.18 applying `spec.labelSelector` only to the items it reads from the backup, with the link of research R-001, so a Velero upgrade review checks it (critique E6)
- [ ] T029 [P] In `dev/adr/0056-environment-clone-record-and-cross-target-restore.md`, add to decision 2 a paragraph "Amended 2026-10-18 (#530, spec 030)": a cross-target restore leaves out the alias Services with a label selector and runs the alias step after its recovery; why (restored aliases pointed to the source's namespaces, research R-001, R-002); a failed alias write fails the restore; a clone entry whose restore failed reads `failed`
- [ ] T030 [P] In `CONTEXT.md`, extend the entry "Service alias" with: "An **environment clone** writes the aliases of the new environment and never restores the source's aliases ([#530](https://github.com/opsmill/styrmin/issues/530))."
- [ ] T031 [P] Create the changelog fragment with `uv run towncrier create -c "<text>" 530.fixed.md` (see `dev/guidelines/changelog.md`): in the past tense, outcomes first, it says that applications in a cloned environment reached the source environment's deployments by short service name and now reach the clone's deployments, that a deployment that was not cloned is not reachable by short name from the clone, and that a clone now reports a deployment whose restore failed as failed, with the restore's error
- [ ] T032 Build the docs to check the changed pages (`cd docs && pnpm install --ignore-workspace && pnpm build`, in a `node:22-slim` container when the host Node is older)

---

## Phase 8: Polish & verification

- [ ] T033 Run `uv run invoke format lint` and `uv run invoke test`; fix failures
- [ ] T034 Build the server image: `docker compose build server`
- [ ] T035 Run `test_environment_clone_lifecycle` and `test_environment_backup_and_restore_lifecycle` in the `api-chromium` variant in one session (`-k "api-chromium"`, E2E run rules); on a failure, debug on the paused session with `kubectl` (quickstart, "Manual check on a paused session"); record the pass in `specs/030-clone-service-aliases/e2e-evidence.md`
- [ ] T036 Run the same two nodes in the `ui-chromium` variant in a separate session; record the pass in `e2e-evidence.md`
- [ ] T037 Walk through `specs/030-clone-service-aliases/quickstart.md`, including the `kubectl get restores.velero.io` check of the label selector on a paused session, and note any result that differs in `e2e-evidence.md`
- [ ] T038 Write `specs/030-clone-service-aliases/pr-notes.md`: link `e2e-evidence.md`; call out the high-risk areas (the restore flows, the Velero Restore of a cross-target restore, the moved alias step); ask the maintainer to confirm the autonomous answers in the spec's Clarifications (reuse of the #503 step, the namespace rule in FR-002 and SC-001, FR-007 for every cause of a failed restore, the counterpart's status after an alias failure) and the description-only change of `schema.graphql`; note that this change carries the alias check of commit `472fe403`, so the demo branch `fac/demo-beta-presentation-bhshh` drops that commit when it is rebased

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: T002 → T003 → T004. Blocks T010, T017 and T018.
- **US1 (Phase 3)**: T005 → T006 → T007; T008 → T009 → T010 → T011; T012 after T002; T013 after T007, T011, T012. T014 → T015 (E2E edits; run in Phase 8).
- **US2 (Phase 4)**: T016 after T014. Its behaviour comes from T006 and T010.
- **US3 (Phase 5)**: T017 after T010 → T018. T019 → T020 → T022 → T023; T021 after T019. T024 last.
- **US4 (Phase 6)**: T025 after T014.
- **Docs (Phase 7)**: after the behaviour they describe (T010, T017, T020); T026 to T031 in parallel; T032 after T026 and T027.
- **Polish (Phase 8)**: after all phases. T034 → T035 → T036 → T037 → T038.

### User Story Dependencies

- US1 is the core fix; US2 checks it on a partial clone with no code of its own.
- US3's failure path extends the code of T010; its clone entry fold (T019 to T023) is independent of US1 and can be built in parallel with Phase 3.
- US4 needs only the E2E helper of T014.

### Parallel Opportunities

- Phase 3: T005 to T007 in parallel with T008 to T011; T012 in parallel with both.
- Phase 5: T019 to T022 in parallel with Phase 3.
- Phase 7: T026 to T031.
- E2E sessions (T035, T036) each need a full vcluster; run them in sequence on one host.

## Parallel Example: after Phase 2

```text
T005 VeleroRestore.label_selector         (agent/service/kubernetes/velero/resources.py)
T008 _Counterpart from _build_counterpart_crd_body (workflows/templates/backup.py)
T019 failed_restore, resolve_deployment_result     (services/backup/clone.py)
```

## Implementation Strategy

1. Phase 1 and Phase 2: baseline and the moved alias step.
2. US1 (core): the label selector and the alias step at the end of a cross-target restore, with unit tests and the SC-001 check. This alone fixes the defect of #530 for a full clone.
3. US2: the partial-clone check, which needs no new code.
4. US3: the failure path and the clone entry fold.
5. US4: the in-place check.
6. Docs, changelog, and both E2E variants. US1 to US3 ship together in one change: without T017, an alias write error ends the USER flow before it stores its result, so the restore fails with Prefect's message instead of the alias error, and without T019 to T022 the clone entry still reads `cloned`.
