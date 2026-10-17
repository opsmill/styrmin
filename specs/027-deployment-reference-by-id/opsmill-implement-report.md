# Implementation report: deployment references stored by id

## 1. Header

- Feature: deployment references stored by id (#508, fixes #492)
- Spec directory: `specs/027-deployment-reference-by-id/`
- Base commit: `738591927c5ec1d25743d58d1a76b425583b6c3b`
- Head commit: `a642c80a6787055e47293c0315c31f3d47c55a8d` (29 commits, none pushed)
- Wall-clock time: about 2026-10-16T23:10Z to 2026-10-17T04:55Z, including a pause of about one and a half hours (00:25Z to 02:00Z) for a usage limit
- Run status: DONE. All 46 tasks are ticked, and every new or modified test has local-pass evidence.

## 2. Chunk ledger

| # | Chunk | Tasks | Outcome | Commits |
|---|-------|-------|---------|---------|
| 1 | Phase 1 + Phase 2 (part 1): baseline, error types, reference helpers | T001-T005 (5) | 5 done | `bf9cf0ae`, `4ab04b9d` |
| 2 | Phase 2 (part 2): resolver reads ids only, expansion per level | T006-T009 (4) | 4 done | `df24bff0` |
| 3 | Phase 3 (US2): every write stores the id | T010-T016 (7) | 7 done | `ca0e4d2e`, `77820076`, `fc04c22a`, `6c441575` |
| 3b | Fix added by the orchestrator: nested unit-of-work rollback | none | fixed | `f1ee83dc` |
| 4 | Phase 4 (US3): refusal at write time | T017-T018 (2) | 2 done | `7caf4194` |
| 5 | Phase 5 (US1): rename, with E2E | T019-T021 (3) | 3 done | `0bb0b7c7`, `ae8dff34`, `8ca893f9` |
| 6 | Phase 6 (US5): clone points terms at the counterparts | T022-T025 (4) | 4 done | `14955d47` |
| 7 | Phase 7 (US6, part 1): request check and cascade | T026-T029 (4) | 4 done | `a67b3d98`, `342da41f` |
| 8 | Phase 7 (US6, part 2): clone E2E, both variants | T030-T031 (2) | 2 done | `17ca4840`, `7ad1efa8` |
| 9 | Phase 8 (US4): delete and re-create | T032 (1) | 1 done | `1c4da57c` |
| 10 | Phase 9 (US8): re-apply without a reconcile | T033-T034 (2) | 2 done | `10a2125b` |
| 11 | Phase 10 (US7): restore isolates each redeploy | T035-T037 (3) | 3 done | `5fdbfb68` |
| 12 | Phase 11 (part 1): documentation, ADR, changelog | T038-T043 (6) | 6 done | `065eaec2` |
| 13 | Phase 11 (part 2): verification and handoff notes | T044-T046 (3) | 3 done | `6895a1d1` |
| R | Review fixes | none | 5 code and test fixes, documentation fixes | `2079f97b`, `d820bbc7`, `9596d318`, `79c1bd19`, `91df29bf`, `f48d76fe`, `a642c80a` |

Decisions and surprises reported by each chunk:

- Chunk 1: the T001 baseline was 231 passed, 1 skipped, 0 failed. `remap_deployment_references` takes an extra optional `path_prefix`.
- Chunk 2:
  - Critique E7 was wrong about `test_accepts_anti_affinity_with_deployment_ref`, because that test calls only the shape check, which accepts a name by design.
  - Behaviour change: each level is now resolved before the merge. A term that a deeper level's `replace: true` discards is still resolved, and it can fail a reconcile.
- Chunk 3: the subagent found a defect in the shared unit of work that existed before this change. Two nested `async with uow` blocks failing inside a caller's savepoint rolled back the caller's whole transaction. The binder no longer opens its own unit of work. Other changes:
  - `deploy_application` resolves names before it starts the ingress controller flow.
  - `update_deployment` binds the whole stored config on every call.
- Chunk 3b: the savepoint stack in `SqlModelUnitOfWork` fixes that defect, and ADR-066 and the knowledge pages record it. The subagent's first message gave test totals before the suites had finished, then withdrew them; the logs confirm the totals in this report.
- Chunk 5: renaming A starts no reconcile, so `updateDeployment` returns null. The E2E passed on its first run.
- Chunk 6: counterparts with no terms are now created in source-name order, not in snapshot order. Nothing reads a new counterpart back by name.
- Chunk 7:
  - The merge of the source config and `config_override` now runs when the request arrives. A source config that no longer validates is now refused at that point, where before the clone flow failed.
  - The SDK's `OperationFailedError` drops the GraphQL extensions, so the term path does not reach SDK users.
  - There is no schema or frontend change, because steps and reasons are plain strings.
- Chunk 8: the term path is checked through a raw GraphQL request. Both variants passed on the first run.
- Chunk 9: re-creating a deployment with the same name works, because the unique name index leaves out deleted rows. When the savepoint is removed, the test with B redeployed last fails, which shows the test checks the isolation.
- Chunk 10: `apply` reports `unchanged` based on the server's null `Task`, so the SDK needed no change.
- Chunk 11: without the savepoint, an environment restore returned `INTERNAL_ERROR`, because the audit line read an object that had expired after the session rolled back. The restore writes the captured config back without binding it, as FR-006 requires.
- Chunk 12:
  - ADR number 0075 was free on local and remote branches.
  - Research R-005 describes driver terms differently from the code. A driver term's name is looked up again only when `updateDeploymentVersion` moves the deployment to another driver version, and the documentation follows the code.
- Chunk 13:
  - On this host, with Node 18, the frontend step of `invoke generate` fails; running `pnpm codegen` directly works.
  - The restore change came after the E2E runs. The orchestrator then ran the whole `shard_env_backup` shard again, once per variant, and both passed (see §4).

## 3. Tasks not completed

None. Every task from T001 to T046 is `[X]`.

## 4. Local-pass evidence

Commands referred to in the table:

- U1: `uv run pytest backend/tests/unit/services/test_scheduling_reference_errors.py backend/tests/unit/services/scheduling/test_references.py backend/tests/unit/services/test_scheduling_validator.py -v -p no:cacheprovider`
- U2: `uv run pytest backend/tests/unit/services/test_scheduling_validator.py "backend/tests/unit/services/test_services_context.py::TestPopulateComponentSchedulingReferencePaths" -v`
- F3: `uv run pytest backend/tests/functional/graphql/test_resolved_scheduling_reference_paths.py "backend/tests/functional/test_api_scheduling_config.py::TestSchedulingPayloadValidation::test_accepts_anti_affinity_with_deployment_ref" -v`
- U4: `uv run pytest backend/tests/unit/services/test_deployment_reference_binding.py "backend/tests/unit/services/scheduling/test_references.py::TestBindInsideTheCallersUnitOfWork" -v`
- U5: `uv run pytest backend/tests/unit/services/test_task_types.py backend/tests/unit/services/test_deploy_skip_initial_reconcile.py -v`
- F6: `uv run pytest` with the four propagation node ids in the table, `-v`
- F7: `uv run pytest backend/tests/functional/test_unit_of_work_savepoint.py -v`
- F8: `uv run pytest backend/tests/functional/graphql/test_environment_update_propagation.py backend/tests/functional/graphql/test_update_deployment_input_propagation.py -v -p no:cacheprovider`
- F9: `uv run pytest backend/tests/functional/graphql/test_deployment_reference_scenarios.py -v` (chunk 5 run)
- U10: `uv run pytest backend/tests/unit/services/backup/test_environment_clone_service.py -v -p no:cacheprovider -k "order_counterparts or merge_precedes or fanout_runs_against_the_real_create_restore"`
- F11: `uv run pytest backend/tests/functional/graphql/test_environment_clone.py -v -p no:cacheprovider -k "points"`
- U12: `uv run pytest backend/tests/unit/services/backup/test_environment_clone_service.py -v -k "clone_request or find_uncloned or cascade_reference or failed_capture_fails or environment_term_that_names or failed_counterpart" -p no:cacheprovider`
- U13: `uv run pytest "backend/tests/unit/services/backup/test_environment_clone_status.py::test_outcome_and_step_vocabularies_are_fixed" -v -p no:cacheprovider`
- F14: `uv run pytest` with the two `test_environment_clone.py` node ids in the table, `-v -p no:cacheprovider`
- F15: `uv run pytest backend/tests/functional/graphql/test_deployment_reference_scenarios.py -v -p no:cacheprovider` (chunk 9 run)
- F16: `uv run pytest` with the three `test_deployment_noop_propagation.py` node ids in the table, `-v -p no:cacheprovider`
- U17: `uv run pytest "python_sdk/tests/test_deployments.py::test_apply_files_twice_with_a_named_deployment_reference_reports_unchanged" -v -p no:cacheprovider`
- R20: `uv run pytest` with the 12 node ids marked R20, `-v` (after the review fixes)
- E-S: `export STYRMIN_IMAGE_VER=e2e-508-1792195869 && docker compose build server`, then `uv run pytest "backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql" -m "ci and shard_compute" -k api-chromium -v -s --pdb`, with stdin from a `sleep infinity` file descriptor
- E-C: `export STYRMIN_IMAGE_VER=e2e-508-1792204778 && docker compose build server`, then `uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" -m "ci and shard_env_backup" -k <variant> -v -s --pdb`, with the same stdin
- E-R: `export STYRMIN_IMAGE_VER=e2e-508-final-1792208899 && docker compose build server`, then `uv run pytest backend/tests/e2e -m "ci and shard_env_backup" -k <variant> -v -s --pdb`, with the same stdin (run by the orchestrator at HEAD `6895a1d1`)

Environment context:

- Unit tests: none needed.
- Functional tests: in-memory SQLite with `StaticPool`, from the `session` fixture in `backend/tests/functional/graphql/conftest.py`. Prefect is replaced by `prefect_manager_mock`.
- `test_unit_of_work_savepoint.py`: its own in-memory SQLite session, with a real `SqlModelUnitOfWork`.
- SDK test: a stub transport.

Pass lines are as the subagents reported them from `pytest -v`. "PASSED" without a percentage means the subagent reported the line without its percentage.

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---------|------|-------------|----------------------|---------------------|--------------------|
| `backend/tests/unit/services/test_scheduling_reference_errors.py::TestUnresolvableAffinityReferenceError::test_missing_name_without_deleted` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [  2%]` |
| `...test_scheduling_reference_errors.py::TestUnresolvableAffinityReferenceError::test_missing_id_without_deleted_has_no_deleted_key` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [  4%]` |
| `...test_scheduling_reference_errors.py::TestUnresolvableAffinityReferenceError::test_tombstoned_deployment_gives_last_name_and_deleted` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [  6%]` |
| `...test_scheduling_reference_errors.py::TestUnresolvableAffinityReferenceError::test_explicit_message_wins` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [  8%]` |
| `...test_scheduling_reference_errors.py::TestUnclonedDeploymentReferenceError::test_metadata_lists_each_deployment_with_its_paths` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 11%]` |
| `...test_scheduling_reference_errors.py::TestUnclonedDeploymentReferenceError::test_message_falls_back_to_id_without_name` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 13%]` |
| `...test_scheduling_reference_errors.py::TestUnclonedDeploymentReferenceError::test_reexported_from_context_exceptions` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 15%]` |
| `backend/tests/unit/services/scheduling/test_references.py::TestIterReferenceSites::test_paths_cover_required_and_preferred_of_both_pod_kinds` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 17%]` |
| `...test_references.py::TestIterReferenceSites::test_configs_without_scheduling_yield_nothing` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 20%]` |
| `...test_references.py::TestReferencedDeploymentIds::test_maps_each_id_to_every_path_that_names_it` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 22%]` |
| `...test_references.py::TestBindByName::test_name_becomes_id_at_required_and_preferred[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 24%]` |
| `...test_references.py::TestBindByName::test_components_are_kept_only_when_given[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 26%]` |
| `...test_references.py::TestBindByName::test_missing_name_is_refused_with_full_path[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 28%]` |
| `...test_references.py::TestBindByName::test_name_of_another_environment_is_refused[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 31%]` |
| `...test_references.py::TestBindByName::test_name_of_tombstoned_deployment_is_refused[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 33%]` |
| `...test_references.py::TestBindByName::test_first_failing_term_gives_the_path[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 35%]` |
| `...test_references.py::TestBindById::test_uppercase_id_is_stored_in_canonical_form[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 37%]` |
| `...test_references.py::TestBindById::test_missing_id_is_refused[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 40%]` |
| `...test_references.py::TestBindById::test_id_of_another_environment_is_refused[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 42%]` |
| `...test_references.py::TestBindById::test_tombstoned_id_is_refused_with_last_name_and_deleted[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 44%]` |
| `...test_references.py::TestBindUpcomingDeployments::test_upcoming_name_gives_its_id_without_a_row[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 46%]` |
| `...test_references.py::TestBindUpcomingDeployments::test_upcoming_id_is_accepted_without_a_row[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 48%]` |
| `...test_references.py::TestBindUpcomingDeployments::test_upcoming_name_wins_over_a_row_with_that_name[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 51%]` |
| `...test_references.py::TestBindUpcomingDeployments::test_old_name_of_a_renamed_deployment_is_refused[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 53%]` |
| `...test_references.py::TestBindUpcomingDeployments::test_no_environment_matches_upcoming_deployments_only[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 55%]` |
| `...test_references.py::TestBindLeavesTheRestAlone::test_node_affinity_and_other_keys_are_untouched[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 57%]` |
| `...test_references.py::TestBindLeavesTheRestAlone::test_input_is_not_mutated[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 60%]` |
| `...test_references.py::TestBindLeavesTheRestAlone::test_config_without_references_is_returned_as_is[asyncio]` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 62%]` |
| `...test_references.py::TestBindLeavesTheRestAlone::test_bound_config_survives_the_environment_config_round_trip[asyncio]` | unit | R20 (first passed in U1 at 23:19:08) | 2026-10-17T04:42:04+00:00 | n/a | `PASSED [ 83%]` |
| `...test_references.py::TestRemapDeploymentReferences::test_mutual_references_point_at_counterparts` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 66%]` |
| `...test_references.py::TestRemapDeploymentReferences::test_unmapped_id_is_reported_with_its_path` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 68%]` |
| `...test_references.py::TestRemapDeploymentReferences::test_none_config` | unit | U1 | 2026-10-16T23:19:08+00:00 | n/a | `PASSED [ 71%]` |
| `...test_references.py::TestBindInsideTheCallersUnitOfWork::test_refusal_in_a_savepoint_keeps_the_callers_earlier_work[asyncio]` | unit | U4 | 2026-10-16T23:56:27+00:00 | n/a | `PASSED [100%]` |
| `...test_references.py::TestBindRefusesMalformedReferences::test_id_and_name_together_are_refused_with_the_path[asyncio]` | unit | R20 | 2026-10-17T04:42:04+00:00 | n/a | `PASSED [ 58%]` |
| `...test_references.py::TestBindRefusesMalformedReferences::test_neither_id_nor_name_is_refused_with_the_path[asyncio]` | unit | R20 | 2026-10-17T04:42:04+00:00 | n/a | `PASSED [ 66%]` |
| `...test_references.py::TestBindRefusesMalformedReferences::test_malformed_id_is_refused_with_the_path[asyncio]` | unit | R20 | 2026-10-17T04:42:04+00:00 | n/a | `PASSED [ 75%]` |
| `...test_references.py::TestBindRefusesMalformedReferences::test_malformed_stored_id_is_refused_with_the_path` | unit | R20 | 2026-10-17T04:42:04+00:00 | n/a | `PASSED [ 91%]` |
| `backend/tests/unit/services/test_scheduling_validator.py::TestResolveDeploymentReferenceById::test_resolves_upcoming_id_without_lookup[asyncio]` | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `...test_scheduling_validator.py::TestResolveDeploymentReferenceUnresolvable::test_name_of_existing_deployment_raises[asyncio]` (renamed from `test_resolves_by_name`) | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `...test_scheduling_validator.py::TestResolveDeploymentReferenceUnresolvable::test_name_of_upcoming_deployment_raises[asyncio]` | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `...test_scheduling_validator.py::TestResolveDeploymentReferenceUnresolvable::test_tombstoned_id_raises_with_last_name[asyncio]` | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `...test_scheduling_validator.py::TestResolveDeploymentReferenceUnresolvable::test_different_environment_raises[asyncio]` | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `...test_scheduling_validator.py::TestExpandDeploymentReferences::test_default_path_prefix_is_scheduling[asyncio]` | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `...test_scheduling_validator.py::TestExpandDeploymentReferences::test_path_prefix_names_the_level[asyncio]` | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `...test_scheduling_validator.py::TestExpandDeploymentReferences::test_upcoming_ids_expand_without_lookup[asyncio]` | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `backend/tests/unit/services/test_services_context.py::TestPopulateComponentSchedulingReferencePaths::test_environment_level_term_gives_environment_path[asyncio]` | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `...test_services_context.py::TestPopulateComponentSchedulingReferencePaths::test_deployment_level_term_gives_index_in_its_own_list[asyncio]` | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `...test_services_context.py::TestPopulateComponentSchedulingReferencePaths::test_component_level_term_gives_component_path[asyncio]` | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `...test_services_context.py::TestPopulateComponentSchedulingReferencePaths::test_expanded_levels_merge_in_level_order[asyncio]` | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `...test_services_context.py::TestPopulateComponentSchedulingReferencePaths::test_upcoming_deployment_resolves_without_a_row[asyncio]` | unit | U2 | 2026-10-16T23:33:24+00:00 | n/a | `PASSED` |
| `backend/tests/functional/graphql/test_resolved_scheduling_reference_paths.py::test_resolved_scheduling_merges_the_expanded_levels` | functional | F3 | 2026-10-16T23:33:30+00:00 | SQLite session fixture | `PASSED [ 33%]` |
| `...test_resolved_scheduling_reference_paths.py::test_resolved_scheduling_refuses_tombstoned_deployment_with_level_path` | functional | F3 | 2026-10-16T23:33:30+00:00 | SQLite session fixture | `PASSED [ 66%]` |
| `backend/tests/functional/test_api_scheduling_config.py::TestSchedulingPayloadValidation::test_accepts_anti_affinity_with_deployment_ref` (docstring only) | functional | F3 | 2026-10-16T23:33:30+00:00 | SQLite session fixture | `PASSED [100%]` |
| `backend/tests/unit/services/test_deployment_reference_binding.py::test_deploy_stores_the_id_of_the_deployment_a_term_names` | unit | U4 | 2026-10-16T23:56:27+00:00 | n/a | `PASSED [ 11%]` |
| `...test_deployment_reference_binding.py::test_deploy_term_that_names_the_new_deployment_stores_its_new_id` | unit | U4 | 2026-10-16T23:56:27+00:00 | n/a | `PASSED [ 22%]` |
| `...test_deployment_reference_binding.py::test_deploy_refuses_a_term_that_names_a_missing_deployment` | unit | U4 | 2026-10-16T23:56:27+00:00 | n/a | `PASSED [ 33%]` |
| `...test_deployment_reference_binding.py::test_deploy_binds_the_component_configs_copied_from_the_driver_version` | unit | U4 | 2026-10-16T23:56:27+00:00 | n/a | `PASSED [ 44%]` |
| `...test_deployment_reference_binding.py::test_update_deployment_rename_resolves_a_term_against_the_new_name` | unit | U4 | 2026-10-16T23:56:27+00:00 | n/a | `PASSED [ 55%]` |
| `...test_deployment_reference_binding.py::test_update_deployment_rename_refuses_a_term_that_names_the_old_name` | unit | U4 | 2026-10-16T23:56:27+00:00 | n/a | `PASSED [ 66%]` |
| `...test_deployment_reference_binding.py::test_update_deployment_version_stores_the_id_of_the_deployment_a_term_names` | unit | U4 | 2026-10-16T23:56:27+00:00 | n/a | `PASSED [ 77%]` |
| `...test_deployment_reference_binding.py::test_update_deployment_version_binds_the_component_configs_of_a_new_driver_version` | unit | U4 | 2026-10-16T23:56:27+00:00 | n/a | `PASSED [ 88%]` |
| `backend/tests/unit/services/test_task_types.py` and `backend/tests/unit/services/test_deploy_skip_initial_reconcile.py`, all 27 tests (shared stub of `generate_instance_from_deployment` changed) | unit | U5 | 2026-10-16T23:56:33+00:00 | n/a | `27 passed`, including `test_deploy_application_saves_the_instance_before_the_flow_run_starts PASSED [ 66%]` |
| `backend/tests/functional/graphql/test_deploy_input_propagation.py::test_deploy_deployment_ref_name_is_stored_as_the_id` | functional | F6 | 2026-10-16T23:56:40+00:00 | SQLite session fixture | `PASSED [ 25%]` |
| `backend/tests/functional/graphql/test_update_deployment_input_propagation.py::test_update_deployment_deployment_ref_name_is_stored_as_the_id` | functional | F6 | 2026-10-16T23:56:40+00:00 | SQLite session fixture | `PASSED [ 50%]` |
| `backend/tests/functional/graphql/test_update_deployment_version_input_propagation.py::test_deployment_ref_name_is_stored_as_the_id` | functional | F6 | 2026-10-16T23:56:40+00:00 | SQLite session fixture | `PASSED [ 75%]` |
| `backend/tests/functional/graphql/test_environment_update_propagation.py::test_update_environment_deployment_ref_name_is_stored_as_the_id` | functional | F6 | 2026-10-16T23:56:40+00:00 | SQLite session fixture | `PASSED [100%]` |
| `backend/tests/functional/test_unit_of_work_savepoint.py::test_failure_in_nested_blocks_inside_a_savepoint_keeps_the_callers_work` | functional | F7 | 2026-10-17T00:02:27+00:00 | own SQLite session, real unit of work | `PASSED [ 50%]` (failed before the fix: `AssertionError: assert {'after'} == {'after', 'before'}`) |
| `...test_unit_of_work_savepoint.py::test_uncaught_failure_in_nested_blocks_inside_a_savepoint_rolls_back_everything` | functional | F7 | 2026-10-17T00:02:27+00:00 | own SQLite session, real unit of work | `PASSED [100%]` |
| `...test_unit_of_work_savepoint.py::test_failure_after_a_block_left_a_savepoint_normally_rolls_back_everything` | functional | R20 | 2026-10-17T04:42:04+00:00 | own SQLite session, real unit of work | `PASSED [ 50%]` (fails when the pop on normal exit is removed: `assert {'before', 'in-savepoint'} == set()`) |
| `backend/tests/functional/graphql/test_environment_update_propagation.py::test_update_environment_refuses_a_term_that_names_a_missing_deployment` | functional | F8 | 2026-10-17T00:09:42+00:00 | SQLite session fixture | `PASSED [ 29%]` |
| `...test_environment_update_propagation.py::test_create_environment_refuses_a_term_that_names_a_deployment[deployment_name]` | functional | F8 | 2026-10-17T00:09:42+00:00 | SQLite session fixture | `PASSED [ 31%]` |
| `...test_environment_update_propagation.py::test_create_environment_refuses_a_term_that_names_a_deployment[deployment_id]` | functional | F8 | 2026-10-17T00:09:42+00:00 | SQLite session fixture | `PASSED [ 32%]` |
| `...test_update_deployment_input_propagation.py::test_update_deployment_refuses_a_term_that_names_no_deployment_of_the_environment[missing_name]` | functional | F8 | 2026-10-17T00:09:42+00:00 | SQLite session fixture | `PASSED [ 98%]` |
| `...test_update_deployment_input_propagation.py::test_update_deployment_refuses_a_term_that_names_no_deployment_of_the_environment[other_environment_id]` | functional | F8 | 2026-10-17T00:09:42+00:00 | SQLite session fixture | `PASSED [100%]` |
| `backend/tests/functional/graphql/test_deployment_reference_scenarios.py::test_rename_of_a_named_deployment_succeeds_and_changes_no_stored_term` | functional | R20 (first passed in F9 at 00:17:16) | 2026-10-17T04:42:04+00:00 | SQLite session fixture | `PASSED [ 25%]` (fails on the base commit with #492: `'Affinity deployment reference cannot be resolved: a'`) |
| `...test_deployment_reference_scenarios.py::test_update_of_b_after_the_rename_succeeds` | functional | F15 (first passed in F9) | 2026-10-17T03:01:32+00:00 | SQLite session fixture | `PASSED` |
| `...test_deployment_reference_scenarios.py::test_environment_fan_out_after_the_rename_fails_no_redeploy` | functional | F15 (first passed in F9) | 2026-10-17T03:01:32+00:00 | SQLite session fixture | `PASSED` |
| `...test_deployment_reference_scenarios.py::test_resolved_scheduling_of_b_selects_a_s_id_after_the_rename` | functional | F15 (first passed in F9) | 2026-10-17T03:01:32+00:00 | SQLite session fixture | `PASSED` |
| `...test_deployment_reference_scenarios.py::test_update_of_b_is_refused_once_the_named_deployment_is_tombstoned[config_written_back]` | functional | F15 | 2026-10-17T03:01:32+00:00 | SQLite session fixture | `PASSED [ 50%]` |
| `...test_deployment_reference_scenarios.py::test_update_of_b_is_refused_once_the_named_deployment_is_tombstoned[rename_only]` | functional | F15 | 2026-10-17T03:01:32+00:00 | SQLite session fixture | `PASSED [ 60%]` |
| `...test_deployment_reference_scenarios.py::test_environment_fan_out_fails_b_s_redeploy_and_keeps_c_s[first]` | functional | F15 | 2026-10-17T03:01:32+00:00 | SQLite session fixture | `PASSED [ 70%]` |
| `...test_deployment_reference_scenarios.py::test_environment_fan_out_fails_b_s_redeploy_and_keeps_c_s[last]` | functional | F15 | 2026-10-17T03:01:32+00:00 | SQLite session fixture | `PASSED [ 80%]` |
| `...test_deployment_reference_scenarios.py::test_cluster_fan_out_fails_b_s_redeploy_when_e_s_term_names_a` | functional | F15 | 2026-10-17T03:01:32+00:00 | SQLite session fixture | `PASSED [ 90%]` |
| `...test_deployment_reference_scenarios.py::test_term_written_again_with_the_name_binds_the_re_created_deployment` | functional | F15 | 2026-10-17T03:01:32+00:00 | SQLite session fixture | `PASSED [100%]` |
| `...test_deployment_reference_scenarios.py::test_environment_restore_puts_back_a_term_that_names_a_tombstoned_deployment[first]` | functional | R20 (first passed at 03:19:04) | 2026-10-17T04:42:04+00:00 | SQLite session fixture | `PASSED [  8%]` |
| `...test_deployment_reference_scenarios.py::test_environment_restore_puts_back_a_term_that_names_a_tombstoned_deployment[last]` | functional | R20 (first passed at 03:19:04) | 2026-10-17T04:42:04+00:00 | SQLite session fixture | `PASSED [ 16%]` |
| `backend/tests/unit/services/backup/test_environment_clone_service.py::test_fanout_runs_against_the_real_create_restore` (modified) | unit | U10 | 2026-10-17T02:12:01+00:00 | n/a | `PASSED [ 10%]` |
| `...test_environment_clone_service.py::test_the_merge_precedes_environment_creation_and_counterpart_creation` (modified) | unit | U10 | 2026-10-17T02:12:01+00:00 | n/a | `PASSED [ 20%]` |
| `...test_environment_clone_service.py::test_order_counterparts_puts_each_after_the_ones_its_terms_name[input_order0]` | unit | U10 | 2026-10-17T02:12:01+00:00 | n/a | `PASSED [ 30%]` |
| `...test_environment_clone_service.py::test_order_counterparts_puts_each_after_the_ones_its_terms_name[input_order1]` | unit | U10 | 2026-10-17T02:12:01+00:00 | n/a | `PASSED [ 40%]` |
| `...test_environment_clone_service.py::test_order_counterparts_ignores_self_terms_and_deployments_outside_the_clone` | unit | U10 | 2026-10-17T02:12:01+00:00 | n/a | `PASSED [ 50%]` |
| `...test_environment_clone_service.py::test_order_counterparts_puts_the_ones_the_environment_names_first` | unit | U10 | 2026-10-17T02:12:01+00:00 | n/a | `PASSED [ 60%]` |
| `...test_environment_clone_service.py::test_order_counterparts_puts_a_named_counterpart_before_an_environment_named_one` | unit | U10 | 2026-10-17T02:12:01+00:00 | n/a | `PASSED [ 70%]` |
| `...test_environment_clone_service.py::test_order_counterparts_breaks_a_cycle_in_source_name_order[input_order0]` | unit | U10 | 2026-10-17T02:12:01+00:00 | n/a | `PASSED [ 80%]` |
| `...test_environment_clone_service.py::test_order_counterparts_breaks_a_cycle_in_source_name_order[input_order1]` | unit | U10 | 2026-10-17T02:12:01+00:00 | n/a | `PASSED [ 90%]` |
| `...test_environment_clone_service.py::test_order_counterparts_breaks_first_the_cycle_that_names_no_other` | unit | U10 | 2026-10-17T02:12:01+00:00 | n/a | `PASSED [100%]` |
| `backend/tests/functional/graphql/test_environment_clone.py::test_clone_points_a_term_at_the_counterpart_in_either_snapshot_order[snapshot_order0]` | functional | F11 | 2026-10-17T02:12:16+00:00 | SQLite session fixture | `PASSED [ 20%]` |
| `...test_environment_clone.py::test_clone_points_a_term_at_the_counterpart_in_either_snapshot_order[snapshot_order1]` | functional | F11 | 2026-10-17T02:12:16+00:00 | SQLite session fixture | `PASSED [ 40%]` |
| `...test_environment_clone.py::test_clone_points_mutual_terms_at_each_others_counterpart[snapshot_order0]` | functional | F11 | 2026-10-17T02:12:16+00:00 | SQLite session fixture | `PASSED [ 60%]` |
| `...test_environment_clone.py::test_clone_points_mutual_terms_at_each_others_counterpart[snapshot_order1]` | functional | F11 | 2026-10-17T02:12:16+00:00 | SQLite session fixture | `PASSED [ 80%]` |
| `...test_environment_clone.py::test_clone_points_the_environment_term_at_the_counterpart` | functional | F11 | 2026-10-17T02:12:16+00:00 | SQLite session fixture | `PASSED [100%]` |
| `...test_environment_clone_service.py::test_clone_request_is_refused_when_a_term_names_an_unselected_deployment` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [  5%]` |
| `...test_environment_clone_service.py::test_clone_request_is_refused_when_the_named_deployment_is_not_eligible` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 10%]` |
| `...test_environment_clone_service.py::test_clone_request_lists_a_tombstoned_deployment_by_its_last_name` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 15%]` |
| `...test_environment_clone_service.py::test_clone_request_is_refused_when_the_environment_config_names_a_left_out_deployment` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 21%]` |
| `...test_environment_clone_service.py::test_clone_request_is_refused_when_the_override_names_a_left_out_deployment` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 26%]` |
| `...test_environment_clone_service.py::test_clone_request_refuses_an_override_that_names_no_deployment_of_the_source` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 31%]` |
| `...test_environment_clone_service.py::test_clone_request_refuses_a_driver_term_that_no_copied_deployment_has_by_name[postgres-all-expected0]` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 36%]` |
| `...test_environment_clone_service.py::test_clone_request_refuses_a_driver_term_that_no_copied_deployment_has_by_name[postgres-main-api-expected1]` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 42%]` |
| `...test_environment_clone_service.py::test_clone_request_accepts_a_driver_term_that_names_a_copied_deployment` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 47%]` |
| `...test_environment_clone_service.py::test_clone_request_is_accepted_when_the_environment_term_is_cleared_or_replaced[cleared]` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 52%]` |
| `...test_environment_clone_service.py::test_clone_request_is_accepted_when_the_environment_term_is_cleared_or_replaced[replaced]` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 57%]` |
| `...test_environment_clone_service.py::test_clone_request_stores_the_override_with_the_id_of_the_named_deployment` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 63%]` |
| `...test_environment_clone_service.py::test_find_uncloned_references_groups_the_paths_of_each_deployment` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 68%]` |
| `...test_environment_clone_service.py::test_cascade_reference_failures_follows_a_chain[input_order0]` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 73%]` |
| `...test_environment_clone_service.py::test_cascade_reference_failures_follows_a_chain[input_order1]` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 78%]` |
| `...test_environment_clone_service.py::test_a_failed_capture_fails_the_counterparts_whose_terms_name_it` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 84%]` |
| `...test_environment_clone_service.py::test_an_environment_term_that_names_a_failed_capture_fails_the_clone` | unit | R20 (first passed in U12 at 02:25:48) | 2026-10-17T04:42:04+00:00 | n/a | `PASSED [100%]` |
| `...test_environment_clone_service.py::test_a_failed_counterpart_fails_the_counterparts_whose_terms_name_it` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [ 94%]` |
| `...test_environment_clone_service.py::test_a_failed_counterpart_that_the_environment_names_stops_the_clone` | unit | U12 | 2026-10-17T02:25:48+00:00 | n/a | `PASSED [100%]` |
| `backend/tests/unit/services/backup/test_environment_clone_status.py::test_outcome_and_step_vocabularies_are_fixed` (modified) | unit | U13 | 2026-10-17T02:27:59+00:00 | n/a | `PASSED [100%]` |
| `backend/tests/functional/graphql/test_environment_clone.py::test_clone_environment_refuses_a_selection_that_leaves_out_a_named_deployment` | functional | F14 | 2026-10-17T02:25:59+00:00 | SQLite session fixture | `PASSED [ 50%]` |
| `...test_environment_clone.py::test_clone_environment_requires_admin` (unchanged, rerun) | functional | F14 | 2026-10-17T02:25:59+00:00 | SQLite session fixture | `PASSED [100%]` |
| `backend/tests/functional/graphql/test_deployment_noop_propagation.py::test_update_deployment_writing_back_a_read_term_returns_null` | functional | F16 | 2026-10-17T03:09:05+00:00 | SQLite session fixture, Prefect mocked | `PASSED [ 33%]` |
| `...test_deployment_noop_propagation.py::test_update_deployment_version_re_sending_a_term_with_the_name_returns_null` | functional | F16 | 2026-10-17T03:09:05+00:00 | SQLite session fixture, Prefect mocked | `PASSED [ 66%]` |
| `...test_deployment_noop_propagation.py::test_update_environment_re_sending_a_term_with_the_name_skips_every_deployment` | functional | F16 | 2026-10-17T03:09:05+00:00 | SQLite session fixture, Prefect mocked | `PASSED [100%]` |
| `python_sdk/tests/test_deployments.py::test_apply_files_twice_with_a_named_deployment_reference_reports_unchanged` | unit | U17 | 2026-10-17T03:09:06+00:00 | SDK stub transport | `PASSED [100%]` |
| `backend/tests/unit/services/backup/test_environment_backup.py::test_restore_keeps_a_redeploy_when_another_names_a_tombstoned_deployment[first]` | unit | R20 (first passed at 03:19:01) | 2026-10-17T04:42:04+00:00 | n/a | `PASSED [ 33%]` |
| `...test_environment_backup.py::test_restore_keeps_a_redeploy_when_another_names_a_tombstoned_deployment[last]` | unit | R20 (first passed at 03:19:01) | 2026-10-17T04:42:04+00:00 | n/a | `PASSED [ 41%]` (fails without the savepoint: `AssertionError: assert [] == ['c']`) |
| `backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql[api-chromium]` | e2e | E-S | 2026-10-17T00:21:55+00:00 | vCluster `pytest-b46f26c7-ae52-4e17-8a8e-15d522f53cf9`, `/tmp/pytest-of-root/pytest-1886/vcluster0/kubeconfig`, image `e2e-508-1792195869` | `PASSED`, `1 passed, 1 deselected, 1 warning in 241.05s (0:04:01)` |
| `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]` | e2e | E-C | 2026-10-17T02:44:57+00:00 | vCluster `pytest-f097d326-bf0b-4381-923f-bfd0d35a72bd`, `/tmp/pytest-of-root/pytest-1896/vcluster0/kubeconfig`, image `e2e-508-1792204778` | `PASSED`, `1 passed, 1 deselected, 1 warning in 299.13s (0:04:59)` |
| `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]` | e2e | E-C | 2026-10-17T02:50:55+00:00 | vCluster `pytest-7a8ba2a6-5087-4c4e-8cf5-e54219ffb4ee`, `/tmp/pytest-of-root/pytest-1897/vcluster0/kubeconfig`, image `e2e-508-1792204778` | `PASSED`, `1 passed, 1 deselected, 1 warning in 338.06s (0:05:38)` |
| `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium]` and `::test_environment_clone_lifecycle[api-chromium]` (whole shard, existing restore test rerun after `5fdbfb68`) | e2e | E-R | 2026-10-17T03:56:18+00:00 | vCluster `pytest-9a2cbfca-babd-42cb-af33-be2e77f316f5`, image `e2e-508-final-1792208899`; the log does not print the kubeconfig path | `PASSED` for both, `2 passed, 199 deselected, 1 warning in 469.80s (0:07:49)` |
| `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[ui-chromium]` and `::test_environment_clone_lifecycle[ui-chromium]` (whole shard) | e2e | E-R | 2026-10-17T04:04:52+00:00 | vCluster `pytest-fbc6560e-76e9-49d9-8d89-81bcf1cd491c`, image `e2e-508-final-1792208899` | `PASSED` for both, `2 passed, 199 deselected, 1 warning in 511.15s (0:08:31)` |

