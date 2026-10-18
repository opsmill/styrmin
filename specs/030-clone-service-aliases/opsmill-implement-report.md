# Implementation Report: A Clone Writes Its Own Service Aliases and Restores None of the Source's (#530)

**Status: DONE.** All 38 tasks are done, every new or modified test has local-pass evidence, and the review's High findings are fixed.

| Item | Value |
|---|---|
| Feature | [#530](https://github.com/opsmill/styrmin/issues/530): after an environment clone, each counterpart held the source's service aliases |
| Spec dir | `/home/ubuntu/emdash/worktrees/styrmin-fatih2-ef968ca0/fac-alias-clone-fix-l1vzt/specs/030-clone-service-aliases` |
| Base commit (review diff) | `f816ac25` (last commit of the prep phase) |
| `HEAD` at the start of this run | `3a3c6982` (all tasks were already done) |
| Head commit (before this report) | `e52c8600` |
| Implementation | Earlier session, commits `202c091a` to `3a3c6982`, 2026-10-18T11:19:08Z to 2026-10-18T12:56:08Z |
| This run (review and report) | About 2026-10-18T22:35Z to 2026-10-18T23:05Z. The start time is approximate. |

## 1. What this run did

- **Preflight:** every task in `tasks.md` was already `[X]` and the working tree was clean, so no chunk was dispatched. The implementation had been committed in an earlier session, and no review or report had been made.
- **Review:** this run reviewed `f816ac25..3a3c6982` with the six review agents.
- **Fixes:** the High findings were fixed in three commits: `f7bb114f`, `8da6967e` and `e52c8600`.
- **Evidence:** the unit and functional tests were run again, because the earlier session recorded only totals for them and this report needs a pass line per test.

## 2. Chunk-by-chunk ledger

The chunks ran in the earlier session. This ledger maps each commit to its tasks from the checkboxes that the commit ticked in `tasks.md`. The earlier subagents' reports are not available, so the "Flagged" column quotes commit messages and [e2e-evidence.md](e2e-evidence.md).

| # | Chunk (phase of `tasks.md`) | Tasks | ✅ / ⚠️ / ❌ | Commits | Flagged |
|---|---|---|---|---|---|
| 1 | Phase 1: Setup | T001 | 1 / 0 / 0 | `202c091a` | Baseline: 276 tests passed in the seven affected files. |
| 2 | Phase 2: Foundational | T002 to T004 | 3 / 0 / 0 | `82af8343` | None. |
| 3 | Phase 3: User Story 1 | T005 to T015 | 11 / 0 / 0 | `7ee6cb7f`, `084be5ce`, `57ddcec4` | None. |
| 4 | Phase 4: User Story 2 | T016 | 1 / 0 / 0 | `c3726101` | None. |
| 5 | Phase 5: User Story 3 | T017 to T024 | 8 / 0 / 0 | `693f73f6`, `362ede28` | `schema.graphql` changed in its descriptions only. |
| 6 | Phase 6: User Story 4 | T025 | 1 / 0 / 0 | `28b1bfc8` | The SC-003 check cannot tell whether Velero restored the alias or the update flow of the second deployment rewrote it ([pr-notes.md](pr-notes.md)). |
| 7 | Phase 7: Documentation | T026 to T032 | 7 / 0 / 0 | `93f757b2` | None. |
| 8 | Phase 8: Polish and verification | T033 to T038 | 6 / 0 / 0 | `1d9f7ce3`, `73d9d4bf`, `b364b819`, `405813a7`, `3a3c6982` | The first `api-chromium` session failed in the SC-001 check, because the check called the `deployment` query for an internal deployment. Fixed in the test in `73d9d4bf`; the second session passed. |

Total: 38 ✅, 0 ⚠️, 0 ❌.

## 3. Tasks not completed

None. Every task in `tasks.md` is `[X]`.

## 4. Local-pass evidence

The unit and functional rows come from runs in this worktree, at `/home/ubuntu/emdash/worktrees/styrmin-fatih2-ef968ca0/fac-alias-clone-fix-l1vzt`. The E2E rows come from [e2e-evidence.md](e2e-evidence.md), which the earlier session recorded.

The unit and functional runs:

- **Run A:** at commit `3a3c6982`, from 2026-10-18T22:40:03Z to 22:40:37Z. Summary line: `============================= 307 passed in 20.21s =============================`. Command:
  ```
  uv run pytest backend/tests/unit/agent/test_backup_builders.py backend/tests/unit/agent/test_service_aliases.py backend/tests/unit/agent/tasks/test_remediation_flow_steps.py backend/tests/unit/workflows/test_restore_steps.py backend/tests/unit/workflows/test_restore_workflow_failure_handler.py backend/tests/unit/services/backup/test_environment_clone_status.py backend/tests/unit/test_restore_recovery_cross_target.py backend/tests/functional/graphql/test_environment_clone.py -v -p no:cacheprovider
  ```
- **Run B:** the two tests added by the review fix, at the tree of `f7bb114f`, from 2026-10-18T22:51:26Z to 22:51:33Z. Summary line: `============================== 2 passed in 3.34s ===============================`. Both tests failed against the code of `3a3c6982` (`2 failed in 3.39s`). Command:
  ```
  uv run pytest <node id> -v -p no:cacheprovider
  ```
- **Run C:** after the review fix, at the tree of `f7bb114f`, from 2026-10-18T22:51:59Z to 22:52:21Z. Summary line: `882 passed in 14.25s`. Command:
  ```
  uv run pytest backend/tests/unit/agent/test_backup_builders.py backend/tests/unit/agent/test_service_aliases.py backend/tests/unit/agent/tasks/test_remediation_flow_steps.py backend/tests/unit/workflows/ backend/tests/unit/services/backup/ backend/tests/unit/test_restore_recovery_cross_target.py backend/tests/unit/test_deployment_deletion_operator.py backend/tests/functional/graphql/test_environment_clone.py -q
  ```
- **Run D:** after the description fix, at `8da6967e`, at 2026-10-18T22:58:16Z. Summary line: `168 passed in 6.11s`. Command:
  ```
  uv run pytest backend/tests/functional/graphql/test_environment_clone.py backend/tests/unit/services/backup/test_environment_clone_status.py -q
  ```

The functional tests start their own temporary server and database. The unit tests need no environment.

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---|---|---|---|---|---|
| `backend/tests/unit/agent/test_backup_builders.py::TestBuildVeleroRestore::test_cross_target_restore_leaves_out_the_service_aliases` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_cross_target_restore_leaves_out_the_service_aliases PASSED` |
| `backend/tests/unit/agent/test_backup_builders.py::TestBuildVeleroRestore::test_in_place_restore_has_no_label_selector` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_in_place_restore_has_no_label_selector PASSED` |
| `backend/tests/unit/agent/test_backup_builders.py::TestBuildVeleroRestore::test_restores_do_not_share_the_label_selector` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_restores_do_not_share_the_label_selector PASSED` |
| `backend/tests/unit/agent/test_service_aliases.py::TestCounterpartAliases::test_aliases_join_the_counterparts_and_name_no_source_namespace` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_aliases_join_the_counterparts_and_name_no_source_namespace PASSED` |
| `backend/tests/unit/agent/tasks/test_remediation_flow_steps.py::test_alias_step_uses_the_services_that_the_server_lists_now` (modified) | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_alias_step_uses_the_services_that_the_server_lists_now PASSED` |
| `backend/tests/unit/agent/tasks/test_remediation_flow_steps.py`: all 18 tests (fixtures `cluster`, `with_aliases` and `without_aliases` modified) | unit | Run A | 2026-10-18T22:40:37Z | n/a | 18 lines `test_remediation_flow_steps.py::... PASSED` |
| `backend/tests/unit/agent/tasks/test_remediation_flow_steps.py::test_create_failing_alias_read_records_the_alias_step_failed` (added by the review) | unit | Run B | 2026-10-18T22:51:33Z | n/a | `...::test_create_failing_alias_read_records_the_alias_step_failed PASSED [100%]` |
| `backend/tests/unit/workflows/test_restore_steps.py::test_a_cross_target_restore_writes_the_aliases_after_the_recovery` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_a_cross_target_restore_writes_the_aliases_after_the_recovery PASSED` |
| `backend/tests/unit/workflows/test_restore_steps.py::test_an_in_place_restore_writes_no_aliases` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_an_in_place_restore_writes_no_aliases PASSED` |
| `backend/tests/unit/workflows/test_restore_steps.py::test_a_cross_target_restore_that_fails_before_its_end_writes_no_aliases[recovery-failed]` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_a_cross_target_restore_that_fails_before_its_end_writes_no_aliases[recovery-failed] PASSED` |
| `backend/tests/unit/workflows/test_restore_steps.py::test_a_cross_target_restore_that_fails_before_its_end_writes_no_aliases[velero-failed]` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_a_cross_target_restore_that_fails_before_its_end_writes_no_aliases[velero-failed] PASSED` |
| `backend/tests/unit/workflows/test_restore_steps.py::test_a_refused_alias_write_fails_the_alias_step_and_the_recovery` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_a_refused_alias_write_fails_the_alias_step_and_the_recovery PASSED` |
| `backend/tests/unit/workflows/test_restore_steps.py::test_a_failed_alias_read_fails_the_alias_step_and_the_recovery` (added by the review) | unit | Run B | 2026-10-18T22:51:33Z | n/a | `...::test_a_failed_alias_read_fails_the_alias_step_and_the_recovery PASSED [ 50%]` |
| `backend/tests/unit/workflows/test_restore_steps.py::test_a_refused_alias_write_fails_the_restore_and_the_counterpart` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_a_refused_alias_write_fails_the_restore_and_the_counterpart PASSED` |
| `backend/tests/unit/workflows/test_restore_steps.py::test_restore_workflow_gives_a_cross_target_restore_the_counterpart_context` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_restore_workflow_gives_a_cross_target_restore_the_counterpart_context PASSED` |
| `backend/tests/unit/workflows/test_restore_steps.py::test_restore_workflow_gives_an_in_place_restore_no_counterpart_context` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_restore_workflow_gives_an_in_place_restore_no_counterpart_context PASSED` |
| `backend/tests/unit/workflows/test_restore_steps.py::test_the_counterpart_context_reaches_the_user_flow_as_a_context` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_the_counterpart_context_reaches_the_user_flow_as_a_context PASSED` |
| `backend/tests/unit/workflows/test_restore_steps.py`: all 22 tests (fixtures and `_user_flow` modified) | unit | Run A | 2026-10-18T22:40:37Z | n/a | 22 lines `test_restore_steps.py::... PASSED` |
| `backend/tests/unit/workflows/test_restore_workflow_failure_handler.py`: all 6 tests (`_run_restore_workflow` modified) | unit | Run A | 2026-10-18T22:40:37Z | n/a | 6 lines `test_restore_workflow_failure_handler.py::... PASSED` |
| `backend/tests/unit/test_restore_recovery_cross_target.py`: all 15 tests (they use `backend/tests/unit/counterpart_crd_fixtures.py`, which was modified) | unit | Run A | 2026-10-18T22:40:37Z | n/a | 15 lines `test_restore_recovery_cross_target.py::... PASSED` |
| `backend/tests/unit/services/backup/test_environment_clone_status.py::test_a_cloned_entry_whose_restore_failed_reads_failed_with_the_error` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_a_cloned_entry_whose_restore_failed_reads_failed_with_the_error PASSED` |
| `backend/tests/unit/services/backup/test_environment_clone_status.py::test_a_failed_restore_without_an_error_gives_the_reason_alone` | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_a_failed_restore_without_an_error_gives_the_reason_alone PASSED` |
| `backend/tests/unit/services/backup/test_environment_clone_status.py::test_every_other_entry_is_read_as_stored`: 6 cases (`cloned-restore-in-progress`, `cloned-restore-completed`, `cloned-restore-missing`, `cloned-no-restore`, `skipped`, `failed`) | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_every_other_entry_is_read_as_stored[<case>] PASSED`, one line per case |
| `backend/tests/unit/services/backup/test_environment_clone_status.py::test_the_entries_read_agree_with_the_derived_status`: 3 cases (`one-failed-one-completed`, `both-failed`, `both-completed`) | unit | Run A | 2026-10-18T22:40:37Z | n/a | `...::test_the_entries_read_agree_with_the_derived_status[<case>] PASSED`, one line per case |
| `backend/tests/functional/graphql/test_environment_clone.py::test_a_cloned_entry_whose_restore_failed_reads_failed_on_every_read` (with the modified operation `list_environment_clones.graphql`) | functional | Run A, again in Run D | 2026-10-18T22:40:37Z; Run D at 2026-10-18T22:58:16Z | Temporary server and database from the test fixtures | `...::test_a_cloned_entry_whose_restore_failed_reads_failed_on_every_read PASSED` |
| `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium]` | e2e | `uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle" "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" -k api-chromium -v -s --pdb`, with `STYRMIN_IMAGE_VER=e2e-530-1792325479` | 2026-10-18T12:34:02Z | vcluster `pytest-17181d4c-5275-4329-9a90-cf4fbb4fd38f`; kubeconfig `/tmp/pytest-of-root/pytest-2021/vcluster0/kubeconfig`; commit `73d9d4bf` | `...::test_environment_backup_and_restore_lifecycle[api-chromium] ... PASSED` |
| `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]` | e2e | Same session as the row above | 2026-10-18T12:34:02Z | Same as the row above | `...::test_environment_clone_lifecycle[api-chromium] PASSED` |
| `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[ui-chromium]` | e2e | The same command with `-k ui-chromium` | 2026-10-18T12:46:44Z | vcluster `pytest-cd1a98bd-0f3d-44ec-abac-44aec202970b`; kubeconfig `/tmp/pytest-of-root/pytest-2022/vcluster0/kubeconfig`; commit `b364b819` | `...::test_environment_backup_and_restore_lifecycle[ui-chromium] ... PASSED` |
| `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]` | e2e | Same session as the row above | 2026-10-18T12:46:44Z | Same as the row above | `...::test_environment_clone_lifecycle[ui-chromium] PASSED` |

