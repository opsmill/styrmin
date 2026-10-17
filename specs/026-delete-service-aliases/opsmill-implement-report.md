# Implementation report: 026 deleting a deployment deletes its service aliases (#503)

**Status: DONE.** All 37 tasks are done. Every new or changed test passed locally. All six review aspects ran, and the high findings are fixed. One trade-off in the fix needs a maintainer decision on FR-007 (see "Autonomous decisions").

- Spec dir: `specs/026-delete-service-aliases`
- Base commit: `190ca9cd`
- Head commit before this report: `4e8bd531`
- Wall-clock time: 2026-10-16T23:00Z to 2026-10-17T02:30Z, with a pause for a usage limit between the review aspects

## Chunk ledger

| # | Chunk | Tasks | Outcome | Commits | Flagged |
|---|-------|-------|---------|---------|---------|
| 1 | Phase 1 Setup | T001 | 1 ✅ | `a4cf20ca` | Run by the orchestrator: baseline of 53 unit tests passed, no file change |
| 2 | Phase 2 Foundational | T002–T007 | 6 ✅ | `b3caa922` | `is_namespace_gone_error` decodes a `bytes` body |
| 3 | Phase 3 US1 implementation | T008–T012 | 5 ✅ | `830f2c0c` | No existing test needed a change |
| 4 | Phase 4 US2 | T016–T024 | 9 ✅ | `40d65fee`, `8c2eb078` | CR read helper duplicated in `service_aliases.py` because of a circular import |
| 5 | Phase 5 US3 | T025–T027 | 3 ✅ | `9c1e5533` | No source change; mutation checks done |
| 6 | Phase 3 US1 E2E | T013–T015 | 3 ✅ | `72dc5299` | Passed on the first run; T013 found no other test that depends on `intent` in the shard |
| 7 | Phase 6 Docs | T028–T033 | 6 ✅ | `af69546c` | Also updated `dev/knowledge/backend/services.md` |
| 8 | Phase 7 Polish | T034–T037 | 4 ✅ | `a27f28f8` | The UI session runs 1 test (the rename test has been `api_only` since `545738fe`) |
| 9 | Review fixes | review findings | 6 ✅ | `32d0fd2f`, `88a66613`, `4e8bd531` | Second-read trade-off (see "Autonomous decisions"); dated notes added to `plan.md`, research R-004, the contract and the data model |

The first version of this report (`d3703200`) recorded the run as stopped during the review.

## Tasks not completed

None. All 37 tasks are `[X]`.

## Local-pass evidence

The chunk reports and [e2e-evidence.md](e2e-evidence.md) hold the full node lists, commands and environment.

