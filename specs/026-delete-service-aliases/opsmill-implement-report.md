# Implementation report: 026 deleting a deployment deletes its service aliases (#503)

**Status: INCOMPLETE.** All 37 tasks are done and their tests pass locally. The review phase stopped after three of six review aspects because the usage limit was reached. One high finding and one medium defect are not fixed yet.

- Spec dir: `specs/026-delete-service-aliases`
- Base commit: `190ca9cd`
- Head commit before this report: `a27f28f8`
- Wall-clock time: about 23:00 to 00:30 UTC, 2026-10-16 to 2026-10-17

## Chunk ledger

| # | Chunk | Tasks | Outcome | Commits | Flagged |
|---|-------|-------|---------|---------|---------|
| 1 | Phase 1 Setup | T001 | 1 ✅ | `a4cf20ca` | Run by the orchestrator: baseline of 53 unit tests passed, no file change |
| 2 | Phase 2 Foundational | T002–T007 | 6 ✅ | `b3caa922` | `is_namespace_gone_error` decodes a `bytes` body |
| 3 | Phase 3 US1 implementation | T008–T012 | 5 ✅ | `830f2c0c` | No existing test needed a change |
| 4 | Phase 4 US2 | T016–T024 | 9 ✅ | `40d65fee`, `8c2eb078` | CR read helper duplicated in `service_aliases.py` (circular import); a missing namespace counts as departing |
| 5 | Phase 5 US3 | T025–T027 | 3 ✅ | `9c1e5533` | No source change; mutation checks done |
| 6 | Phase 3 US1 E2E | T013–T015 | 3 ✅ | `72dc5299` | Passed on the first run; T013 found no dependency on `intent` in the shard |
| 7 | Phase 6 Docs | T028–T033 | 6 ✅ | `af69546c` | Also updated `dev/knowledge/backend/services.md` |
| 8 | Phase 7 Polish | T034–T037 | 4 ✅ | `a27f28f8` | UI session runs 1 test (the rename test has been `api_only` since `545738fe`) |

## Tasks not completed

None. All 37 tasks are `[X]`.

## Local-pass evidence

The full commands, timestamps and environment for each run are in the chunk reports and in [e2e-evidence.md](e2e-evidence.md).

| Test id | Type | Run command | Passed at (ISO 8601) | Environment | Pass line |
|---------|------|-------------|----------------------|-------------|-----------|
| `test_apply_service.py` (4 tests) | unit | `uv run pytest backend/tests/unit/agent/test_apply_service.py backend/tests/unit/agent/test_namespace_primitives.py backend/tests/unit/agent/test_delete_service.py -v` | 2026-10-16T23:03:22+00:00 | n/a | `19 passed in 0.14s` |
| `test_namespace_primitives.py` (11 nodes) | unit | same | 2026-10-16T23:03:22+00:00 | n/a | `19 passed in 0.14s` |
| `test_deployment_deletion_operator.py` US1 tests (6) | unit | `uv run pytest backend/tests/unit/test_deployment_deletion_operator.py backend/tests/unit/agent/test_kopf_deletion_cycle.py backend/tests/unit/test_restore_recovery_cross_target.py -v` | 2026-10-16T23:11:42+00:00 | n/a | `40 passed` |
| `test_service_aliases.py` `TestOwnerNamespace`, `TestFindDepartingNamespaces`, `TestApplyServiceAliasesFlow` (18 nodes) | unit | `uv run pytest backend/tests/unit/agent/test_service_aliases.py backend/tests/unit/services/test_context_deleting_peer_services.py -v` | 2026-10-16T23:23:51+00:00 | n/a | `34 passed in 0.17s` |
| `test_context_deleting_peer_services.py::test_generate_context_lists_the_services_of_a_deleting_peer` | unit | same | 2026-10-16T23:23:51+00:00 | n/a | `PASSED` |
| `test_deployment_deletion_operator.py` US3 tests (14 nodes, 1 modified) | unit | `uv run pytest backend/tests/unit/test_deployment_deletion_operator.py -v` | 2026-10-16T23:29:05+00:00 | n/a | `36 passed` |
| `test_service_discovery.py::test_deleted_deployment_leaves_no_alias[api-chromium]` | e2e | `STYRMIN_IMAGE_VER=e2e-503-1792193732 uv run pytest backend/tests/e2e/test_service_discovery.py -k api-chromium -v -s --pdb` | 2026-10-16T23:38:33Z | vCluster `pytest-31c5f1a9-…`, `/tmp/pytest-of-root/pytest-1870/vcluster0/kubeconfig` | `3 passed, 3 deselected` |
| same module `[ui-chromium]` | e2e | same with `-k ui-chromium`, `STYRMIN_IMAGE_VER=e2e-503-1792194439` | 2026-10-16T23:53:13Z | vCluster `pytest-7b9d70a7-…`, `/tmp/pytest-of-root/pytest-1874/vcluster0/kubeconfig` | `1 passed, 2 skipped, 3 deselected` |
| same module `[api-chromium]`, quickstart run with `kubectl` checks | e2e | `-k api-chromium`, same image | 2026-10-16T23:57:42Z | vCluster `pytest-3804abbd-…`, `/tmp/pytest-of-root/pytest-1877/vcluster0/kubeconfig` | `3 passed, 3 deselected` |