Notes on the evidence:

- Each `...` stands for the node id given in the "Test id" cell.
- The E2E pass lines are quoted in full, with the fixture output between the node id and `PASSED`, in [e2e-evidence.md](e2e-evidence.md).
- Each E2E session ends with the summary line `2 passed, 2 deselected, 1 warning`.
- The E2E sessions ran before the review fix `f7bb114f`. See §6, decision 6.

## 5. Review findings

Six review agents ran on `f816ac25..3a3c6982`: code, comments, tests, errors, types and simplify. All six are on by default, and the project has no review configuration.

### Fixed in this run

| Severity | File | Finding | Raised by | Fix |
|---|---|---|---|---|
| High | `backend/styrmin_backend/agent/tasks/service_aliases.py` (`apply_service_aliases_step`) | The step read the peers' services and the cluster's aliases before it opened. When one of these reads failed in a clone's restore, the restore was `FAILED` but no step held the error, which breaks FR-004 and SC-004. | errors (Medium), tests (Medium), comments (Low), code (Low) | `f7bb114f`: the read error is raised again inside the step, which records it as failed. Two tests were added, and both fail without the fix. |
| High (Constitution §VII) | `docs/docs/concepts-and-architecture/backups-and-restores.md`, alias paragraph | It said that every restore restores its aliases from the backup and that nothing writes them afterwards. Both are false for the restore of a clone. | comments | `8da6967e` |
| High (Constitution §VII) | `dev/knowledge/backend/backup-restore.md`, `dev/knowledge/backend/api.md`, `dev/knowledge/frontend/deployment-timeline.md`, `CONTEXT.md` ("Step"), `backups-and-restores.md` | These pages said that a restore has three steps. The restore of a clone records a fourth step. | comments, and the docs-fix subagent for `CONTEXT.md` | `8da6967e`, `e52c8600` |
| High (Constitution §VII) | `dev/adr/0056-environment-clone-record-and-cross-target-restore.md`, amendment | It gave the wrong reason why pods and Services are still restored under the label selector. | comments | `8da6967e` |
| Medium | `api/definitions/backup/environment_clone.py`, `services/backup/clone.py`, `schema.graphql`, `frontend/src/generated/graphql.ts` | The description said that `counterpartDeploymentId` is "null unless CLONED", and then that a `FAILED` entry keeps it. | comments (Medium), code (Low), types | `8da6967e`, descriptions only |
| Low | The same descriptions | The reason was described as "the restore's error", but the text is `the restore failed: <error>`. | comments | `8da6967e` |
| Low | `backups-and-restores.md`, failure paragraph | Readers could conclude that a failed restore also fails the entries whose affinity terms name the deployment. | comments | `8da6967e` |
| Low | `dev/knowledge/backend/backup-restore.md` | Line references were out of date, and a table row left out the failed-read case. | comments | `8da6967e`: the references now name the function next to the lines. |