| Test id | Type | Run command | Passed at (ISO 8601) | Environment | Pass line |
|---------|------|-------------|----------------------|-------------|-----------|
| `test_apply_service.py` (4 tests) | unit | `uv run pytest backend/tests/unit/agent/test_apply_service.py backend/tests/unit/agent/test_namespace_primitives.py backend/tests/unit/agent/test_delete_service.py -v` | 2026-10-16T23:03:22+00:00 | n/a | `19 passed in 0.14s` |
| `test_namespace_primitives.py` (11 nodes; 2 `bytes`-body nodes added in the review fixes) | unit | same; rerun in the review-fix command below | 2026-10-17T02:25:51Z | n/a | `PASSED` (each node) |
| `test_deployment_deletion_operator.py` US1 tests (6) | unit | `uv run pytest backend/tests/unit/test_deployment_deletion_operator.py backend/tests/unit/agent/test_kopf_deletion_cycle.py backend/tests/unit/test_restore_recovery_cross_target.py -v` | 2026-10-16T23:11:42+00:00 | n/a | `40 passed` |
| `test_deployment_deletion_operator.py` US3 tests (14 nodes, 1 changed) | unit | `uv run pytest backend/tests/unit/test_deployment_deletion_operator.py -v` | 2026-10-16T23:29:05+00:00 | n/a | `36 passed` |
| `test_context_deleting_peer_services.py::test_generate_context_lists_the_services_of_a_deleting_peer` | unit | `uv run pytest backend/tests/unit/agent/test_service_aliases.py backend/tests/unit/services/test_context_deleting_peer_services.py -v` | 2026-10-16T23:23:51+00:00 | n/a | `PASSED` |
| Review fixes: `test_service_aliases.py` `TestBuildExternalNameService`, `TestOwnerNamespace`, `TestFindDepartingNamespaces` (two 9-row state tables), `TestApplyServiceAliasesFlow` (rewritten); `test_deployment_deletion_operator.py::test_delete_handler_with_a_deletion_request_deletes_aliases_in_a_terminating_namespace`, `::test_delete_service_aliases_compares_the_labels_with_the_canonical_id` | unit | `uv run pytest backend/tests/unit/agent/test_service_aliases.py backend/tests/unit/agent/test_namespace_primitives.py backend/tests/unit/agent/test_apply_service.py backend/tests/unit/test_deployment_deletion_operator.py backend/tests/unit/services/test_context_deleting_peer_services.py -v -p no:cacheprovider` | 2026-10-17T02:25:51Z | n/a | `110 passed in 0.33s` |
| `test_service_discovery.py` module `[api-chromium]`, including `test_deleted_deployment_leaves_no_alias` | e2e | `STYRMIN_IMAGE_VER=e2e-503-1792193732 uv run pytest backend/tests/e2e/test_service_discovery.py -k api-chromium -v -s --pdb` | 2026-10-16T23:38:33Z | vCluster `pytest-31c5f1a9-…`, `/tmp/pytest-of-root/pytest-1870/vcluster0/kubeconfig` | `3 passed, 3 deselected` |
| same module `[ui-chromium]` | e2e | same with `-k ui-chromium`, `STYRMIN_IMAGE_VER=e2e-503-1792194439` | 2026-10-16T23:53:13Z | vCluster `pytest-7b9d70a7-…`, `/tmp/pytest-of-root/pytest-1874/vcluster0/kubeconfig` | `1 passed, 2 skipped, 3 deselected` |
| same module `[api-chromium]`, quickstart run with the `kubectl` checks | e2e | `-k api-chromium`, same image | 2026-10-16T23:57:42Z | vCluster `pytest-3804abbd-…`, `/tmp/pytest-of-root/pytest-1877/vcluster0/kubeconfig` | `3 passed, 3 deselected` |
| same module `[api-chromium]` after the review fixes | e2e | `STYRMIN_IMAGE_VER=e2e-503-1792203741 uv run pytest backend/tests/e2e/test_service_discovery.py -k api-chromium -v -s --pdb` | 2026-10-17T02:27:59Z | vCluster `pytest-fc2c9cbe-…`, `/tmp/pytest-of-root/pytest-1892/vcluster0/kubeconfig` | `3 passed, 3 deselected` |

Full suites:

- Unit tests after the review fixes: `4208 passed, 1 skipped`.
- `uv run invoke test` before the review fixes: `4980 passed, 3 skipped`.
- Docs build: `[SUCCESS]`.

The `ui-chromium` session was not run again after the review fixes. Its only test, `test_service_discovery_between_apps`, does not cover a deletion. The fixes changed only the deletion paths and the alias builder's parameter name.

## Review findings

All six aspects ran: code, comments, tests, errors, types and simplify.