Full suites after the review fixes:

- Unit: 4193 passed, 1 skipped (2026-10-17T04:39:12Z).
- Functional: 770 passed, 2 skipped (04:40:35Z).

Before the review fixes, chunk 13 ran these:

- `uv run invoke test`: 5017 passed, 3 skipped.
- `uv run invoke validate-graphql`: 277 of 277 files passed.
- `uv run invoke format lint`: exit 0.

The review-fix commits after `6895a1d1` change log fields, the binder's validation of each reference, and one clone log line. The unit and functional suites cover them; no E2E ran after them.

## 5. Review findings

The review ran six aspects: code, comments, tests, errors, types and simplify. No finding was critical. Fixed findings are listed with their commit.

| Severity | File | Finding | Status |
|----------|------|---------|--------|
| High | `services/backup/environment.py` | A redeploy that an environment restore refuses was hard to trace. The log line had no restore id, and the count included Velero dispatch failures. | Fixed in `2079f97b`: added `environment_restore_id`, `error_code`, `path`, a separate `config_redeploy_failed` count, and a metric line. Storing the failures on `EnvironmentRestore` needs a schema change and was not made. |
| Medium | `services/scheduling/references.py` | Driver component configs reached the binder without validation. A term with both an id and a name kept the id and dropped the name, and a malformed reference was skipped. | Fixed in `79c1bd19` |
| Medium (test, rated 7 of 10) | `tests/functional/test_unit_of_work_savepoint.py` | No test checked that a block which exits normally is removed from the savepoint stack. | Fixed in `d820bbc7` |
| Medium (test, rated 6 of 10) | `tests/functional/graphql/test_deployment_reference_scenarios.py` | The #492 rename test passed even on the base code. | Fixed in `9596d318` |
| Medium | Clone documentation in 3 places | The pages said an empty-selection clone always completes. It is now refused when the environment's config names a deployment. | Fixed in `f48d76fe` |
| Medium | `services/exceptions.py`, `backup-restore.md` | One docstring and one knowledge-page count were inaccurate. | Fixed in `f48d76fe` |
| Medium (existed before) | `services/deployment.py` | `update_deployment` commits phase 1 before phase 2 resolves the terms at environment and component level. A refusal at those levels comes after the deployment's own change is saved. | Deferred |
| Medium | SDK `resources/_base.py` | `OperationFailedError` drops the GraphQL extensions, so SDK and CLI users do not get the term path. The contract fixes the message of the clone refusal. | Deferred |
| Low (reviewer rated it medium; latent) | `services/deployment.py` (ingress controller) | In a clone, the dedicated ingress controller's instance is built without `upcoming_deployments`. It does not fail today, because the ingress driver has no components and resolution returns early. | Deferred, test gap recorded |
| Low | `workflows/templates/clone.py` | A failed restore dispatch, after the counterpart row exists, is cascaded as "not cloned". | Deferred, design question |
| Low | `workflows/templates/clone.py` | The branch that stops the clone had no log line. | Fixed in `91df29bf` |
| Low | Comment and documentation wording: driver terms not cascaded, "whose capture failed", savepoint list, `DriverMismatchError`, `order_counterparts` docstring, "no live deployment", refusal lists, ADR index, R-015 | Wording did not match the code. | Fixed in `f48d76fe` |
| Low | `services/backup/clone.py` (around L501) | A malformed driver component id is parsed with a bare `UUID()`. | Deferred |
| Low | Several clone and binder paths | The counterpart cascade checks only deployment-level ids. | Deferred |
| Low | Error and type design: `UnclonedReference` invariants, a classmethod for `deleted=True`, `_CreatedEnvironment.merged_config` naming, `Mapping` parameters | The suggestions do not change behaviour. | Deferred |
| Low (tests, rated 2 to 5 of 10) | Several test files | No tests yet for: a clone with a dedicated ingress controller, binding before the ingress controller is dispatched, a dispatch failure after a counterpart row exists, a driver term re-bound in a clone, the `DELETING` state, and `updateDeployment` re-sending a name. The SDK test checks only its stub. | Deferred |
| Advisory | Simplify review | Duplicated id check in `validator.py` and `references.py`; per-level expansion in two places; `_run_environment_clone` is long; test builders are duplicated. | Deferred |