### Deferred

| Severity | File | Finding | Raised by |
|---|---|---|---|
| Medium | `backend/styrmin_backend/workflows/templates/backup.py` (`execute_velero_restore_flow` parameters; `execute_restore_workflow`) | Nothing makes callers pass `counterpart_crd_body` and `counterpart_context` together. The one caller passes both. A future caller that passes only the body would get a restore that leaves out the aliases and never writes them, with no error. A check at the start of the flow, or one combined parameter, would prevent it. | types |
| Medium | `backend/tests/e2e/test_backup_restore.py`, SC-003 check | The check cannot tell whether Velero restored the alias or the update flow of the second deployment rewrote it, because the environment restore also redeploys that deployment. FR-006 is covered by the unit tests only. [pr-notes.md](pr-notes.md) already states this limit. | tests |
| Low | `agent/service/kubernetes/resources/builders/backup.py` (`build_velero_restore`) and `workflows/templates/backup.py` (`execute_restore_workflow`) | The two places decide differently whether a restore is cross-target. The selector is added when the namespaces differ, and the alias step runs when the deployment ids differ. So an in-place restore into another namespace drops the aliases and writes none. The HelmRelease exclusion already uses the namespace test. | code, types |
| Low | `workflows/templates/backup.py`, alias failure branch | The log line has no exception type and no traceback. This is the same pattern as the recovery branch. | errors |
| Low | `services/backup/clone.py` (`resolve_deployment_result`) | The reason can hold a long multi-line `ApiException` text. Restore error messages already work this way. | errors |
| Low | `agent/tasks/service_aliases.py` (`with_current_peer_services`) | When the server's list of services cannot be read, the step uses the stored context and logs only a warning, so a restore can be `COMPLETED` with aliases missing. Research R-002 allows this. | errors |
| Low | Tests for FR-005 | No test checks that updating or upgrading a `FAILED` counterpart repairs it. Today this rests on reading the code (research R-005). | tests |
| Low | `backend/tests/unit/agent/test_service_aliases.py` (`TestCounterpartAliases`) | The test runs only code that existed before #530. The restore wiring is covered by other tests. | tests |
| Low (10 suggestions) | `backup.py`, `clone.py`, `environment_clone.py`, `test_restore_steps.py`, `test_environment_clone_status.py`, `test_backup_restore.py` | Simplifications that keep behaviour the same. They are listed after this table. | simplify |