Full suites:

- Unit tests: `4183 passed, 1 skipped`.
- `uv run invoke test`: `4980 passed, 3 skipped`.
- Docs build: `[SUCCESS]`.

## Review findings

Three of six review aspects ran: code, comments and tests. The errors, types and simplify aspects did not run. No finding is fixed yet.

| Severity | Source | File | Summary | Status |
|----------|--------|------|---------|--------|
| High | tests | `backend/tests/unit/agent/test_service_aliases.py:601,650` | The fake `find_departing_namespaces` ignores its argument, so no test checks which namespaces each read covers | Not fixed |
| Medium, treated as high | code | `backend/styrmin_backend/agent/tasks/service_aliases.py:233,354-374` | The second read counts a `Terminating` or missing namespace as departing, so during a restore a flow deletes a live alias it just wrote. This goes against FR-017 and the CONTEXT.md entry | Not fixed |
| Medium | tests | `test_service_aliases.py:494-504` | No state-table row has a `Terminating` namespace without a deletion request | Not fixed |
| Medium | tests | `test_deployment_deletion_operator.py:565` | The delete handler with `deletionRequested: true` is not tested | Not fixed |
| Medium | comments | `dev/knowledge/backend/orchestration-flows.md:313` | The reason given for not creating a namespace is wrong for a restore, where no flow runs | Not fixed |
| Low | code | `service_aliases.py:354-361`, `orchestration-flows.md:311` | Written aliases whose holder namespace is departing are kept. On the `kubectl delete` path that namespace is not deleted, so the alias stays | Not fixed; part of the same fix |
| Low | code | `service_aliases.py:213-226` | `_read_styrmin_deployment` duplicates `orchestration.py:173-184` | Deferred |
| Low | comments | `service_aliases.py:13`, `changelog/503.fixed.md` | They say the flow never writes such aliases; it can, and then deletes them | Not fixed |
| Low | comments | `primitives.py:182`, `service_aliases.py:257`, `orchestration-flows.md:312` | They give a narrower reason for a skipped write than `is_namespace_gone_error` accepts (any 404) | Not fixed |
| Low | comments | `dev/knowledge/agent/operator.md:102` | "Both deletion paths run it" leaves out the skip-teardown annotation | Not fixed |
| Low | comments | `docs/docs/drivers/generic-app.md:139-141` | It says the deployment's name stops resolving; it is the names of its services | Not fixed |
| Low | tests | `test_namespace_primitives.py:90` | The RBAC 403 and the error-message check use only a text body; the API returns `bytes` | Not fixed |
| Low (pre-existing) | comments | `styrmin_deployment.py:1210,1236`, `operator.md:100` | Step 2 is called "Services/Middlewares" but deletes only Services | Out of scope |

Planned fix for the restore and holder findings:

- Make the second read count a namespace only when its StyrminDeployment has `spec.deletionRequested`, or has a `deletionTimestamp` while the namespace is `Active`. These are the conditions under which the teardown deletes aliases.
- Delete the written aliases of such owners whatever namespace holds them.

## Autonomous decisions

- T001 was run by the orchestrator instead of a subagent, because it changes no file.
- The US1 E2E tasks (T013–T015) ran after US2 and US3, so the E2E run tested the final code. The dependencies in tasks.md allow this.
- Phase 4 (9 tasks) was kept as one chunk so the suite would not be broken between chunks.
- The code review's medium finding (restore deletes a live alias) is treated as high, because it silently breaks name lookups between running deployments.

## Suggested next steps

1. Fix the review findings above:
   - the second-read rule and the holder rule, with the unit tests the tests review asked for;
   - the documentation and changelog wording.
2. Re-run the `api-chromium` session of `test_service_discovery.py` and add the run to `e2e-evidence.md`.
3. Run the three remaining review aspects: errors, types and simplify.
4. Rerun `speckit-opsmill-implement`, or finish by hand, then open a PR.