## 6. Autonomous decisions

- T001, the baseline run, was merged into chunk 1, because its only output was the T002 commit message.
- Phase 2 was split in two (T001 to T005, and T006 to T009), and so were Phase 7 (code, then E2E) and Phase 11 (documentation, then verification), to keep each chunk under about 10 tasks and 15 files.
- Chunk 3b was added; tasks.md has no such task. It fixes the nested unit-of-work rollback defect before Phases 8 and 10, which rely on savepoint isolation. It touches the shared unit of work, a high-risk area, and changes how failures in nested blocks are rolled back.
- The whole `shard_env_backup` shard was run again for both variants after the restore change. The commit `5fdbfb68` came after the clone E2E runs, and AGENTS.md asks for confirmation before relying on an older E2E pass.
- No E2E ran after the review-fix commits. They change log fields, the validation of each reference in the binder, and one log line, and the unit and functional suites cover them. Confirm whether you want another E2E run before the PR.
- Review triage:
  - The code review's top finding, the dedicated ingress controller in a clone, was rated low after a check of the code.
  - Storing restore failures on `EnvironmentRestore` was not done, because it needs a schema change and your approval.
  - E3, the term path in the SDK message, was deferred, because the contract fixes that message.
- Two behaviour changes need your review:
  - A clone request now runs the config merge when it arrives, so a source config that no longer validates is refused at once.
  - The binder now also refuses unknown keys and a `components` value that is not a list.

## 7. Suggested next steps

1. Read `pr-notes.md`, then open a PR from `fac/affinity-by-id-zsdtf`. The high-risk areas are the unit of work, the clone flow, the environment restore and the GraphQL descriptions.
2. Decide whether to run `shard_compute` and `shard_env_backup` again after the review-fix commits, or to rely on CI.
3. Decide on the deferred review findings that need your input:
   - storing restore failures on `EnvironmentRestore` (schema change);
   - the two-phase `update_deployment` saving part of a refused change;
   - whether a failed restore dispatch after a counterpart exists should cascade;
   - passing the GraphQL extensions through the SDK.
4. File the follow-up issue for showing which deployment a term names, next to the id (spec Out of Scope, critique P2). It was not filed during implementation.