The simplify review's suggestions:

- Unpack `_build_counterpart_crd_body` directly, and possibly rename it.
- Use `recovery_status.update(...)` in the alias failure branch.
- Rename `failed_restore` to a private name.
- Remove the repeated description sentences from the fields.
- Merge two context tests in `test_restore_steps.py`.
- Remove two redundant assertions.
- Add an `_assert_cloned` E2E helper.
- Remove the `peer_aliases` check, which overlaps the `aliases_outside` check.
- Simplify the parsing of the `externalName` namespace.

## 6. Autonomous decisions

1. **No chunk was dispatched.** At the start, `tasks.md` had 38 of 38 tasks done and the tree was clean. The run went on to the review and the report instead of stopping. §2 is built from the commits and `tasks.md`, because the earlier subagents' reports are not available.
2. **The review base is `f816ac25`, not the `HEAD` at the start of this run.** The diff `HEAD@start..HEAD` was empty. `f816ac25` is the last commit of the prep phase, so the diff from it covers the whole implementation.
3. **The six review agents ran in parallel.** They only read files.
4. **The missing-step finding was rated High.** The reviewers rated it Medium or Low. It breaks a MUST of FR-004 and the success criterion SC-004, and the fix is small.
5. **The fix is in the shared alias step, so it also changes the create, update and upgrade flows.** In those flows a failed read is now recorded as the failed alias step "Create and delete service aliases". Before, the flow failed with no alias step recorded. This is the same rule as for the restore, and [pr-notes.md](pr-notes.md) now says so for the maintainer.
6. **The E2E tests were not run again after `f7bb114f`.**
   - The image under test in both E2E sessions was built before this commit.
   - The commit adds a path only for an exception raised by the reads. The successful path runs the same calls in the same order, and neither E2E test makes a read fail.
   - The unit tests cover the new path. Run C also covers the create, update and upgrade flows.
   - Re-running both variants takes about 45 minutes, including the image build. It is the first next step if you want E2E evidence at the final head.
7. **Documentation findings were rated High under Constitution §VII**, because the change had made those pages false. The Medium and Low documentation findings in the same files were fixed as well.
8. **The GraphQL descriptions changed again, still in their text only.** The schema diff and the frontend types diff each change two lines of description. [pr-notes.md](pr-notes.md) already asks the maintainer to confirm a change to descriptions only.
9. **[pr-notes.md](pr-notes.md) was edited twice in this run:**
   - The docs-fix subagent corrected its sentence about "null unless CLONED".
   - The orchestrator added the section on the changes made after the review.
10. **The unit and functional tests were run again (Run A)**, because the earlier session recorded only totals for them.

## 7. Suggested next steps

1. Optional: run `test_environment_clone_lifecycle` and `test_environment_backup_and_restore_lifecycle` again in both variants, on an image built at the final head, for E2E evidence that includes `f7bb114f` (decision 6).
2. Decide on the two deferred Medium findings: the check that `counterpart_crd_body` and `counterpart_context` come together, and a stronger SC-003 check.
3. Confirm the open points in [pr-notes.md](pr-notes.md):
   - the answers that the spec gave on its own
   - the change to the GraphQL descriptions
   - the change to the create, update and upgrade flows (decision 5)
4. Open the pull request.