| Severity | Aspect | File | Summary | Status |
|----------|--------|------|---------|--------|
| High | tests | `test_service_aliases.py` flow tests | The fake departing check ignored its argument, so no test checked which namespaces each read covers | Fixed in `32d0fd2f` |
| Medium, treated as high | code | `service_aliases.py` second read | A restore's namespace deletion made the flow delete a live alias it had just written | Fixed in `32d0fd2f` |
| Medium | tests | `test_service_aliases.py` state table | No row had a `Terminating` namespace without a deletion request | Fixed in `32d0fd2f` |
| Medium | tests | `test_deployment_deletion_operator.py` | The delete handler with `deletionRequested: true` was not tested | Fixed in `32d0fd2f` |
| Medium | comments | `orchestration-flows.md` | Wrong reason given for creating no namespace during a restore | Fixed in `88a66613` |
| Medium | types | `service_aliases.py` `build_external_name_service` | `owner_namespace` meant the holder namespace there | Fixed: renamed to `holder_namespace` |
| Medium | simplify | `test_service_discovery.py` | `_wait_for_deleted` repeated `wait_for_deployment_status` | Fixed in `4e8bd531` |
| Low | code | `service_aliases.py` | Written aliases whose holder namespace was departing were kept | Fixed in `32d0fd2f` |
| Low | comments | docstring, changelog, `operator.md`, `generic-app.md`, `is_namespace_gone_error` wording | Text said more or less than the code does | Fixed in `32d0fd2f` and `88a66613` |
| Low | types | `styrmin_deployment.py` id guard; `WrittenAlias.resource_version` default | Id not normalized; a missing version silently removed the version check on the delete | Fixed in `32d0fd2f` |
| Low | errors | `service_aliases.py` skip and delete logs | Logs did not name the departing namespace or say whether a delete removed anything | Fixed in `32d0fd2f` |
| Low | tests | `test_namespace_primitives.py` | No `bytes` bodies in the tests | Fixed in `32d0fd2f` |
| Low | code, simplify | `service_aliases.py` `_read_styrmin_deployment` | Duplicates `orchestration.py:173-184` | Deferred (circular import) |
| Low | errors | `service_aliases.py` `_is_departing` | A failed peer read raises a bare `ApiException` that does not name the namespace | Deferred |
| Low | types | `primitives.py` `is_namespace_gone_error` | A 404 from the replace after a 409 also counts as gone | Deferred; the wording now says the namespace or the Service is gone |
| Low | simplify | several | Shared helpers (`is_namespace_terminating`, `list_service_aliases`), dropping the message check and the label fallback, merging tests | Deferred |
| Low (pre-existing) | comments | `styrmin_deployment.py`, `operator.md` | Teardown step 2 is named "Services/Middlewares" but deletes only Services | Out of scope |

## Autonomous decisions

- **The second read leaves one case open, and FR-007 needs a decision.** After the review, the flow's second read follows the operator teardown's rule: a deletion request, or a `deletionTimestamp` while the namespace is `Active`.
  - Why: this keeps a restore from deleting a live alias.
  - Cost: when the StyrminDeployment is already removed at the second read, the read cannot tell a deletion from a restore, so it keeps the alias.
  - When an alias can remain: it was written after the delete handler's teardown listed the aliases and before the StyrminDeployment was removed. For that, the flow's first read and its write have to span the whole teardown and the start of the namespace deletion.
  - Nothing removes such an alias later, because a flow's stale-alias cleanup covers only its own deployment's aliases. It stays until a deployment with the same service name replaces it.
  - FR-007 says no alias remains. The spec was not changed. Confirm the trade-off, or ask for another way to tell a restore from a deletion.
- T001 was run by the orchestrator, because it changes no file.
- The US1 E2E tasks (T013–T015) ran after US2 and US3, so the E2E run tested the final code. The dependencies in tasks.md allow this.
- Phase 4 (9 tasks) was kept as one chunk, so the suite was not left broken between chunks.
- The code review's medium finding was treated as high, because it silently breaks name lookups between running deployments.
- The review-fix pass added dated notes to `plan.md`, research R-004, the contract and the data model. This command normally does not edit those files. The notes record the rule change.
- Cheap low findings in the same code were fixed in the same pass. The others are deferred and listed above.

## Suggested next steps

1. Decide on the FR-007 trade-off above. Then update spec.md, or ask for a different second-read rule.
2. Open a PR. Call out the high-risk areas (operator teardown, and flows that write into other deployments' namespaces) and link [pr-notes.md](pr-notes.md) and [e2e-evidence.md](e2e-evidence.md).
3. Optionally, file issues for the deferred low findings and for research R-010 (a deployment's own flow can create its own namespace again after its deletion was requested).
